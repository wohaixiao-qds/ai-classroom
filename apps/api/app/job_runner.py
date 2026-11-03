"""后台任务体(M5):uvicorn spawn 的子进程入口。

用法(由 executor.start_job 调,不直接跑):
    python -m app.job_runner request_prep  <vault笔记相对路径>
    python -m app.job_runner request_research <待探主题名>

状态机回写 catalog_actions:queued → running → done(detail=课件id) / failed(detail=原因)。
注意:同一时间同一 target 只应有一个在跑(路由层已挡重复)。
"""

from __future__ import annotations

import sys
from typing import Any

from app.core.catalog_store import set_status


def _run() -> str:
    kind, target = sys.argv[1], sys.argv[2]
    set_status(target, "running")
    result: dict[str, Any]
    if kind == "request_prep":
        from app.agent.prep import _material_from_note, run_prep

        material = _material_from_note(target)
        material["_material_path"] = target  # vault 相对路径,课表关联靠它
        result = run_prep(material)
    elif kind == "outline_prep":
        # P7·M2:大纲按课点单——原料调研→备课→按大纲钦定先修链→发布
        topic, _, course_title = target.partition("::")
        from app.agent.prep import run_prep
        from app.agent.research import (
            cached_framework,
            cached_material,
            research_framework,
            research_material,
        )

        fw = cached_framework(topic) or research_framework(topic)
        outline_course = next(
            (c for c in fw["courses"] if c.get("title") == course_title), None
        )
        if outline_course is None:
            return f"大纲里没有这门课: {course_title}"
        material = cached_material(topic, course_title) or research_material(
            topic, course_title
        )
        # 知识版图归位:主题串(如 Agent Harness)不进版图,vault 层级才进
        from app.services.catalog import find_todo_area

        area = find_todo_area(course_title)
        if area:
            material["topic"] = area
        prereq_ids = list(outline_course.get("prereqs", []))
        titles_by_id = {c["id"]: c["title"] for c in fw["courses"]}
        prereq_titles = [titles_by_id[pid] for pid in prereq_ids if pid in titles_by_id]
        prev = prereq_titles[-1] if prereq_titles else None
        result = run_prep(material, prev_subtopic=prev)
    elif kind == "request_research":
        # 样课先行(P5 补):一句话开课 = 先出领域大纲(零基础完整路线),
        # 再自动备大纲第一门样课;其余课在大纲里逐课点单(生成中心)
        from app.agent.prep import run_prep
        from app.agent.research import research_framework, research_material
        from app.services.catalog import find_todo_area

        fw = research_framework(target)
        entry = fw["courses"][0]  # 大纲第一门 = 入口课(无前置)
        entry_title = str(entry.get("title", target))
        print(f"样课先行:大纲 {len(fw['courses'])} 门,先备入口课「{entry_title}」")
        material = research_material(target, entry_title)
        # 知识版图归位:待探项源自 vault 某层级,查到就把层级写进 topic
        # (否则「解析层」会被当独立主题挂在顶层,不进 harness/Runtime——实测踩过)
        area = find_todo_area(entry_title) or find_todo_area(target)
        if area and area != material.get("topic"):
            material["topic"] = area
            import json as _json
            from pathlib import Path as _Path

            mp = _Path(str(material["_material_path"]))
            mp.write_text(_json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"topic 归位: {area}")
        result = run_prep(material)  # 入口课无前置,无位置感可承接
    else:
        return f"未知任务类型: {kind}"

    if not result.get("ok"):
        return "备课未通过校验(软着陆),产物在 courses/ 可人工接着审"
    course = result["course"]

    # 大纲挂接(P7·M2):outline_course_id 恒写(目录出课判定靠它);
    # 先修链覆盖模型建议,只挂已出课的(前置未出课时先欠着,那门课出炉后
    # 整链会在学习路线里自然续上——按标题匹配课件)
    if kind == "outline_prep":
        import json as _json
        from pathlib import Path as _Path

        from app.agent.prep import _course_path

        by_title: dict[str, str] = {}
        for p in _Path("courses").glob("*.csl.json"):
            try:
                cd = _json.loads(p.read_text(encoding="utf-8"))
                by_title[str(cd.get("title", ""))] = str(cd.get("id", ""))
            except Exception:  # noqa: BLE001
                continue
        deps = [
            {"id": by_title[t], "reason": f"大纲先修:{t}"}
            for t in prereq_titles
            if t in by_title and by_title[t] != course["id"]
        ]
        course["meta"]["outline_course_id"] = outline_course.get("id", "")
        if deps:
            course["meta"]["depends_on"] = deps
        cp = _course_path(str(course["id"]))
        cp.write_text(_json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"大纲挂接完成:outline_course_id={course['meta']['outline_course_id']}"
            + (f",先修链={[d['id'] for d in deps]}" if deps else "")
        )

    from app.services.tts_compile import publish_courses

    publish_courses()

    # 出课自动归位(P7):新课与旧课都进最贴合的大纲位置(一次 LLM 调用;
    # 失败不影响交付,下次出课或手动「归位旧课」会再试)
    try:
        from app.services.outline_attribution import attribute_all

        r = attribute_all()
        print(
            f"归位: {len(r['placements'])} 门"
            + (f";出圈 {len(r['unplaceable'])} 门" if r["unplaceable"] else "")
        )
    except Exception as e:  # noqa: BLE001 归位失败不影响交付
        print(f"归位失败(不影响交付): {e}")
    return str(course["id"])


if __name__ == "__main__":
    try:
        detail = _run()
    except Exception as e:  # noqa: BLE001 后台任务:任何异常都要落状态,不能静默死掉
        set_status(sys.argv[2], "failed", str(e)[:200])
        print(f"FAILED: {e}")
        sys.exit(1)
    set_status(sys.argv[2], "done", detail)
    print(f"DONE: {detail}")
