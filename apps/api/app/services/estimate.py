"""成本预估(P5·T3,借鉴 DeepTutor estimate.py):人审闸前告知预计开销。

数据源 = traces 实测(最近 5 次 ok 轮的均值);无历史给保守默认档。
预估是给「等的人」一个心理预期,精度目标 <2× 即可,不追求精确。
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from app.core.trace import read_traces

# 首跑无历史的默认档(分钟 / LLM 调用轮数):宁高勿低,别让人以为卡死
_DEFAULTS: dict[str, dict[str, float]] = {
    "research": {"min": 8.0, "calls": 10, "n": 0},
    "prep": {"min": 15.0, "calls": 14, "n": 0},
}


def _stage_stats(filename: str) -> dict[str, float] | None:
    """最近 5 次 ok 轮的耗时(分钟)与调用轮数均值;无历史返回 None。"""
        # read_traces 最新在前:[:5] 即最近 5 次 ok 轮
    rows = [r for r in read_traces(filename, limit=12) if r.get("ok")][:5]
    if not rows:
        return None
    return {
        "min": round(mean(float(r.get("elapsed_s", 0)) for r in rows) / 60, 1),
        "calls": round(mean(len(r.get("tool_calls", [])) + 1 for r in rows)),
        "n": float(len(rows)),
    }


def estimate_pipeline() -> dict[str, Any]:
    """原料调研 + 备课两阶段的预估(分钟/调用轮数),标注数据来源。"""
    research = _stage_stats("research.jsonl") or _DEFAULTS["research"]
    prep = _stage_stats("prep.jsonl") or _DEFAULTS["prep"]
    return {
        "research": research,
        "prep": prep,
        "total_min": round(research["min"] + prep["min"], 1),
        "source": "最近实测均值" if _stage_stats("prep.jsonl") else "默认档(首跑无历史)",
    }
