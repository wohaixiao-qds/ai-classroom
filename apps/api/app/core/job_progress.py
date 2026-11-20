"""后台任务实际进展；CLI 未绑定任务时不制造任务记录。"""

from __future__ import annotations

from contextvars import ContextVar, Token

_JOB: ContextVar[tuple[str, str, int | None] | None] = ContextVar("job_progress", default=None)


def set_job_context(kind: str, target: str, action_id: int | None
                    ) -> Token[tuple[str, str, int | None] | None]:
    return _JOB.set((kind, target, action_id))


def reset_job_context(token: Token[tuple[str, str, int | None] | None]) -> None:
    _JOB.reset(token)


def ensure_job_active() -> None:
    context = _JOB.get()
    if context is None or context[2] is None:
        return
    from app.core.job_store import ensure_active

    kind, target, action_id = context
    ensure_active({"kind": kind, "target": target, "action_id": action_id})


def emit_progress(stage: str, status: str, detail: str, *,
                  current: int | None = None, total: int | None = None) -> None:
    context = _JOB.get()
    if context is None:
        return
    from app.core.job_events import record_event

    kind, target, action_id = context
    record_event(kind, target, stage, status, detail, action_id=action_id,
                 current=current, total=total)
