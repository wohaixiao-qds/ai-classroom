"""原文快照→摘录→原料→课件块的确定性溯源,不把文字命中解释为事实正确。

完整抓取正文只保留在本地 material JSON;发布课件只带摘录、邻近上下文和指纹。
旧材料可继续使用,缺原文时保持 missing/unreviewed,不补造验证结果。
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.schemas.csl import EvidenceItem


def normalized_body(text: str) -> str:
    """fetch_page 的 [标题 | URL] 只标识出处,不属于支持结论的正文。"""
    # Only remove a standalone metadata line. Some extractors return a single
    # long line; using `[^\n]*` there can consume the entire page up to a later
    # Markdown link's closing bracket and falsely invalidate real quotations.
    first_line, separator, remainder = text.partition("\n")
    if separator and re.fullmatch(r"\[[^\n]*\|\s*https?://[^\n]*\]\s*", first_line):
        text = remainder
    # Markdown emphasis is extractor formatting, not semantic page text. The
    # model may omit it while still quoting a contiguous passage verbatim.
    text = re.sub(r"(?<!\\)(\*{1,3})(?=\S)(.+?)(?<=\S)\1", r"\2", text)
    return " ".join(text.split())


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_error(text: str) -> str | None:
    """识别工具错误与常见拦截页;未命中不保证页面完整或来源权威。"""
    body = normalized_body(text)
    if not body or body.startswith(("(抓取失败", "(提取失败", "(搜索失败", "(工具执行出错")):
        return "抓取未返回可用正文"
    if len(body) < 300 and re.search(
        r"access denied|just a moment|verify you are human|captcha|404 not found|403 forbidden",
        body, re.IGNORECASE,
    ):
        return "抓取返回错误页或人机验证页"
    return None


def _points(material: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for gi, group in enumerate(material.get("groups", []), 1):
        if not isinstance(group, dict):
            continue
        for pi, point in enumerate(group.get("points", []), 1):
            if isinstance(point, dict):
                out.append((f"g{gi}p{pi}", point))
    return out


def locate_material(
    material: dict[str, Any], pages: Mapping[str, str], *, _saved_bodies: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """仅用本轮实际返回构建证据,覆盖模型自报的 evidence/快照/审查结果。"""
    result = copy.deepcopy(material)
    sources = {
        s.get("id"): str(s.get("url", ""))
        for s in result.get("sources", []) if isinstance(s, dict)
    }
    snapshots = dict(pages) if _saved_bodies else {
        url: normalized_body(body) for url, body in pages.items() if not fetch_error(body)
    }
    evidence: list[dict[str, Any]] = []
    errors = []
    for eid, point in _points(result):
        sid = point.get("source_id")
        body = snapshots.get(sources.get(sid, ""), "")
        raw_quote = " ".join(str(point.get("quote") or "").split())
        quote = raw_quote if _saved_bodies and raw_quote in body else normalized_body(raw_quote)
        start = body.find(quote) if quote else -1
        if len(quote) < 12:
            errors.append(f"要点 {eid} 缺少足够具体的原文摘录(至少12字符,须逐字引用)")
        elif start < 0:
            errors.append(f"要点 {eid} 的 quote 不在来源[{sid}]实际抓取正文中,不得翻译或改写摘录")
        item = EvidenceItem(
            id=eid, point=str(point.get("text", "")),
            source_id=sid if isinstance(sid, int) and not isinstance(sid, bool) else None,
            quote=quote or None,
        )
        if start >= 0 and len(quote) >= 12:
            end = start + len(quote)
            item = item.model_copy(update={
                "context": body[max(0, start - 350):end + 350],
                "quote_status": "matched", "quote_start": start, "quote_end": end,
                "source_hash": text_hash(body),
            })
        evidence.append(item.model_dump())
    result["evidence_version"] = 1
    result["evidence"] = evidence
    result["source_snapshots"] = {
        url: {"text": body, "sha256": text_hash(body)} for url, body in snapshots.items()
        if url in sources.values()
    }
    return result, errors


def material_evidence(material: dict[str, Any]) -> list[dict[str, Any]]:
    """恢复新材料时重验摘录位置;历史材料只导出待审记录。"""
    if material.get("evidence_version") == 1:
        snapshots = material.get("source_snapshots", {})
        pages = {}
        for url, snapshot in snapshots.items():
            body = snapshot.get("text", "")
            if not isinstance(body, str) or text_hash(body) != snapshot.get("sha256"):
                raise ValueError(f"原文快照指纹不符:{url}")
            pages[url] = body
        # A saved body already has a verified hash. Do not normalize it again:
        # old snapshots may contain Markdown or a second header in the body.
        rebuilt, errors = locate_material(material, pages, _saved_bodies=True)
        if errors:
            raise ValueError("原料证据损坏:" + ";".join(errors[:3]))
        old = {e.get("id"): e for e in material.get("evidence", []) if isinstance(e, dict)}
        for item in rebuilt["evidence"]:
            saved = old.get(item["id"], {})
            # 内容改变后旧语义结论不能沿用。
            if all(saved.get(k) == item.get(k) for k in
                   ("point", "source_id", "quote", "context", "source_hash")):
                for key in ("support", "reviewer", "reason"):
                    if key in saved:
                        item[key] = saved[key]
            try:
                EvidenceItem.model_validate(item)
            except ValidationError as exc:
                raise ValueError("原料证据审查字段无效") from exc
        return list(rebuilt["evidence"])
    return [EvidenceItem(
        id=eid, point=str(p.get("text", "")),
        source_id=p.get("source_id") if type(p.get("source_id")) is int else None,
        quote=str(p["quote"]) if p.get("quote") else None,
        reason="历史材料或笔记未保存抓取正文,摘录和语义均待审",
    ).model_dump() for eid, p in _points(material)]


def block_text(block: dict[str, Any]) -> str:
    """保留实际待审内容,含代码/表格/测验标准,不把原料要点替代正文。"""
    if block.get("type") == "table":
        rows = [" | ".join(map(str, row)) for row in
                [block.get("header", []), *block.get("rows", [])]]
        if block.get("caption"):
            rows.append(str(block["caption"]))
        return "\n".join(rows)
    if block.get("type") == "flashcards":
        return "\n".join(f"{c.get('front', '')}: {c.get('back', '')}"
                         for c in block.get("cards", []))
    return "\n".join(str(block[k]) for k in ("text", "code", "caption", "question", "pass_rule")
                     if block.get(k))


def course_evidence_report(
    course: dict[str, Any], *, check_model_support: bool = True,
) -> dict[str, Any]:
    """供验收/离线审阅共用:未知引用是错误,未关联或未审语义明确保留。"""
    evidence = {e["id"]: e for e in course.get("meta", {}).get("evidence", [])}
    blocks, errors = [], []
    for section in course.get("sections", []):
        for index, block in enumerate(section.get("blocks", []), 1):
            bid = f"{section['id']}:{index}"
            ids = block.get("evidence_ids", [])
            unknown = [eid for eid in ids if eid not in evidence]
            if unknown:
                errors.append(f"{bid} 引用了不存在的证据:{unknown}")
            refs = [evidence[eid] for eid in ids if eid in evidence]
            if check_model_support and any(e.get("support") == "unsupported" for e in refs):
                errors.append(f"{bid} 引用的原料已被标为不受原文支持,请修正或移除该断言")
            blocks.append({
                "id": bid, "section": section.get("heading", ""),
                "text": block_text(block), "evidence_ids": ids, "evidence": refs,
                # 原料审查不等于改写后的课件审查。
                "support": "unreviewed",
                "reason": "正文尚未做语义审查" if refs else "未关联原文证据(练习/类比亦需人工区分)",
            })
    return {"course_id": course.get("id"), "errors": errors, "blocks": blocks,
            "linked_blocks": sum(bool(b["evidence"]) for b in blocks),
            "total_blocks": len(blocks), "semantic_status": "unreviewed"}
