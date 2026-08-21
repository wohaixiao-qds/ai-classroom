"""Eval 观测接口:读 trace 出质量指标、轨迹、同问题历史、衍生候选。

只读 Runtime 落下的轨迹,不参与 Runtime 决策(两层分离,见 P1.5 §六)。
职责边界:本页只管 **agent 质量**;学习进度(学了几课/通过几检查点)归课表页。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from fastapi import APIRouter

from app.core.trace import read_traces

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])

_NORM_RE = re.compile(r"[\s，。、？！?!,.:：;；]+")


def norm_q(q: str) -> str:
    """问题归一化:去空白与标点,让「harness 和 agent是什么关系」与
    「harness和 agent的区别是什么」这类近似问法能归到一组(实测踩过)。"""
    return _NORM_RE.sub("", q).lower()


def _tutor(include_test: bool) -> list[dict]:
    rows = read_traces("tutor.jsonl", limit=1000)
    return rows if include_test else [r for r in rows if r.get("source") != "test"]


@router.get("/summary")
def summary(include_test: bool = False) -> dict:
    """质量指标(防假性完成)+ 成本/性能。include_test=true 才把调试调用算进来。"""
    rows = _tutor(include_test)
    n = len(rows)
    if not n:
        return {"asks": 0, "quality": {}, "cost": {}, "verdict_counts": {}}

    def pct(c: int) -> float:
        return round(c * 100 / n, 1)

    unsourced = [  # 无据作答:没引课件、没联网、还长篇(>200字) → 高度可疑
        r for r in rows if not r.get("grounded") and r.get("answer_len", 0) > 200
    ]
    grade = read_traces("grade.jsonl", limit=500)

    return {
        "asks": n,
        "quality": {
            "grounded_rate": pct(sum(1 for r in rows if r.get("grounded"))),
            "cited_rate": pct(sum(1 for r in rows if r.get("cited_pages"))),
            "searched": sum(1 for r in rows if r.get("searched")),
            "unsourced_long": len(unsourced),
            "tool_error": sum(1 for r in rows if r.get("tool_error")),
            "soft_landed": sum(1 for r in rows if r.get("soft_landed")),
            "truncated": sum(1 for r in rows if r.get("truncated")),
        },
        "cost": {
            "avg_elapsed_s": round(sum(r.get("elapsed_s", 0) for r in rows) / n, 1),
            "slowest_s": max((r.get("elapsed_s", 0) for r in rows), default=0),
            "in_tokens": sum((r.get("usage") or {}).get("input_tokens", 0) for r in rows),
            "out_tokens": sum((r.get("usage") or {}).get("output_tokens", 0) for r in rows),
            "cache_hit_rounds": sum(
                1 for r in rows if (r.get("usage") or {}).get("cache_read", 0) > 0
            ),
        },
        "verdict_counts": dict(Counter(g.get("verdict", "?") for g in grade)),
    }


@router.get("/traces")
def traces(limit: int = 50, include_test: bool = False) -> dict:
    """问答轨迹(最新在前)+ 批改轨迹。"""
    return {
        "tutor": _tutor(include_test)[:limit],
        "grade": read_traces("grade.jsonl", limit),
    }


@router.get("/repeats")
def repeats(include_test: bool = False) -> dict:
    """同问题历史(轻量抓回归):同一问题被问多次 → 并排看答案演变是变好还是变差。

    也是衍生候选信号之一:反复问同一点 = 课件那里讲不清。
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    labels: dict[str, str] = {}
    for r in _tutor(include_test):
        raw = r.get("question", "").strip()
        key = norm_q(raw)
        labels.setdefault(key, raw)  # 展示用原文(取最新一条的写法)
        groups[key].append(
            {
                "ts": r.get("ts"),
                "answer": r.get("answer"),
                "answer_len": r.get("answer_len"),
                "cited_pages": r.get("cited_pages"),
                "grounded": r.get("grounded"),
                "elapsed_s": r.get("elapsed_s"),
            }
        )
    items = [
        {"question": labels[k], "count": len(v), "history": v}  # read_traces 已最新在前
        for k, v in groups.items()
        if len(v) > 1
    ]
    items.sort(key=lambda x: -x["count"])
    return {"repeats": items, "count": len(items)}


@router.get("/gaps")
def gaps(include_test: bool = False) -> dict:
    """衍生候选:三个信号合并——联网过的问题 / 反复问的问题 / 检查点 fail 的页。"""
    rows = _tutor(include_test)

    searched = [
        {
            "kind": "searched",
            "ts": r.get("ts"),
            "question": r.get("question"),
            "page_id": r.get("page_id"),
            "detail": " / ".join(
                str((c.get("args") or {}).get("query"))
                for c in r.get("tool_calls", [])
                if c.get("name") == "web_search"
            ),
        }
        for r in rows
        if r.get("searched")
    ]

    labels: dict[str, str] = {}
    for r in rows:
        labels.setdefault(norm_q(r.get("question", "")), r.get("question", "").strip())
    counts = Counter(norm_q(r.get("question", "")) for r in rows)
    repeated = [
        {"kind": "repeated", "question": labels[k], "detail": f"被问 {c} 次"}
        for k, c in counts.most_common()
        if c > 1
    ]

    failed = [
        {
            "kind": "checkpoint_fail",
            "ts": g.get("ts"),
            "question": f"检查点未通过: {g.get('page_id')}",
            "page_id": g.get("page_id"),
            "detail": g.get("comment", "")[:80],
        }
        for g in read_traces("grade.jsonl", limit=500)
        if g.get("verdict") == "fail"
    ]

    items = searched + repeated + failed
    return {"gaps": items, "count": len(items)}
