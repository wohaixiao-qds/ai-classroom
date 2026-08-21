"""Eval 观测接口:读 trace 出指标、轨迹、检查点通过率、衍生候选。

只读 Runtime 落下的轨迹,不参与 Runtime 决策(两层分离,见 P1.5 §六)。
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter

from app.core.trace import read_traces

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])


@router.get("/summary")
def summary() -> dict:
    """指标条 + 检查点通过率。"""
    tutor = read_traces("tutor.jsonl", limit=500)
    grade = read_traces("grade.jsonl", limit=500)

    asks = len(tutor)
    searched = sum(1 for t in tutor if t.get("searched"))
    avg_s = round(sum(t.get("elapsed_s", 0) for t in tutor) / asks, 1) if asks else 0.0
    cache_hits = sum(1 for t in tutor if (t.get("usage") or {}).get("cache_read", 0) > 0)

    # 检查点:按页取最新一次判定
    latest: dict[str, str] = {}
    for g in grade:  # read_traces 已最新在前
        latest.setdefault(g.get("page_id", "?"), g.get("verdict", "?"))
    verdicts = Counter(latest.values())

    return {
        "asks": asks,
        "searched": searched,
        "avg_elapsed_s": avg_s,
        "cache_hit_rounds": cache_hits,
        "checkpoints": [{"page_id": k, "verdict": v} for k, v in latest.items()],
        "verdict_counts": dict(verdicts),
        "grade_total": len(grade),
    }


@router.get("/traces")
def traces(limit: int = 50) -> dict:
    """问答轨迹(最新在前)。"""
    return {"tutor": read_traces("tutor.jsonl", limit), "grade": read_traces("grade.jsonl", limit)}


@router.get("/gaps")
def gaps() -> dict:
    """衍生候选:课件答不了才联网 → 触发过 web_search 的问题即课件未覆盖点。"""
    items = [
        {
            "ts": t.get("ts"),
            "question": t.get("question"),
            "course_id": t.get("course_id"),
            "page_id": t.get("page_id"),
            "queries": [
                (c.get("args") or {}).get("query")
                for c in t.get("tool_calls", [])
                if c.get("name") == "web_search"
            ],
        }
        for t in read_traces("tutor.jsonl", limit=500)
        if t.get("searched")
    ]
    return {"gaps": items, "count": len(items)}
