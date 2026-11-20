"""后台任务执行器(M5):把课表按钮的意图真正跑起来。

子进程隔离(--reload 的 dev server 里 spawn 出去,崩不牵连 API),
日志落 data/logs/,状态回写 catalog_actions(job_runner 负责)。
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.core.catalog_store import latest_job, set_status
from app.core.config import settings


def log_path_for(kind: str, target: str, action_id: int | None = None) -> Path:
    """任务日志路径(单一事实源):routes/jobs.py 的 tail 端点与 start_job 共用,杜绝漂移。"""
    log_dir: Path = settings.data_dir / "logs"
    safe = re.sub(r"[^\w-]+", "-", target)[:40] or "job"
    if action_id is None:
        row = latest_job(kind, target)
        action_id = int(row["id"]) if row else None
    if action_id is None:
        return log_dir / f"{kind}-{safe}.log"  # 旧手动任务兼容
    suffix = hashlib.sha256(target.encode()).hexdigest()[:10]
    return log_dir / f"{kind}-{safe}-{suffix}-{action_id}.log"


def start_job(kind: str, target: str, *, action_id: int | None = None) -> str:
    """派一个后台子进程跑备课/调研,返回日志路径。"""
    row = latest_job(kind, target)
    if action_id is None and row:
        action_id = int(row["id"])
    log_path = log_path_for(kind, target, action_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    set_status(target, "running", action_id=action_id)
    args = [sys.executable, "-u", "-m", "app.job_runner", kind, target]
    if action_id is not None:
        args.append(str(action_id))
    try:
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(  # noqa: S603 固定参数调用自家模块
                # -u:日志实时刷新,不能等到子进程退出才看到阶段消息。
                args,
                cwd=str(settings.courses_dir.parent),  # apps/api/
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        set_status(target, "failed", f"任务进程启动失败: {exc}", action_id=action_id)
        raise
    # PID 登记(取消用):与日志同名不同后缀,单一事实源
    pid_path = log_path.with_suffix(".pid")
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    return str(log_path)


def reconcile_job(kind: str, target: str) -> None:
    """重试入口校正异常退出的旧任务;刚入队未登记 PID 的窗口保留 30 秒。"""
    row = latest_job(kind, target)
    if not row or row["status"] not in ("queued", "running"):
        return
    path = log_path_for(kind, target, int(row["id"])).with_suffix(".pid")
    if path.exists():
        try:
            os.getpgid(int(path.read_text().strip()))
            return
        except ProcessLookupError:
            path.unlink(missing_ok=True)
    elif (datetime.now() - datetime.fromisoformat(row["created_at"])).total_seconds() < 30:
        return
    set_status(target, "failed", "任务进程已中断,再次提交将恢复绑定产物", action_id=int(row["id"]))


def cancel_job(kind: str, target: str) -> dict[str, object]:
    """手动取消:SIGTERM 进程组 → job_runner 保留产物并置 cancelled。

    返回 {cancelled, note};进程已不在(自然结束)时如实说明。"""
    row = latest_job(kind, target)
    if row and row["status"] not in ("queued", "running"):
        return {"cancelled": False, "note": "该执行尝试已结束"}
    action_id = int(row["id"]) if row else None
    pid_path = log_path_for(kind, target, action_id).with_suffix(".pid")
    if not pid_path.exists():
        return {"cancelled": False, "note": "没有该任务的 PID 登记(可能从未启动或已清理)"}
    pid = int(pid_path.read_text(encoding="utf-8").strip())
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)  # start_new_session → 独立进程组
        return {"cancelled": True, "note": f"已向进程组 {pid} 发送 SIGTERM",
                "action_id": action_id}
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return {"cancelled": False, "note": "进程已不在(可能自然结束),已清理 PID 登记"}
