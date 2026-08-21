"""课表衍生候选池(Runtime 层)—— 记录用户在课表上的动作,SQLite 单文件。

与 memory 同源(共用 classroom.db),各自建表互不干扰。存「意图」而非执行:
确认候选 / 请求备课 / 请求调研 —— P2/P3 未建时先把念头接住(见 P1.5 §五)。
绝不写进只读 vault(边界铁律 5)。
"""

from __future__ import annotations

import sqlite3
import time

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
}


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def record_action(kind: str, target: str, label: str | None = None) -> dict[str, str]:
    """追加一条动作,返回其派生状态。"""
    status = _STATUS[kind]
    with _conn() as c:
        c.execute(
            "INSERT INTO catalog_actions(kind, target, label, status, created_at)"
            " VALUES(?,?,?,?,?)",
            (kind, target, label, status, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
    return {"kind": kind, "target": target, "status": status}


def action_index() -> dict[str, set[str]]:
    """汇总当前动作状态,供 catalog 组装时给各泳道打标。

    spark 的 confirm/dismiss 可来回切,按插入顺序后者覆盖前者;
    备课/调研只看是否请求过(有 = queued)。
    """
    confirmed: set[str] = set()
    dismissed: set[str] = set()
    prep: set[str] = set()
    research: set[str] = set()
    with _conn() as c:
        rows = c.execute("SELECT kind, target FROM catalog_actions ORDER BY id").fetchall()
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
        elif kind == "request_research":
            research.add(target)
    return {"confirmed": confirmed, "dismissed": dismissed, "prep": prep, "research": research}
