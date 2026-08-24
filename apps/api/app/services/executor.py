"""后台任务执行器(M5):把课表按钮的意图真正跑起来。

子进程隔离(--reload 的 dev server 里 spawn 出去,崩不牵连 API),
日志落 data/logs/,状态回写 catalog_actions(job_runner 负责)。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from app.core.config import settings


def start_job(kind: str, target: str) -> str:
    """派一个后台子进程跑备课/调研,返回日志路径。"""
    log_dir: Path = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w-]+", "-", target)[:40] or "job"
    log_path = log_dir / f"{kind}-{safe}.log"
    log = log_path.open("w", encoding="utf-8")
    subprocess.Popen(  # noqa: S603 固定参数调用自家模块
        [sys.executable, "-m", "app.job_runner", kind, target],
        cwd=str(settings.courses_dir.parent),  # apps/api/
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # 脱离会话:API 重载/退出不杀任务
    )
    return str(log_path)
