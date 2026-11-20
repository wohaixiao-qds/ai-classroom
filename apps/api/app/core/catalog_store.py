"""课表衍生候选池(Runtime 层)—— 记录用户在课表上的动作,SQLite 单文件。

与 memory 同源(共用 classroom.db),各自建表互不干扰。存「意图」而非执行:
确认候选 / 请求备课 / 请求调研 —— P2/P3 未建时先把念头接住(见 P1.5 §五)。
绝不写进只读 vault(边界铁律 5)。
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from app.core.config import settings

_DB = settings.data_dir / "classroom.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,   -- confirm_spark / dismiss_spark / request_prep / request_research
    target      TEXT NOT NULL,   -- spark.key / note.path / todo.title
    label       TEXT,
    status      TEXT NOT NULL,   -- confirmed / dismissed / queued
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_actions_kind ON catalog_actions(kind, target);
"""

# 动作 → 落库状态(kind 已由路由层的枚举校验兜住)
_STATUS = {
    "confirm_spark": "confirmed",
    "dismiss_spark": "dismissed",
    "request_prep": "queued",
    "request_research": "queued",
    "outline_prep": "queued",  # P7·M2:大纲按课点单备课,target = "主题::课名"
}


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    try:  # 迁移:老表补 detail 列(记录产出课件 id / 失败原因)
        c.execute("ALTER TABLE catalog_actions ADD COLUMN detail TEXT")
    except sqlite3.OperationalError:
        pass  # 已有该列
    return c


def record_action(kind: str, target: str, label: str | None = None) -> dict[str, Any]:
    """追加一条动作,返回其派生状态。"""
    status = _STATUS[kind]
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if kind in ("request_prep", "request_research", "outline_prep"):
            active = c.execute(
                "SELECT * FROM catalog_actions WHERE kind=? AND target=?"
                " AND status IN ('queued','running') ORDER BY id DESC LIMIT 1", (kind, target),
            ).fetchone()
            if active:
                return {**dict(active), "created": False}
        cursor = c.execute(
            "INSERT INTO catalog_actions(kind, target, label, status, created_at)"
            " VALUES(?,?,?,?,?)",
            (kind, target, label, status, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
    return {"id": cursor.lastrowid, "kind": kind, "target": target,
            "status": status, "created": True}


def set_status(target: str, status: str, detail: str | None = None,
               *, action_id: int | None = None) -> None:
    """更新该 target 最新一条动作的状态(M5 后台执行器回写:running/done/failed)。"""
    with _conn() as c:
        row = c.execute(
            "SELECT id,status FROM catalog_actions WHERE target=? ORDER BY id DESC LIMIT 1",
            (target,),
        ).fetchone() if action_id is None else c.execute(
            "SELECT id,status FROM catalog_actions WHERE id=? AND target=?", (action_id, target)
        ).fetchone()
        if row:
            if row["status"] == "cancelled" and status != "cancelled":
                return
            c.execute(
                "UPDATE catalog_actions SET status=?, detail=? WHERE id=?",
                (status, detail, row["id"]),
            )


def latest_job(kind: str, target: str) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM catalog_actions WHERE kind=? AND target=? ORDER BY id DESC LIMIT 1",
            (kind, target),
        ).fetchone()
    return dict(row) if row else None


def action_index() -> dict[str, Any]:
    """汇总当前动作状态,供 catalog 组装时给各泳道打标。

    spark 的 confirm/dismiss 可来回切,按插入顺序后者覆盖前者;
    备课/调研只看是否请求过(有 = queued),status_of 另给执行态(running/done/failed)。
    """
    confirmed: set[str] = set()
    dismissed: set[str] = set()
    prep: set[str] = set()
    research: set[str] = set()
    status_of: dict[str, str] = {}
    with _conn() as c:
        rows = c.execute("SELECT kind, target, status FROM catalog_actions ORDER BY id").fetchall()
    for r in rows:
        kind, target = r["kind"], r["target"]
        if kind == "confirm_spark":
            dismissed.discard(target)
            confirmed.add(target)
        elif kind == "dismiss_spark":
            confirmed.discard(target)
            dismissed.add(target)
        elif kind == "request_prep":
            prep.add(target)
            status_of[target] = r["status"]
        elif kind == "request_research":
            research.add(target)
            status_of[target] = r["status"]
    return {
        "confirmed": confirmed,
        "dismissed": dismissed,
        "prep": prep,
        "research": research,
        "status_of": status_of,
    }
