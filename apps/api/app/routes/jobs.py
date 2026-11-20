"""后台任务观测路由(P4 第五轮追加):把备课/调研子进程的处理消息暴露给页面。

任务由 executor.start_job 派子进程跑,stdout/stderr 落 data/logs/*.log——
agent 循环的阶段消息(submit_plan 规划 / init_course 建骨架 / write_section 逐节写 /
validate_csl 终验)与失败原因都在里面。本路由只做只读 tail,不碰 agent 代码。
路径拼装与 executor.log_path_for 同源,杜绝两处漂移。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException

from app.core.catalog_store import set_status
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
