"""生成任务的共享 HTTP 响应契约。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Kind = Literal["request_prep", "request_research", "outline_prep"]


class JobSummary(BaseModel):
    id: int
    kind: Kind
    target: str
    label: str | None
    status: str
    detail: str | None
    created_at: str
    course_id: str | None
    can_resume: bool


class JobEvent(BaseModel):
    id: int
    action_id: int
    stage: str
    status: str
    detail: str
    created_at: str
    current: int | None
    total: int | None


class JobDetail(BaseModel):
    job: JobSummary
    events: list[JobEvent]
    attempts: int
    history_recorded: bool


class JobOperation(BaseModel):
    ok: bool
    status: str
    note: str
    action_id: int | None
