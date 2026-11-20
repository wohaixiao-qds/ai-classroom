"""Eval 聚合:统一窗口和来源过滤,严格区分行为、规则与证据审查。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from app.core.trace import EVAL_VERSION, read_traces

_NORM_RE = re.compile(r"[\s，。、？！?!,.:：;；]+")
_STAGES = ("tutor", "grade", "research", "prep")


def norm_q(q: str) -> str:
    """只合并空白/标点差异,不声称识别语义近似。"""
    return _NORM_RE.sub("", q).lower()


def _rows(stage: str, include_test: bool) -> list[dict[str, Any]]:
    rows = read_traces(f"{stage}.jsonl", limit=1000)
    return rows if include_test else [r for r in rows if r.get("source") != "test"]


def _pct(count: int, total: int) -> float | None:
    return round(count * 100 / total, 1) if total else None


def _assessment(r: dict[str, Any]) -> dict[str, Any]:
    ev = r.get("self_eval") or {}
    if ev.get("version") != EVAL_VERSION:
        return {"verdict": "skipped", "skip_reason": "legacy_or_missing"}
    return ev


def summary(include_test: bool = False) -> dict[str, Any]:
    stages = {s: _rows(s, include_test) for s in _STAGES}
    rows = stages["tutor"]
    answers = [r for r in rows if r.get("answer") and r["status"] in ("succeeded", "unknown")]
    assessments = [_assessment(r) for r in answers]
    checked = [
        v
        for v in assessments
        if v.get("verdict") in ("supported", "partial", "unsupported", "uncertain")
    ]
    judged = [v for v in checked if v["verdict"] != "uncertain"]
    refs = [r for r in answers if r.get("citation_valid") is not None]
    grade = [
        r
        for r in stages["grade"]
        if r.get("verdict") in ("pass", "warn", "fail") and r["status"] in ("succeeded", "unknown")
    ]
    return {
        "asks": len(rows),
        "eval_version": EVAL_VERSION,
        "quality": {
            "answers": len(answers),
            "checked": len(checked),
            "coverage_pct": _pct(len(checked), len(answers)),
            "support_rate_pct": _pct(sum(v["verdict"] == "supported" for v in judged), len(judged)),
            "assessment_counts": dict(Counter(v["verdict"] for v in checked)),
            "skip_reasons": dict(
                Counter(
                    v.get("skip_reason", "unknown")
                    for v in assessments
                    if v.get("verdict") == "skipped"
                )
            ),
            "citation_checks": len(refs),
            "valid_citation_pct": _pct(sum(r["citation_valid"] for r in refs), len(refs)),
            "citation_unknown": sum(
                bool(r.get("cited_pages")) and r.get("citation_valid") is None for r in answers
            ),
            "guard_violations": sum(bool(r["guard_violations"]) for r in rows),
            "reteach": sum(bool(r["reteach"]) for r in rows),
            "tool_used": sum(bool(r["tool_calls"]) for r in rows),
            "tool_error": sum(bool(r["tool_error"]) for r in rows),
            "searched": sum(bool(r["searched"]) for r in rows),
            "soft_landed": sum(bool(r["soft_landed"]) for r in rows),
            "truncated": sum(bool(r["truncated"]) for r in rows),
        },
        "cost": {
            "avg_elapsed_s": round(sum(r["elapsed_s"] for r in rows) / len(rows), 1) if rows else 0,
            "in_tokens": sum(r["usage"].get("input_tokens", 0) for r in rows),
            "out_tokens": sum(r["usage"].get("output_tokens", 0) for r in rows),
            "judge_in_tokens": sum(
                (r.get("self_eval") or {}).get("usage", {}).get("input_tokens", 0) for r in rows
            ),
            "judge_out_tokens": sum(
                (r.get("self_eval") or {}).get("usage", {}).get("output_tokens", 0) for r in rows
            ),
            "judge_elapsed_s": round(
                sum((r.get("self_eval") or {}).get("elapsed_s", 0) for r in rows), 1
            ),
            "unknown_usage": sum(not bool(r["usage"]) for r in rows),
        },
        "stages": {
            s: {"total": len(items), "statuses": dict(Counter(r["status"] for r in items))}
            for s, items in stages.items()
        },
        "verdict_counts": dict(Counter(g["verdict"] for g in grade)),
        "tutored_grades": sum(bool(g.get("tutored")) for g in grade),
    }


def traces(limit: int = 50, include_test: bool = False) -> dict[str, Any]:
    return {s: _rows(s, include_test)[:limit] for s in _STAGES}


def _groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str | None, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("question"):
            groups[(r["course_id"], r["page_id"], norm_q(r["question"]))].append(r)
    items = []
    for (cid, pid, _), history in groups.items():
        if len(history) < 2:
            continue
        versions = [r["versions"] for r in history]
        comparable = all(v.get("context_hash") for v in versions) and all(
            all(v.get(k) == versions[0].get(k) for k in ("context_hash", "model", "eval"))
            for v in versions
        )
        items.append(
            {
                "question": history[0]["question"],
                "course_id": cid,
                "page_id": pid,
                "count": len(history),
                "comparable": bool(comparable),
                "history": history,
            }
        )
    return sorted(items, key=lambda x: -x["count"])


def repeats(include_test: bool = False) -> dict[str, Any]:
    items = _groups(_rows("tutor", include_test))
    return {"repeats": items, "count": len(items)}


def gaps(include_test: bool = False) -> dict[str, Any]:
    rows = _rows("tutor", include_test)
    items = [
        {
            "kind": "searched",
            "ts": r["ts"],
            "course_id": r["course_id"],
            "question": r["question"],
            "detail": "调用了搜索,可能是补充或核实;需人工确认缺口",
        }
        for r in rows
        if r["searched"]
    ]
    items += [
        {
            "kind": "repeated",
            "course_id": g["course_id"],
            "question": g["question"],
            "detail": f"同课同节重复 {g['count']} 次,也可能是复习或重试",
        }
        for g in _groups(rows)
    ]
    items += [
        {
            "kind": "checkpoint_fail",
            "ts": g["ts"],
            "course_id": g["course_id"],
            "question": f"检查点未通过: {g['page_id']}",
            "detail": str(g.get("comment", ""))[:100],
        }
        for g in _rows("grade", include_test)
        if g.get("verdict") == "fail"
    ]
    return {"gaps": items, "count": len(items)}
