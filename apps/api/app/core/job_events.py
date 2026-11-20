"""任务实际执行事件。旧任务没有记录时不从日志推断完成节点。"""
from __future__ import annotations

import time
from typing import Any

from app.core.catalog_store import _conn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL, target TEXT NOT NULL, action_id INTEGER NOT NULL,
 stage TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL,
 created_at TEXT NOT NULL, current INTEGER, total INTEGER
);
CREATE INDEX IF NOT EXISTS idx_job_events_task ON job_events(kind,target,id);
"""


def record_event(kind: str, target: str, stage: str, status: str, detail: str,
                 *, action_id: int | None = None, current: int | None = None,
                 total: int | None = None) -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT id,status FROM catalog_actions WHERE kind=? AND target=?"
                        " ORDER BY id DESC LIMIT 1", (kind, target)).fetchone()
        if not row or row["status"] not in ("queued", "running"):
            return
        if action_id is not None and row["id"] != action_id:
            return
        c.execute("INSERT INTO job_events(kind,target,action_id,stage,status,detail,created_at,"
                  "current,total) VALUES(?,?,?,?,?,?,?,?,?)",
                  (kind, target, row["id"], stage, status, detail[:4000],
                   time.strftime("%Y-%m-%dT%H:%M:%S"), current, total))


def events_for(kind: str, target: str, *, after_action: int = 0) -> list[dict[str, Any]]:
    with _conn() as c:
        c.executescript(_SCHEMA)
        rows = c.execute("SELECT id,action_id,stage,status,detail,created_at,current,total"
                         " FROM job_events WHERE kind=? AND target=? AND action_id>?"
                         " ORDER BY id DESC LIMIT 500", (kind, target, after_action)).fetchall()
    return [dict(r) for r in reversed(rows)]
