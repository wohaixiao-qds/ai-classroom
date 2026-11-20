"""生成任务查询与人工控制；删除保留墓碑，旧执行不能复活。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.core.catalog_store import _conn, latest_job, record_action
from app.core.config import settings
from app.core.job_events import events_for
from app.core.job_store import get_binding
from app.services.executor import cancel_job, process_alive, reconcile_job, start_job

KINDS = ("request_prep", "request_research", "outline_prep")


def summary(row: dict[str, Any]) -> dict[str, Any]:
    binding = get_binding(row["kind"], row["target"])
    stopping = row["status"] == "cancelled" and process_alive(
        row["kind"], row["target"], int(row["id"])
    )
    return {key: row.get(key) for key in
            ("id", "kind", "target", "label", "status", "detail", "created_at")} | {
        "status": "stopping" if stopping else row["status"],
        "course_id": binding["course_id"] if binding else
        (row.get("detail") if row["status"] == "done" else None),
        "can_resume": not stopping and row["status"] in ("cancelled", "failed", "blocked"),
    }


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM catalog_actions WHERE id IN"
                         " (SELECT MAX(id) FROM catalog_actions WHERE kind IN (?,?,?)"
                         " GROUP BY kind,target) AND status!='deleted' ORDER BY id DESC LIMIT ?",
                         (*KINDS, limit)).fetchall()
    result = []
    for raw in rows:
        row = dict(raw)
        if row["status"] in ("queued", "running"):
            reconcile_job(row["kind"], row["target"])
            row = latest_job(row["kind"], row["target"]) or row
        if row["status"] != "deleted":
            result.append(summary(row))
    return result


def detail_job(kind: str, target: str) -> dict[str, Any]:
    reconcile_job(kind, target)
    row = latest_job(kind, target)
    if not row or row["status"] == "deleted":
        raise LookupError("任务不存在或已删除")
    with _conn() as c:
        deleted = c.execute("SELECT MAX(id) FROM catalog_actions WHERE kind=? AND target=?"
                            " AND status='deleted'", (kind, target)).fetchone()[0] or 0
        attempts = c.execute("SELECT COUNT(*) FROM catalog_actions WHERE kind=? AND target=?"
                             " AND id>?", (kind, target, deleted)).fetchone()[0]
    events = events_for(kind, target, after_action=int(deleted))
    return {"job": summary(row), "events": events, "attempts": attempts,
            "history_recorded": bool(events)}


def resume_job(kind: str, target: str) -> dict[str, Any]:
    reconcile_job(kind, target)
    previous = latest_job(kind, target)
    if not previous or previous["status"] == "deleted":
        raise LookupError("任务不存在或已删除")
    if previous["status"] not in ("cancelled", "failed", "blocked"):
        raise ValueError("只有已停止或中断的任务可以继续")
    # SIGTERM 尚未完成时，不允许第二个进程接管同一产物。
    if process_alive(kind, target, int(previous["id"])):
        raise ValueError("任务正在停止，请稍后继续")
    action = record_action(kind, target, previous.get("label"))
    if action["created"]:
        start_job(kind, target, action_id=int(action["id"]))
    return {"ok": True, "status": "running", "note": "继续已有任务，复用有效检查点",
            "action_id": int(action["id"])}


def delete_job(kind: str, target: str) -> dict[str, Any]:
    row = latest_job(kind, target)
    if not row or row["status"] == "deleted":
        return {"ok": True, "status": "deleted", "note": "任务已删除", "action_id": None}
    if row["status"] in ("queued", "running"):
        cancel_job(kind, target)
    if process_alive(kind, target, int(row["id"])):
        raise ValueError("任务正在停止，请稍后删除；已完成产物已保留")
    # 先终结所有旧尝试，再清理绑定；ensure_active 与事件记录都会拒绝旧进程。
    with _conn() as c:
        c.execute("UPDATE catalog_actions SET status='deleted' WHERE kind=? AND target=?",
                  (kind, target))
    binding = get_binding(kind, target)
    if binding:
        cid = str(binding["course_id"])
        source = settings.courses_dir / f"{cid}.csl.json"
        published = (settings.web_public_courses / f"{cid}.csl.json").exists()
        # 防止同名文件或被人工替换的文件被纳入删除范围。
        if source.exists() and not published:
            course = json.loads(source.read_text(encoding="utf-8"))
            if course.get("meta", {}).get("job_binding_id") == binding["id"]:
                archive = settings.data_dir / "deleted-jobs" / str(row["id"])
                archive.mkdir(parents=True, exist_ok=True)
                paths: list[Path] = [source,
                    settings.data_dir / "research" / f"{cid}.plan.json",
                    settings.data_dir / "publication" / f"{cid}.json",
                    settings.data_dir / "publication" / f"{cid}.checkpoint.json",
                    settings.data_dir / "publication" / f"{cid}.checkpoint.tmp"]
                for path in paths:
                    if path.is_file():
                        shutil.move(str(path), str(archive / path.name))
        with _conn() as c:
            c.execute("DELETE FROM job_bindings WHERE id=?", (binding["id"],))
    return {"ok": True, "status": "deleted",
            "note": "任务已移除，专属未发布草稿已归档；已发布课程与学习记录保留",
            "action_id": int(row["id"])}
