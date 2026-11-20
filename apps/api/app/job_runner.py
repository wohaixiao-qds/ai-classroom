"""后台任务体(M5):uvicorn spawn 的子进程入口。

用法(由 executor.start_job 调,不直接跑):
    python -m app.job_runner request_prep  <vault笔记相对路径>
    python -m app.job_runner request_research <待探主题名>

状态机回写 catalog_actions:queued → running → done(detail=课件id) / failed(detail=原因)。
注意:同一时间同一 target 只应有一个在跑(路由层已挡重复)。
"""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from typing import Any

from app.core.catalog_store import set_status


def _on_cancel(signum: int, _frame: Any) -> None:
    """手动取消(P7):SIGTERM → 清 0 节骨架课+置 cancelled,不留下半成品。"""
    kind, target = sys.argv[1], sys.argv[2]
    if kind == "outline_prep":
        course_title = target.partition("::")[2]
        from app.routes.outline import _existing_courses_index

        by_title, _, _ = _existing_courses_index()
        for cid in by_title.get(course_title, []):
            cp = Path("courses") / f"{cid}.csl.json"
            try:
                d = json.loads(cp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not d.get("sections"):
                cp.unlink(missing_ok=True)
                print(f"已清理 0 节骨架课: {cid}")
    set_status(target, "cancelled", "手动取消")
    print("CANCELLED: 手动取消")
    sys.exit(1)


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
        # 大纲→vault 目录同步(全自动跟随):主题/篇目录 + 大纲.md 快照,绑定写回 framework
        from app.services.vault_sync import sync_outline, theme_area

        sync_outline(fw, topic=topic)
        outline_course = next(
            (c for c in fw["courses"] if c.get("title") == course_title), None
        )
        if outline_course is None:
            raise ValueError(f"大纲里没有这门课: {course_title}")
        material = cached_material(topic, course_title) or research_material(
            topic, course_title
        )
        # 写回落点=大纲篇目录:topic = 领域/主题/篇(归一后即 vault 真实目录)
        area = theme_area(fw)
        if area:
            part = str(outline_course.get("part") or "").strip()
            material["topic"] = f"{area} / {part}" if part else area
        else:
            # 兜底:vault 不可用时退回待探行归位(老机制)
            from app.services.catalog import find_todo_area

            fallback = find_todo_area(course_title)
            if fallback:
                material["topic"] = fallback
        # 取消/失败重发自动判续:同名课件已在盘上 → 续写模式(载已有节继续)
        resume_cid = None
        import json as _json

        for _p in Path("courses").glob("*.csl.json"):
            try:
                cd = _json.loads(_p.read_text(encoding="utf-8"))
            except (OSError, _json.JSONDecodeError):
                continue
            if str(cd.get("title", "")) == course_title:
                resume_cid = str(cd.get("id"))
                break
        prereq_ids = list(outline_course.get("prereqs", []))
        titles_by_id = {c["id"]: c["title"] for c in fw["courses"]}
        prereq_titles = [titles_by_id[pid] for pid in prereq_ids if pid in titles_by_id]
        prev = prereq_titles[-1] if prereq_titles else None
        if resume_cid:
            print(f"检测到未完成课件 {resume_cid} → 续写模式")
            result = run_prep(material, resume_course_id=resume_cid)
        else:
            result = run_prep(material, prev_subtopic=prev)
    elif kind == "request_research":
        # 样课先行(P5 补):一句话开课 = 先出领域大纲(零基础完整路线),
        # 再自动备大纲第一门样课;其余课在大纲里逐课点单(生成中心)
        from app.agent.prep import run_prep
        from app.agent.research import research_framework, research_material
        from app.services.vault_sync import sync_outline, theme_area

        fw = research_framework(target)
        # 大纲→vault 目录同步(全自动跟随)
        sync_outline(fw, topic=target)
        entry = fw["courses"][0]  # 大纲第一门 = 入口课(无前置)
        entry_title = str(entry.get("title", target))
        print(f"样课先行:大纲 {len(fw['courses'])} 门,先备入口课「{entry_title}」")
        material = research_material(target, entry_title)
        # 写回落点=大纲篇目录;vault 不可用时退回待探行归位(老机制)
        area = theme_area(fw)
        part = str(entry.get("part") or "").strip()
        new_topic = f"{area} / {part}" if (area and part) else area
        if not new_topic:
            from app.services.catalog import find_todo_area

            new_topic = find_todo_area(entry_title) or find_todo_area(target)
        if new_topic and new_topic != material.get("topic"):
            material["topic"] = new_topic
            import json as _json
            from pathlib import Path as _Path

            mp = _Path(str(material["_material_path"]))
            mp.write_text(_json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"topic 归位: {new_topic}")
        result = run_prep(material)  # 入口课无前置,无位置感可承接
    else:
        raise ValueError(f"未知任务类型: {kind}")

    if not result.get("ok"):
        # 软着陆只保留中间产物,不等于合格交付;由入口统一记 failed。
        raise RuntimeError("备课未通过校验(软着陆),产物在 courses/ 可人工接着审")
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
        course["meta"]["outline_course_id"] = (outline_course or {}).get("id", "")
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


def _main() -> int:
    signal.signal(signal.SIGTERM, _on_cancel)
    try:
        detail = _run()
    except Exception as e:  # noqa: BLE001 后台任务:任何异常都要落状态,不能静默死掉
        set_status(sys.argv[2], "failed", str(e)[:200])
        print(f"FAILED: {e}")
        return 1
    set_status(sys.argv[2], "done", detail)
    print(f"DONE: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
