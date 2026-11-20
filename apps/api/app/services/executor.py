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

from app.core.catalog_store import _conn, latest_job, set_status
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
    args = [sys.executable, "-u", "-m", "app.job_runner", kind, target]
    if action_id is not None:
        args.append(str(action_id))
    try:
        # Spawn + PID registration is atomic against stop/delete. A cancelled
        # queued attempt must never start later and recreate discarded files.
        with _conn() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT id,status FROM catalog_actions WHERE kind=? AND target=?"
                " ORDER BY id DESC LIMIT 1", (kind, target),
            ).fetchone()
            if action_id is not None and (
                not current or current["id"] != action_id
                or current["status"] not in ("queued", "running")
            ):
                raise ValueError("任务已停止、删除或被新尝试替代，拒绝启动旧进程")
            with log_path.open("w", encoding="utf-8") as log:
                proc = subprocess.Popen(  # noqa: S603 固定参数调用自家模块
                    args, cwd=str(settings.courses_dir.parent),
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                )
            log_path.with_suffix(".pid").write_text(str(proc.pid), encoding="utf-8")
            if action_id is not None:
                connection.execute("UPDATE catalog_actions SET status='running' WHERE id=?",
                                   (action_id,))
    except OSError as exc:
        set_status(target, "failed", f"任务进程启动失败: {exc}", action_id=action_id)
        raise
    return str(log_path)


def reconcile_job(kind: str, target: str) -> None:
    """重试入口校正异常退出的旧任务;刚入队未登记 PID 的窗口保留 30 秒。"""
    row = latest_job(kind, target)
    if not row or row["status"] not in ("queued", "running"):
        return
    path = log_path_for(kind, target, int(row["id"])).with_suffix(".pid")
    if path.exists():
        if process_alive(kind, target, int(row["id"])):
            return
        path.unlink(missing_ok=True)
    elif (datetime.now() - datetime.fromisoformat(row["created_at"])).total_seconds() < 30:
        return
    set_status(target, "failed", "任务进程已中断,再次提交将恢复绑定产物", action_id=int(row["id"]))


def cancel_job(kind: str, target: str) -> dict[str, object]:
    """手动取消:SIGTERM 进程组 → job_runner 保留产物并置 cancelled。

    返回 {cancelled, note};进程已不在(自然结束)时如实说明。"""
    row = latest_job(kind, target)
    if not row:
        return {"cancelled": False, "note": "任务不存在"}
    if row["status"] not in ("queued", "running"):
        return {"cancelled": False, "note": "该执行尝试已结束"}
    action_id = int(row["id"]) if row else None
    pid_path = log_path_for(kind, target, action_id).with_suffix(".pid")
    if not pid_path.exists():
        set_status(target, "cancelled", "已停止，保留有效产物", action_id=action_id)
        return {"cancelled": True, "note": "已停止，未登记运行进程", "action_id": action_id}
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        set_status(target, "cancelled", "PID 登记无效，已停止任务写入", action_id=action_id)
        return {"cancelled": True, "note": "PID 登记无效，未发送信号", "action_id": action_id}
    if not _owns_process(pid, kind, target, action_id):
        set_status(target, "cancelled", "原任务进程已退出，未向其他进程发送信号",
                   action_id=action_id)
        pid_path.unlink(missing_ok=True)
        return {"cancelled": True, "note": "原任务进程已退出", "action_id": action_id}
    set_status(target, "cancelled", "正在停止，保留有效产物", action_id=action_id)
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)  # start_new_session → 独立进程组
        return {"cancelled": True, "note": f"已向进程组 {pid} 发送 SIGTERM",
                "action_id": action_id}
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return {"cancelled": False, "note": "进程已不在(可能自然结束),已清理 PID 登记"}


def process_alive(kind: str, target: str, action_id: int | None = None) -> bool:
    """只检查本次执行登记的进程；用于停止后继续/删除的互斥。"""
    path = log_path_for(kind, target, action_id).with_suffix(".pid")
    if not path.exists():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        if pid <= 1:
            return False
        os.kill(pid, 0)
        return _owns_process(pid, kind, target, action_id)
    except (ProcessLookupError, ValueError):
        return False


def _owns_process(pid: int, kind: str, target: str, action_id: int | None) -> bool:
    """PID 可被操作系统复用；发信号前核对执行入口和完整任务标识。"""
    if pid <= 1:
        return False
    result = subprocess.run(  # noqa: S603 固定只读系统命令
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
        check=False, timeout=2,
    )
    command = result.stdout.strip()
    expected = f"-m app.job_runner {kind} {target}"
    if action_id is not None:
        expected += f" {action_id}"
    return result.returncode == 0 and command.endswith(expected)
