"""对话记忆(Runtime 层) —— SQLite 单文件,标准库 sqlite3,零依赖。

设计要点(见 docs/P1.5执行计划 §六):
- 记忆归 agent(harness),不归 UI:前端只传 session_id,后端自己 load/append
- 与 trace 分层:trace 是 Eval 层(只追加、观测);本模块是 Runtime 层(参与上下文组装)
- 存完整轮次(含工具调用与结果),追问时依据还在——修「跨轮工具上下文丢失」
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings

_DB: Path = settings.data_dir / "classroom.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    course_id   TEXT    NOT NULL,
    page_id     TEXT,
    role        TEXT    NOT NULL,          -- user / assistant
    content     TEXT    NOT NULL,          -- 文本;工具轮为 JSON 字符串
    kind        TEXT    NOT NULL DEFAULT 'text',  -- text / tool_use / tool_result
    ts          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    course_id   TEXT NOT NULL,
    title       TEXT,                      -- 首个问题截断作标题
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_session(course_id: str) -> str:
    """开一轮干净对话(A5 会话管理的基础)。"""
    sid = uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions(id, course_id, title, created_at, updated_at) VALUES(?,?,?,?,?)",
            (sid, course_id, None, _now(), _now()),
        )
    return sid


def ensure_session(session_id: str | None, course_id: str) -> str:
    """没给 session_id 或查不到 → 新建一个。前端首次提问不必先建会话。"""
    if session_id:
        with _conn() as c:
            row = c.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row:
            return session_id
    return new_session(course_id)


def append_turn(
    session_id: str,
    course_id: str,
    role: str,
    content: Any,
    *,
    kind: str = "text",
    page_id: str | None = None,
) -> None:
    """追加一轮。content 非字符串则 JSON 序列化(工具块用)。"""
    payload = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    with _conn() as c:
        c.execute(
            "INSERT INTO turns(session_id, course_id, page_id, role, content, kind, ts)"
            " VALUES(?,?,?,?,?,?,?)",
            (session_id, course_id, page_id, role, payload, kind, _now()),
        )
        c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id))
        # 首轮用户提问作会话标题
        c.execute(
            "UPDATE sessions SET title=? WHERE id=? AND title IS NULL AND ?='user'",
            (payload[:40], session_id, role),
        )


def load_messages(session_id: str, limit_turns: int = 12) -> list[dict]:
    """取最近 limit_turns 条,还原成 Anthropic messages 格式(含工具块)。

    工具块(kind != text)的 content 是 JSON,反序列化回 list/dict——
    这样追问时模型能看到上轮查到的原始资料,而不只是自己的结论。
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, kind FROM turns WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit_turns),
        ).fetchall()
    msgs: list[dict] = []
    for r in reversed(rows):
        content: Any = r["content"]
        if r["kind"] != "text":
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                pass
        msgs.append({"role": r["role"], "content": content})
    return _repair(msgs)


def _repair(msgs: list[dict]) -> list[dict]:
    """修 messages 合法性:Anthropic 要求首条为 user、且 tool_use/tool_result 成对。

    截断可能切断配对(如首条恰是 tool_result),会被 API 拒。这里从前面丢掉
    不完整片段,直到首条是普通 user 文本为止——宁少不错。
    """
    while msgs and not (msgs[0]["role"] == "user" and isinstance(msgs[0]["content"], str)):
        msgs.pop(0)
    return msgs


def list_sessions(course_id: str, limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT s.id, s.title, s.created_at, s.updated_at,"
            " (SELECT COUNT(*) FROM turns t"
            "  WHERE t.session_id=s.id AND t.role='user' AND t.kind='text') AS asks"
            " FROM sessions s WHERE s.course_id=? ORDER BY s.updated_at DESC LIMIT ?",
            (course_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def session_history(session_id: str) -> list[dict]:
    """给前端渲染用:只要文本轮(工具块不展示)。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, ts FROM turns WHERE session_id=? AND kind='text' ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]
