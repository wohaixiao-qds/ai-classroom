"""Eval 层 · 轨迹落盘(共享 harness 基础设施)。

两条独立轨迹,各自 JSONL(形状不同,不混):
- tutor.jsonl : 答疑问答轨迹
- grade.jsonl : 复述批改轨迹

设计约束(见 docs/P1.5执行计划 §六):trace 属 Eval 层,只追加、供观测/复盘;
Runtime 不反过来读它当记忆(记忆走 SQLite),避免两层搅在一起。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from app.core.config import settings

_CITE_RE = re.compile(r"课件第\s*(\d+)\s*页")


def cited_pages(answer: str) -> list[int]:
    """从回答里提取引用的课件页码(供观测页统计"哪页常被引用")。"""
    return sorted({int(m) for m in _CITE_RE.findall(answer)})


def _append(filename: str, rec: dict[str, Any]) -> None:
    settings.traces_dir.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
    with (settings.traces_dir / filename).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def trace_tutor(
    *,
    course_id: str,
    page_id: str | None,
    question: str,
    answer: str,
    tool_calls: list[dict],
    elapsed_s: float,
    usage: dict | None = None,
    error: str | None = None,
) -> None:
    """答疑一轮的轨迹。searched 字段是衍生候选的判定信号(课件答不了才联网)。"""
    _append(
        "tutor.jsonl",
        {
            "course_id": course_id,
            "page_id": page_id,
            "question": question,
            "answer": answer,
            "answer_len": len(answer),
            "cited_pages": cited_pages(answer),
            "tool_calls": tool_calls,
            "searched": any(t.get("name") == "web_search" for t in tool_calls),
            "turns": max(1, len(tool_calls)),
            "elapsed_s": round(elapsed_s, 1),
            "usage": usage or {},
            "error": error,
        },
    )


def trace_grade(
    *,
    course_id: str,
    page_id: str,
    answer: str,
    verdict: str,
    comment: str,
    elapsed_s: float,
) -> None:
    """复述批改的轨迹(供观测页算检查点通过率)。"""
    _append(
        "grade.jsonl",
        {
            "course_id": course_id,
            "page_id": page_id,
            "answer": answer,
            "answer_len": len(answer),
            "verdict": verdict,
            "comment": comment,
            "elapsed_s": round(elapsed_s, 1),
        },
    )


def read_traces(filename: str, limit: int = 200) -> list[dict]:
    """读最近 limit 条(观测页用)。坏行跳过,不让一行脏数据毁掉整页。"""
    p: Path = settings.traces_dir / filename
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-limit:][::-1]  # 最新在前
