"""旧课归位(P7·选2):把已出课件归属到新大纲对应的课上,写 course_ref。

一次 LLM 归属匹配:只配「实质相同」(覆盖大纲课核心 60%+),一对一,
拿不准不配——漏配无损,错配有毒。结果过 validate_framework 才落盘。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agent.research import _slug, validate_framework
from app.core.config import settings
from app.core.llm import get_llm_client


def _outline_path(topic: str) -> Path:
    return settings.data_dir / "research" / f"{_slug(topic)}.framework.json"


def _load_outline(topic: str) -> dict[str, Any]:
    p = _outline_path(topic)
    if not p.exists():
        raise ValueError(f"没有「{topic}」的大纲——先开课调研出大纲")
    d = json.loads(p.read_text(encoding="utf-8"))
    if "courses" not in d:
        from app.agent.research import _legacy_to_outline

        d = _legacy_to_outline(d)
    return d


MATCH_PROMPT = """你在做「旧课归位」:把学员已出的课件,归属到新大纲对应的课上。

# 大纲课程(待归属)
{outline_courses}

# 学员已出的课件
{existing_courses}

规则:
- 归入标准:这些课件**合起来**实质覆盖该大纲课的核心(60% 以上);单门覆盖也行
- 每门已出课件只能归入一门大纲课;不属于任何大纲课的课件不要硬塞
- 拿不准就不归——漏归无损,错归有毒
- 主题都不同(如 MCP 课件配 harness 大纲课)绝不归

只输出 JSON(不要其他内容):
{{"matches": [{{"outline_id": "大纲课id", "course_ids": ["课件id", "..."], "reason": "一句话"}}]}}

没有够格的归入就输出 {{"matches": []}}"""


def attribute_existing_courses(topic: str) -> dict[str, Any]:
    """归属匹配并写回 course_ref。返回 {matches, unmatched, note}。"""
    d = _load_outline(topic)
    if not d.get("courses"):
        raise ValueError("大纲为空")
    by_ref: set[str] = {str(c.get("course_ref") or "") for c in d["courses"]}
    by_ref.discard("")

    # 已出课件速览:id | 标题 | 节标题大纲(v2);已被本大纲收编的不再参选
    existing: list[dict[str, str]] = []
    existing_ids: set[str] = set()
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        try:
            cd = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cid = str(cd.get("id", ""))
        existing_ids.add(cid)
        if cid in by_ref:
            continue  # 已归位过的不重复参选
        units = cd.get("sections") or cd.get("pages") or []
        outline = "/".join(
            str(u.get("heading") or u.get("title") or u.get("id", ""))[:24]
            for u in units[:8]
        )
        existing.append({"id": cid, "title": str(cd.get("title", "")), "outline": outline})
    if not existing:
        return {"matches": [], "unmatched": [str(c.get("id")) for c in d["courses"]],
                "note": "没有可归位的课件(全部已归位或无课件)"}

    outline_lines = "\n".join(
        f"- {c.get('id')} | {c.get('title')} | goal:{c.get('goal', '')[:80]}"
        for c in d["courses"]
        if not c.get("course_ref")
    )
    existing_lines = "\n".join(
        f"- {e['id']} | {e['title']} | 大纲:{e['outline']}" for e in existing
    )
    client = get_llm_client().with_options(timeout=180.0)
    resp = client.messages.create(
        model=settings.llm_model,
        max_tokens=8192,  # 思考模型:思考块也吃预算,2048 会被它烧光零文本(实测)
        messages=[
            {
                "role": "user",
                "content": MATCH_PROMPT.format(
                    outline_courses=outline_lines, existing_courses=existing_lines
                ),
            }
        ],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    raw = json.loads(text)
    matches: list[dict[str, Any]] = []

    used_files: set[str] = set()
    outline_ids = {str(c.get("id")) for c in d["courses"]}
    for m in raw.get("matches", []):
        oid = str(m.get("outline_id", ""))
        cids = [str(x) for x in (m.get("course_ids") or [m.get("course_id")] or []) if x]
        if oid not in outline_ids:
            continue  # 幻觉大纲课 id
        cids = [x for x in cids if x in existing_ids and x not in used_files]
        if not cids:
            continue
        target = next((c for c in d["courses"] if str(c.get("id")) == oid), None)
        if target is None or target.get("course_refs"):
            continue  # 已归过的不重复归
        target["course_refs"] = cids
        target["course_ref"] = cids[0]  # 兼容单值消费方
        used_files.update(cids)
        matches.append(
            {
                "outline_id": oid,
                "course_ids": cids,
                "reason": str(m.get("reason", ""))[:80],
            }
        )

    errs = validate_framework(d)
    if errs:
        raise ValueError(f"归位后校验不过,未落盘:{errs[:3]}")
    _outline_path(topic).write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    unmatched = [
        str(c.get("id"))
        for c in d["courses"]
        if not c.get("course_refs") and not c.get("course_ref")
    ]
    return {"matches": matches, "unmatched": unmatched, "note": ""}
