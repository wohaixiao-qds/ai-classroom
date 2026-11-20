"""后台任务体(M5):uvicorn spawn 的子进程入口。

用法(由 executor.start_job 调,不直接跑):
    python -m app.job_runner request_prep  <vault笔记相对路径>
    python -m app.job_runner request_research <待探主题名>

状态机回写 catalog_actions:queued → running → done(detail=课件id) / failed(detail=原因)。
注意:同一时间同一 target 只应有一个在跑(路由层已挡重复)。
"""

from __future__ import annotations

import json
import os
import signal
import sys
from typing import Any

from app.core.catalog_store import _conn, latest_job, set_status
from app.core.config import settings
from app.core.job_store import bind_material, check_plan, ensure_active, get_binding


def _action_id() -> int | None:
    if len(sys.argv) > 3:
        return int(sys.argv[3])
    row = latest_job(sys.argv[1], sys.argv[2])
    return int(row["id"]) if row else None


def _legacy_course(kind: str, target: str, material: dict[str, Any],
                   action_id: int | None) -> str | None:
    """只为有旧执行记录的任务迁移;标题相同且来源/领域一致才候选。"""
    with _conn() as conn:
        prior = conn.execute(
            "SELECT 1 FROM catalog_actions WHERE kind=? AND target=? AND id<? LIMIT 1",
            (kind, target, action_id or 0),
        ).fetchone()
    if not prior:
        return None
    candidates = []
    for path in settings.courses_dir.glob("*.csl.json"):
        try:
            course = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = course.get("meta") or {}
        if meta.get("job_binding_id"):
            continue
        same_source = bool(material.get("_material_path")) and material["_material_path"] in (
            meta.get("source_notes") or []
        )
        same_topic = (bool(material.get("topic")) and meta.get("topic") == material["topic"]
                      and course.get("title") == material.get("subtopic"))
        if same_source or same_topic:
            candidates.append(str(course["id"]))
    if len(candidates) > 1:
        raise ValueError(f"旧任务匹配到多份课件 {candidates},拒绝按同名猜测恢复")
    return candidates[0] if candidates else None


def _bound_prep(kind: str, target: str, material: dict[str, Any],
                *, prev: str | None = None, learning_goal: str = "",
                prerequisite_titles: list[str] | None = None) -> dict[str, Any]:
    from app.agent.prep import _course_path, _plan_path, run_prep

    binding = get_binding(kind, target)
    legacy_id = None if binding else _legacy_course(kind, target, material, _action_id())
    binding = bind_material(kind, target, material, legacy_course_id=legacy_id)
    binding["action_id"] = _action_id()
    ensure_active(binding)
    cid = str(binding["course_id"])
    path = _course_path(cid)
    check_plan(binding, _plan_path(cid))
    if not path.exists() and binding.get("plan_hash"):
        raise ValueError(f"绑定课件 {cid} 已丢失,拒绝重新建课覆盖恢复约定")
    resume = cid if path.exists() else None
    if resume:
        course = json.loads(path.read_text(encoding="utf-8"))
        owner = course.get("meta", {}).get("job_binding_id")
        if course.get("id") != cid or (owner and owner != binding["id"]):
            raise ValueError("绑定课件归属不匹配,拒绝续写")
        print(f"恢复绑定课件 {cid} (binding={binding['id']})")
    result = run_prep(material, prev_subtopic=prev, resume_course_id=resume, job_binding=binding,
                      learning_goal=learning_goal, prerequisite_titles=prerequisite_titles)
    ensure_active(binding)
    if result.get("course") and result["course"].get("id") != cid:
        raise ValueError("备课返回的课件 id 与任务绑定不匹配")
    return result


def _apply_outline_contract(course: dict[str, Any], framework: dict[str, Any],
                            entry: dict[str, Any], topic: str) -> None:
    """显式 refs 优先,再按同领域的大纲 id 查找;不按全库同名猜测。"""
    available: dict[str, dict[str, Any]] = {}
    for path in settings.courses_dir.glob("*.csl.json"):
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            if candidate.get("sections"):
                available[str(candidate["id"])] = candidate
        except (OSError, ValueError, KeyError):
            continue
    entries = {c["id"]: c for c in framework["courses"]}
    deps = []
    for pid in entry.get("prereqs", []):
        prerequisite = entries[pid]
        refs = list(prerequisite.get("course_refs") or [])
        if prerequisite.get("course_ref"):
            refs.append(prerequisite["course_ref"])
        for cid, candidate in available.items():
            meta = candidate.get("meta") or {}
            same_topic = meta.get("job_target") in (topic, topic + "::" + prerequisite["title"])
            if same_topic and meta.get("outline_course_id") == pid:
                refs.append(cid)
        for cid in dict.fromkeys(refs):
            if cid in available and cid != course["id"]:
                deps.append({"id": cid, "reason": f"大纲先修:{prerequisite['title']}"})
    course.setdefault("meta", {}).update(outline_course_id=entry["id"], depends_on=deps)


def _on_cancel(signum: int, _frame: Any) -> None:
    """SIGTERM → 保留任务绑定的恢复产物并置 cancelled。"""
    target = sys.argv[2]
    # 保留绑定骨架与规划,取消不再按全库同名课删除产物。
    set_status(target, "cancelled", "手动取消", action_id=_action_id())
    print("CANCELLED: 手动取消")
    sys.exit(1)


def _run() -> str:
    kind, target = sys.argv[1], sys.argv[2]
    set_status(target, "running", action_id=_action_id())
    result: dict[str, Any]
    if kind == "request_prep":
        from app.agent.prep import _material_from_note

        material = _material_from_note(target)
        material["_material_path"] = target  # vault 相对路径,课表关联靠它
        result = _bound_prep(kind, target, material)
    elif kind == "outline_prep":
        # P7·M2:大纲按课点单——原料调研→备课→按大纲钦定先修链→发布
        topic, _, course_title = target.partition("::")
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
        binding = get_binding(kind, target)
        cached = cached_material(topic, course_title)
        material = cached if cached is not None else (
            json.loads(binding["material_json"]) if binding else
            research_material(topic, course_title)
        )
        material = dict(material, _outline_course_id=outline_course["id"], _outline_topic=topic)
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
        prereq_ids = list(outline_course.get("prereqs", []))
        titles_by_id = {c["id"]: c["title"] for c in fw["courses"]}
        prereq_titles = [titles_by_id[pid] for pid in prereq_ids if pid in titles_by_id]
        prev = prereq_titles[-1] if prereq_titles else None
        result = _bound_prep(kind, target, material, prev=prev,
                             learning_goal=str(outline_course.get("goal") or ""),
                             prerequisite_titles=prereq_titles)
    elif kind == "request_research":
        # 样课先行(P5 补):一句话开课 = 先出领域大纲(零基础完整路线),
        # 再自动备大纲第一门样课;其余课在大纲里逐课点单(生成中心)
        from app.agent.research import (
            cached_framework,
            cached_material,
            research_framework,
            research_material,
        )
        from app.services.vault_sync import sync_outline, theme_area

        binding = get_binding(kind, target)
        fw = (cached_framework(target) if binding else None) or research_framework(target)
        # 大纲→vault 目录同步(全自动跟随)
        sync_outline(fw, topic=target)
        original = json.loads(binding["material_json"]) if binding else {}
        original_id = original.get("_outline_course_id")
        entry = (next((c for c in fw["courses"] if c.get("id") == original_id), None)
                 if original_id else fw["courses"][0])
        if entry is None:
            raise ValueError("原任务绑定的大纲课程已被移除,拒绝改备另一门课")
        entry_title = str(entry.get("title", target))
        print(f"样课先行:大纲 {len(fw['courses'])} 门,先备入口课「{entry_title}」")
        cached = cached_material(target, entry_title) if binding else None
        material = cached if cached is not None else (
            json.loads(binding["material_json"]) if binding else
            research_material(target, entry_title)
        )
        material = dict(material, _outline_course_id=entry["id"], _outline_topic=target)
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
        topic, outline_course = target, entry
        result = _bound_prep(kind, target, material,
                             learning_goal=str(entry.get("goal") or ""),
                             prerequisite_titles=[c["title"] for c in fw["courses"]
                                                  if c["id"] in entry.get("prereqs", [])])
    else:
        raise ValueError(f"未知任务类型: {kind}")

    if not result.get("ok"):
        # 软着陆只保留中间产物,不等于合格交付;由入口统一记 failed。
        raise RuntimeError("备课未通过校验(软着陆),产物在 courses/ 可人工接着审")
    course = result["course"]

    # 两个入口共用大纲权威先修,包括显式的空列表。
    if kind in ("outline_prep", "request_research"):
        from app.agent.prep import _course_path

        assert outline_course is not None  # 两个入口均已验证大纲课程存在
        _apply_outline_contract(course, fw, outline_course, topic)
        _course_path(str(course["id"])).write_text(
            json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    from app.services.publication import ensure_publication
    from app.services.tts_compile import publish_courses

    course = ensure_publication(
        course, material,
        learning_goal=str(outline_course.get("goal") or "")
        if kind in ("outline_prep", "request_research") and outline_course else "",
        job_binding={**(get_binding(kind, target) or {}), "action_id": _action_id()},
        prerequisite_titles=[c["title"] for c in fw["courses"]
                             if c["id"] in outline_course.get("prereqs", [])]
        if kind in ("outline_prep", "request_research") and outline_course else None,
    )
    binding = get_binding(kind, target)
    if binding:
        ensure_active({**binding, "action_id": _action_id()})
    publish_courses(str(course["id"]))

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
    action_id = _action_id()
    try:
        try:
            detail = _run()
        except Exception as e:  # noqa: BLE001 后台任务异常必须落状态
            set_status(sys.argv[2], "failed", str(e)[:200], action_id=action_id)
            print(f"FAILED: {e}")
            return 1
        set_status(sys.argv[2], "done", detail, action_id=action_id)
        print(f"DONE: {detail}")
        return 0
    finally:
        from app.services.executor import log_path_for

        pid_path = log_path_for(sys.argv[1], sys.argv[2], action_id).with_suffix(".pid")
        if pid_path.exists() and pid_path.read_text().strip() == str(os.getpid()):
            pid_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(_main())
