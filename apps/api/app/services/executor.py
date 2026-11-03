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
    subprocess.Popen(  # noqa: S603 固定参数调用自家模块
        # -u 必带:stdout 对文件是块缓冲,不加的话阶段 print 全憋在缓冲区,
        # 页面 tail 到的全空,直到进程退出才一次性落地(实测踩过)
        [sys.executable, "-u", "-m", "app.job_runner", kind, target],
        cwd=str(settings.courses_dir.parent),  # apps/api/
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # 脱离会话:API 重载/退出不杀任务
    )
    return str(log_path)
