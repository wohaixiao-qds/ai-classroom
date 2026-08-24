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
    soft_landed: bool = False,
    truncated: bool = False,
    source: str = "user",
    self_eval: dict[str, str] | None = None,
) -> None:
    """答疑一轮的轨迹。

    质量信号(防假性完成用):
      cited_pages   引用了课件哪几页(空=未引课件)
      searched      是否联网(也是衍生候选判定信号:课件答不了才联网)
      grounded      有据:引了课件 或 联网查过
      tool_error    工具报错过(仍作答则可疑)
      soft_landed   撞 MAX_TURNS 才收尾(查不到硬答)
      truncated     撞 max_tokens 被截断
      source        user=真实使用 / test=调试脚本(避免测试噪音污染统计)
    """
    cited = cited_pages(answer)
    searched = any(t.get("name") == "web_search" for t in tool_calls)
    _append(
        "tutor.jsonl",
        {
            "source": source,
            "course_id": course_id,
            "page_id": page_id,
            "question": question,
            "answer": answer,
            "answer_len": len(answer),
            "cited_pages": cited,
            "tool_calls": tool_calls,
            "searched": searched,
            "grounded": bool(cited) or searched,
            "tool_error": any(t.get("error") for t in tool_calls),
            "soft_landed": soft_landed,
            "truncated": truncated,
            "turns": max(1, len(tool_calls)),
            "elapsed_s": round(elapsed_s, 1),
            "usage": usage or {},
            "error": error,
            "self_eval": self_eval,  # A6:{verdict,reason} 或 None(未评);见 services/self_eval
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


def trace_research(
    *,
    topic: str,
    material_path: str,
    tool_calls: list[dict[str, Any]],
    ok: bool,
    elapsed_s: float,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """找资料一轮的轨迹(M2a)。"""
    _append(
        "research.jsonl",
        {
            "topic": topic,
            "material_path": material_path,
            "tool_calls": tool_calls,
            "searched": sum(1 for t in tool_calls if t.get("name") == "web_search"),
            "fetched": sum(1 for t in tool_calls if t.get("name") == "fetch_page"),
            "ok": ok,
            "elapsed_s": round(elapsed_s, 1),
            "usage": usage or {},
            "error": error,
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
    # 归一化:A3 之前落的旧记录缺新字段,补默认值,免得前端读 undefined.length 崩
    for r in out:
        r.setdefault("cited_pages", [])
        r.setdefault("tool_calls", [])
        r.setdefault("usage", {})
        r.setdefault("searched", False)
        r.setdefault("course_id", "")
        r.setdefault("page_id", None)
        r.setdefault("source", "user")
        r.setdefault("grounded", bool(r.get("cited_pages")) or r.get("searched", False))
        r.setdefault("tool_error", any(t.get("error") for t in r.get("tool_calls", [])))
        r.setdefault("soft_landed", False)
        r.setdefault("truncated", False)
        r.setdefault("self_eval", None)
    return out[-limit:][::-1]  # 最新在前
