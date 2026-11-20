"""共享 Eval 轨迹:先记录执行,再补评价。JSONL 追加事件按 run_id 合并成一次执行。

学习进度不读这里。旧行缺失的状态/版本/证据保持 unknown,不推断为成功或有据。
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
import re
import socket
import threading
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from app.core.config import settings

_CITE_RE = re.compile(r"课件第\s*(\d+)\s*[页节]")
_ACTIVE: ContextVar[TraceRun | None] = ContextVar("trace_run", default=None)
P = ParamSpec("P")
T = TypeVar("T")
EVAL_VERSION = "evidence-v2"


def cited_pages(answer: str) -> list[int]:
    return sorted({int(m) for m in _CITE_RE.findall(answer)})


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


@functools.cache
def _code_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    return digest(
        {
            str(p.relative_to(root)): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*.py"))
        }
    )


def _append(filename: str, rec: dict[str, Any]) -> None:
    settings.traces_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}, ensure_ascii=False)
    # 单次 append write,线程/子进程各写一条完整行。
    with (settings.traces_dir / filename).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


class TraceRun:
    """同一执行的生命周期。终态只写一次,后续裁判只能补 assessment。"""

    def __init__(self, stage: str, **fields: Any) -> None:
        self.stage = stage
        self.id = uuid.uuid4().hex
        self.started = time.perf_counter()
        self.finished = False
        self.fields: dict[str, Any] = {"source": "user", "turns": 0, **fields}
        self.lock = threading.RLock()
        self.versions = {
            "trace": "2",
            "eval": EVAL_VERSION,
            "model": settings.llm_model,
            "code_hash": _code_hash(),
        }
        self._write(
            "started",
            status="running",
            pid=os.getpid(),
            host=socket.gethostname(),
            **self.fields,
            versions=self.versions,
        )

    def _write(self, event: str, **fields: Any) -> None:
        _append(
            f"{self.stage}.jsonl",
            {"run_id": self.id, "stage": self.stage, "event": event, **fields},
        )

    def update(self, **fields: Any) -> None:
        with self.lock:
            if not self.finished:
                self.fields.update(fields)
                self._write("progress", **fields)

    def context(self, **context: Any) -> None:
        """保存实际初始输入(含历史/工具定义),不包含客户端、环境或凭据。"""
        path = settings.data_dir / "eval-context" / f"{self.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(context, ensure_ascii=False, default=str), encoding="utf-8")
        self.versions.update(
            {
                "context_hash": digest(context),
                "prompt_hash": digest(context.get("system") or context.get("prompt")),
                "tools_hash": digest(context.get("tools", [])),
            }
        )
        self.update(context_file=path.name, versions=self.versions)

    def finish(self, status: str, **fields: Any) -> None:
        with self.lock:
            if self.finished:
                return
            self.fields.update(fields)
            self.fields["status"] = status
            self._write(
                "finished",
                **{
                    **self.fields,
                    "status": status,
                    "elapsed_s": round(time.perf_counter() - self.started, 3),
                },
            )
            self.finished = True

    def assess(self, assessment: dict[str, Any]) -> None:
        self._write("assessment", self_eval=assessment)


def current_run() -> TraceRun | None:
    return _ACTIVE.get()


def update_run(**fields: Any) -> None:
    if run := current_run():
        run.update(**fields)


def run_context(**fields: Any) -> None:
    if run := current_run():
        run.context(**fields)


def observed(stage: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """给同步批处理入口补异常/取消终态,保留各自独立循环及原有 trace 字段。"""

    def decorate(fn: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(fn)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            bound = inspect.signature(fn).bind(*args, **kwargs)
            fields = {
                k: v
                for k, v in bound.arguments.items()
                if k in ("course_id", "page_id", "topic", "phase", "source", "tutored")
            }
            run = TraceRun(stage, **fields)
            token = _ACTIVE.set(run)
            try:
                result = fn(*args, **kwargs)
                run.finish(str(run.fields.get("status", "succeeded")))
                return result
            except BaseException as exc:
                cancelled = isinstance(exc, (SystemExit, KeyboardInterrupt))
                status = "cancelled" if cancelled else "failed"
                run.finish(status, error=f"{type(exc).__name__}: {exc}")
                raise
            finally:
                _ACTIVE.reset(token)

        return wrapped

    return decorate


def _record(stage: str, fields: dict[str, Any], run: TraceRun | None = None) -> None:
    status = fields.pop(
        "status", "succeeded" if fields.get("ok", True) and not fields.get("error") else "failed"
    )
    active = run or current_run()
    if run:
        run.finish(status, **fields)
    elif active:
        active.update(status=status, **fields)
    else:
        _append(f"{stage}.jsonl", {"stage": stage, "status": status, **fields})


def trace_tutor(
    *,
    course_id: str,
    page_id: str | None,
    question: str,
    answer: str,
    tool_calls: list[dict[str, Any]],
    elapsed_s: float,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
    soft_landed: bool = False,
    truncated: bool = False,
    source: str = "user",
    self_eval: dict[str, Any] | None = None,
    guard_violations: list[str] | None = None,
    reteach: list[str] | None = None,
    turns: int | None = None,
    status: str = "succeeded",
    run: TraceRun | None = None,
) -> None:
    cited = cited_pages(answer)
    violations = guard_violations or []
    _record(
        "tutor",
        {
            "course_id": course_id,
            "page_id": page_id,
            "question": question,
            "answer": answer,
            "source": source,
            "answer_len": len(answer),
            "cited_pages": cited,
            "tool_calls": tool_calls,
            "tool_used": bool(tool_calls),
            "searched": any(t.get("name") == "web_search" for t in tool_calls),
            # 仅存在性合法;不等于这些章节支撑了回答。未引用=不适用。
            "citation_valid": not violations if cited or re.search(r"\[\d+\]", answer) else None,
            "tool_error": any(t.get("error") for t in tool_calls),
            "soft_landed": soft_landed,
            "truncated": truncated,
            "turns": turns,
            "elapsed_s": elapsed_s,
            "usage": usage or {},
            "error": error,
            "self_eval": self_eval,
            "guard_violations": violations,
            "reteach": reteach or [],
            "status": status,
        },
        run,
    )


def trace_grade(**fields: Any) -> None:
    _record("grade", fields)


def trace_research(**fields: Any) -> None:
    calls = fields.get("tool_calls", [])
    _record(
        "research",
        {
            **fields,
            "searched": sum(t.get("name") == "web_search" for t in calls),
            "fetched": sum(t.get("name") == "fetch_page" for t in calls),
        },
    )


def trace_prep(**fields: Any) -> None:
    _record("prep", fields)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_traces(filename: str, limit: int = 200) -> list[dict[str, Any]]:
    """流式读行、按执行合并。补评不会重复计数或把旧执行移到最新位置。"""
    path = settings.traces_dir / filename
    if not path.exists() or limit <= 0:
        return []
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            key = str(rec.get("run_id") or f"legacy-{i}")
            if key in rows:
                start_ts = rows[key].get("ts")
                rows[key].update(rec)
                rows[key]["ts"] = start_ts
            else:
                rows[key] = rec
    out = list(rows.values())[-limit:][::-1]
    defaults: dict[str, Any] = {
        "cited_pages": [],
        "tool_calls": [],
        "usage": {},
        "course_id": "",
        "page_id": None,
        "source": "user",
        "soft_landed": False,
        "truncated": False,
        "self_eval": None,
        "guard_violations": [],
        "reteach": [],
        "status": "unknown",
        "versions": {},
        "elapsed_s": 0,
        "answer": "",
        "question": "",
        "turns": None,
        "citation_valid": None,
    }
    for r in out:
        for k, default in defaults.items():
            r.setdefault(k, default)
        # 旧 grounded 是行为启发式,不转为证据支撑结论。
        r.pop("grounded", None)
        r.setdefault("searched", any(t.get("name") == "web_search" for t in r["tool_calls"]))
        r.setdefault("tool_error", any(t.get("error") for t in r["tool_calls"]))
        if r["status"] == "running" and r.get("host") == socket.gethostname():
            if not _alive(int(r.get("pid", 0))):
                r["status"] = "interrupted"
                r["error"] = "执行进程已退出,未留下终态"
    return out
