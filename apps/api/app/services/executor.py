"""后台任务执行器(M5):把课表按钮的意图真正跑起来。

子进程隔离(--reload 的 dev server 里 spawn 出去,崩不牵连 API),
日志落 data/logs/,状态回写 catalog_actions(job_runner 负责)。
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from app.core.config import settings


def log_path_for(kind: str, target: str) -> Path:
    """任务日志路径(单一事实源):routes/jobs.py 的 tail 端点与 start_job 共用,杜绝漂移。"""
    log_dir: Path = settings.data_dir / "logs"
    safe = re.sub(r"[^\w-]+", "-", target)[:40] or "job"
    return log_dir / f"{kind}-{safe}.log"


def start_job(kind: str, target: str) -> str:
    """派一个后台子进程跑备课/调研,返回日志路径。"""
    log_path = log_path_for(kind, target)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603 固定参数调用自家模块
        # -u 必带:stdout 对文件是块缓冲,不加的话阶段 print 全憋在缓冲区,
        # 页面 tail 到的全空,直到进程退出才一次性落地(实测踩过)
        [sys.executable, "-u", "-m", "app.job_runner", kind, target],
        cwd=str(settings.courses_dir.parent),  # apps/api/
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # 脱离会话:API 重载/退出不杀任务
    )
    # PID 登记(取消用):与日志同名不同后缀,单一事实源
    pid_path = log_path.with_suffix(".pid")
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    return str(log_path)


def cancel_job(kind: str, target: str) -> dict[str, object]:
    """手动取消:SIGTERM 进程组 → job_runner 信号钩子收尾(清骨架/置 cancelled)。

    返回 {cancelled, note};进程已不在(自然结束)时如实说明。"""
    pid_path = log_path_for(kind, target).with_suffix(".pid")
    if not pid_path.exists():
        return {"cancelled": False, "note": "没有该任务的 PID 登记(可能从未启动或已清理)"}
    pid = int(pid_path.read_text(encoding="utf-8").strip())
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)  # start_new_session → 独立进程组
        return {"cancelled": True, "note": f"已向进程组 {os.getpgid(pid)} 发送 SIGTERM"}
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return {"cancelled": False, "note": "进程已不在(可能自然结束),已清理 PID 登记"}
