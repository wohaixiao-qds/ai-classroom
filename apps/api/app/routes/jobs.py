"""后台任务列表、持久事件及停止/继续/删除入口。

路由负责参数和 HTTP 错误映射，生命周期操作委托 service。
保留旧日志 tail 端点，路径与 executor.log_path_for 同源。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.catalog_store import set_status
from app.services import job_lifecycle
from app.services.executor import cancel_job, log_path_for

router = APIRouter(prefix="/api/v1", tags=["jobs"])

Kind = Literal["request_prep", "request_research", "outline_prep"]


@router.get("/jobs/log")
def job_log(kind: Kind, target: str, tail: int = 40) -> dict[str, object]:
    """尾部日志:前端轮询渲染任务实时动态(target=课表意图的 target 原串)。"""
    if not 1 <= tail <= 200:
        raise HTTPException(status_code=422, detail="tail 取值 1~200")
    path = log_path_for(kind, target)
    if not path.exists():
        return {"exists": False, "lines": []}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"exists": True, "lines": text.splitlines()[-tail:]}


@router.post("/jobs/cancel")
def cancel(kind: Kind, target: str) -> dict[str, object]:
    """手动取消后台任务:SIGTERM → job_runner 保留恢复产物并置 cancelled。"""
    r = cancel_job(kind, target)
    if r["cancelled"]:
        # 状态置 cancelled(信号钩子也会置,双保险防钩子前窗口)
        action_id = r.get("action_id")
        set_status(target, "cancelled", str(r.get("note", "手动取消")),
                   action_id=int(action_id) if isinstance(action_id, int) else None)
    return r


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


@router.get("/jobs", response_model=list[JobSummary])
def jobs(limit: int = 100) -> list[dict[str, object]]:
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit 取值 1~200")
    return job_lifecycle.list_jobs(limit)


@router.get("/jobs/detail", response_model=JobDetail)
def job_detail(kind: Kind, target: str) -> dict[str, object]:
    try:
        return job_lifecycle.detail_job(kind, target)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/resume", response_model=JobOperation)
def job_resume(kind: Kind, target: str) -> dict[str, object]:
    try:
        return job_lifecycle.resume_job(kind, target)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/jobs", response_model=JobOperation)
def job_delete(kind: Kind, target: str) -> dict[str, object]:
    try:
        return job_lifecycle.delete_job(kind, target)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
