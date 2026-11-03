"""课件归位(P7):把每一门已出课件归入最贴合的大纲课程位置,写 course_refs。

全局强制版:一次 LLM 调用,跨所有大纲匹配,**每门课件都必须归位**——
归属是组织(把它放进书里最合适的章节),不是内容等价判定;只覆盖一部分的
课件也归入最贴合的那门课。主题完全出圈的才允许 unplaceable。
结果逐大纲过 validate_framework 才落盘。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.agent.research import _slug, validate_framework
from app.core.config import settings
from app.core.llm import get_llm_client

MATCH_PROMPT = """你在做「课件归位」:把每一门已出课件,归入最贴合的大纲课程位置。
大纲有多本(每本有 topic 和课程列表)——把它们看成书架上的几本书。

# 大纲书架
{outlines}

# 待归位课件(每门都必须归)
{courses}

规则:
1. **每门课件都必须归位**:选内容最贴合的那门大纲课;即使只覆盖该课的一部分,
   也归入它——归属是组织,不是等价判定
2. 一门课件只归一个位置;一门大纲课可以收多门课件
3. 内容明显重复的两门课件,可以归入同一位置(学员自己挑读哪门)
4. 主题完全出圈、放进任何一本大纲都不合适的,才放入 unplaceable 并说明

只输出 JSON(不要其他内容):
{{"placements": [{{"course_id": "课件id", "outline_topic": "大纲主题名",
  "outline_course_id": "大纲课id", "reason": "一句话"}}],
 "unplaceable": [{{"course_id": "课件id", "reason": "一句话"}}]}}"""


def _outline_path(topic: str) -> Path:
    return settings.data_dir / "research" / f"{_slug(topic)}.framework.json"


def _load_outline(topic: str) -> dict[str, Any]:
    """按主题名装载大纲(routes 兼容入口;legacy 自动转大纲形态)。"""
    p = _outline_path(topic)
    if not p.exists():
        raise ValueError(f"没有「{topic}」的大纲——先开课调研出大纲")
    return _load_outline_file(p)


def _load_outline_file(p: Path) -> dict[str, Any]:
    d = json.loads(p.read_text(encoding="utf-8"))
    if "courses" not in d:  # 旧框架转大纲形态
        courses: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, s in enumerate(d.get("subtopics", []), 1):
            title = str(s.get("title", "")).strip() if isinstance(s, dict) else ""
            slug = re.sub(r"[^\w-]+", "-", title.lower()).strip("-")[:24] or f"c{i}"
            if slug in seen:
                slug = f"{slug}-{i}"
            seen.add(slug)
            why = str(s.get("why", "")) if isinstance(s, dict) else ""
            courses.append(
                {
                    "id": slug,
                    "title": title,
                    "goal": why or f"学完能讲清「{title[:20]}」",
                    "why": why,
                    "prereqs": [],
                    "origin": str(s.get("origin", "map")),
                }
            )
        d = {**d, "courses": courses, "domain": str(d.get("domain", "")), "legacy": True}
    return d


def attribute_all() -> dict[str, Any]:
    """全局归位:所有未挂接的课件 → 最贴合的大纲课。写各大纲文件的 course_refs。"""
    research_dir = settings.data_dir / "research"
    outlines: dict[str, dict[str, Any]] = {}  # topic → 大纲 dict
    for p in sorted(research_dir.glob("*.framework.json")):
        try:
            d = _load_outline_file(p)
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("courses"):
            outlines[str(d.get("topic", p.stem))] = d

    # 已被任何大纲收编的课件不再参选
    taken: set[str] = set()
    for d in outlines.values():
        for c in d["courses"]:
            taken.update(str(x) for x in (c.get("course_refs") or []) if x)
            if c.get("course_ref"):
                taken.add(str(c["course_ref"]))

    existing: list[dict[str, str]] = []
    existing_ids: set[str] = set()
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        try:
            cd = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cid = str(cd.get("id", ""))
        existing_ids.add(cid)
        if cid in taken:
            continue
        units = cd.get("sections") or cd.get("pages") or []
        ol = "/".join(
            str(u.get("heading") or u.get("title") or u.get("id", ""))[:24]
            for u in units[:8]
        )
        existing.append(
            {
                "id": cid,
                "title": str(cd.get("title", "")),
                "outline": ol,
            }
        )
    if not existing:
        return {"placements": [], "unplaceable": [], "note": "没有待归位的课件"}

    outlines_lines = ""
    for topic, d in outlines.items():
        outlines_lines += f"## 大纲《{topic}》(domain:{d.get('domain', '')})\n"
        for c in d["courses"]:
            outlines_lines += (
                f"- [{c.get('id')}] {c.get('title')} | goal:{str(c.get('goal', ''))[:70]}\n"
            )
    courses_lines = "\n".join(
        f"- {e['id']} | {e['title']} | 大纲:{e['outline']}" for e in existing
    )

    client = get_llm_client().with_options(timeout=300.0)
    resp = client.messages.create(
        model=settings.llm_model,
        max_tokens=8192,  # 思考模型:思考块也吃预算,小值会零文本(实测)
        messages=[
            {
                "role": "user",
                "content": MATCH_PROMPT.format(
                    outlines=outlines_lines, courses=courses_lines
                ),
            }
        ],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    raw = json.loads(text)

    placements: list[dict[str, str]] = []
    unplaceable: list[dict[str, str]] = []
    used_files: set[str] = set()
    refs_by_outline: dict[str, dict[str, list[str]]] = {}
    for m in raw.get("placements", []):
        cid = str(m.get("course_id", ""))
        topic = str(m.get("outline_topic", ""))
        oid = str(m.get("outline_course_id", ""))
        if cid not in existing_ids or cid in used_files:
            continue
        d = outlines.get(topic)
        if d is None:
            continue
        target = next((c for c in d["courses"] if str(c.get("id")) == oid), None)
        if target is None:
            continue
        used_files.add(cid)
        refs_by_outline.setdefault(topic, {}).setdefault(oid, []).append(cid)
        placements.append(
            {
                "course_id": cid,
                "outline_topic": topic,
                "outline_course_id": oid,
                "reason": str(m.get("reason", ""))[:80],
            }
        )
    for m in raw.get("unplaceable", []):
        cid = str(m.get("course_id", ""))
        if cid in existing_ids and cid not in used_files:
            unplaceable.append({"course_id": cid, "reason": str(m.get("reason", ""))[:80]})
            used_files.add(cid)

    skipped: list[dict[str, str]] = []
    for topic, by_course in refs_by_outline.items():
        d = outlines[topic]
        for c in d["courses"]:
            refs = by_course.get(str(c.get("id")), [])
            if refs:
                c["course_refs"] = refs
                c["course_ref"] = refs[0]
        errs = validate_framework(d)
        if errs:
            # 逐大纲把关:一本不过不连坐其他本(legacy 大纲可能超新大纲的课数闸)
            skipped.append({"outline": topic, "reason": ";".join(errs[:2])})
            continue
        _outline_path(topic).write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    note_parts = []
    if not placements:
        note_parts.append("没有产生归位")
    if skipped:
        note_parts.append("跳过:" + ";".join(f"《{s['outline']}》{s['reason']}" for s in skipped))
    return {
        "placements": placements,
        "unplaceable": unplaceable,
        "skipped": skipped,
        "note": ";".join(note_parts),
    }
