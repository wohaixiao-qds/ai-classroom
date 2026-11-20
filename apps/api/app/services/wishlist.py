"""待学清单持久化与来源兼容；不会写知识库或在保存时启动任务。"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
import unicodedata
import uuid
from typing import Any

from app.core.catalog_store import _conn
from app.core.config import settings
from app.core.trace import read_traces
from app.schemas.jobs import JobSummary
from app.schemas.wishlist import (
    LearningQuestion,
    WishlistItem,
    WishlistResponse,
    WishlistSource,
    WishlistStartResult,
)
from app.services.catalog import _BOLD_RE, _EXCLUDE_DIRS, _TODO_RE, _area, _norm, _skip
from app.services.executor import start_job
from app.services.job_lifecycle import summary

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wishlist_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('pending','started','removed')),
    created_at TEXT NOT NULL,
    topic TEXT NOT NULL,
    job_kind TEXT,
    job_target TEXT,
    action_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_wishlist_status ON wishlist_items(status,created_at);
CREATE TABLE IF NOT EXISTS wishlist_sources (
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    label TEXT NOT NULL,
    course_id TEXT,
    page_id TEXT,
    run_id TEXT,
    PRIMARY KEY(kind,source_id)
);
CREATE INDEX IF NOT EXISTS idx_wishlist_sources_item ON wishlist_sources(item_id);
CREATE TABLE IF NOT EXISTS learning_questions (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    legacy_key TEXT NOT NULL,
    course_id TEXT,
    page_id TEXT,
    run_id TEXT,
    created_at TEXT,
    detail TEXT,
    status TEXT NOT NULL CHECK(status IN ('candidate','saved','dismissed')),
    wishlist_id TEXT,
    handled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_learning_questions_course
    ON learning_questions(course_id,status);
"""


def _connect() -> sqlite3.Connection:
    c = _conn()
    c.executescript(_SCHEMA)
    return c


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _key(value: str) -> str:
    # 只统一 Unicode、大小写和空白；不去标点、不作语义或跨领域猜测。
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _upsert(
    c: sqlite3.Connection, title: str, scope: str, source: WishlistSource,
    *, restore: bool = False, topic: str | None = None,
) -> str:
    """同来源/同域精确主题幂等；导入不会恢复用户已移出的条目。"""
    existing = c.execute(
        "SELECT item_id FROM wishlist_sources WHERE kind=? AND source_id=?",
        (source.kind, source.id),
    ).fetchone()
    item_id: str
    if existing:
        item_id = existing["item_id"]
    else:
        dedup = scope + ":" + _key(title)
        row = c.execute("SELECT id FROM wishlist_items WHERE dedup_key=?", (dedup,)).fetchone()
        item_id = row["id"] if row else uuid.uuid4().hex
        if not row:
            c.execute(
                "INSERT INTO wishlist_items(id,title,dedup_key,status,created_at,topic)"
                " VALUES(?,?,?,'pending',?,?)", (item_id, title, dedup, _now(), topic or title),
            )
        c.execute(
            "INSERT INTO wishlist_sources"
            "(kind,source_id,item_id,label,course_id,page_id,run_id) VALUES(?,?,?,?,?,?,?)",
            (source.kind, source.id, item_id, source.label, source.course_id,
             source.page_id, source.run_id),
        )
    if restore:
        c.execute("UPDATE wishlist_items SET status='pending' WHERE id=? AND status='removed'",
                  (item_id,))
    return item_id


def _job_row(c: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any] | None:
    if not row["job_kind"] or not row["job_target"]:
        return None
    raw = c.execute(
        "SELECT * FROM catalog_actions WHERE kind=? AND target=? ORDER BY id DESC LIMIT 1",
        (row["job_kind"], row["job_target"]),
    ).fetchone()
    return dict(raw) if raw else None


def _item(item_id: str) -> WishlistItem:
    with _connect() as c:
        row = c.execute("SELECT * FROM wishlist_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise LookupError("待学条目不存在")
        sources = c.execute(
            "SELECT kind,source_id AS id,label,course_id,page_id,run_id"
            " FROM wishlist_sources WHERE item_id=? ORDER BY rowid", (item_id,),
        ).fetchall()
        job = _job_row(c, row)
    return WishlistItem(
        id=row["id"], title=row["title"], status=row["status"], created_at=row["created_at"],
        sources=[WishlistSource(**dict(s)) for s in sources],
        job=JobSummary(**summary(job)) if job else None,
    )


def _link_legacy_job(c: sqlite3.Connection, item_id: str, title: str) -> None:
    """旧待探按标题发起过任务，只补关联；不把历史任务批量变成新待办。"""
    row = c.execute("SELECT job_kind,status FROM wishlist_items WHERE id=?", (item_id,)).fetchone()
    if row["job_kind"]:
        return
    job = c.execute(
        "SELECT * FROM catalog_actions WHERE kind='request_research' AND target=?"
        " ORDER BY id DESC LIMIT 1", (title,),
    ).fetchone()
    if job:
        c.execute(
            "UPDATE wishlist_items SET job_kind=?,job_target=?,action_id=?,"
            " status=CASE WHEN status='removed' THEN status ELSE 'started' END WHERE id=?",
            (job["kind"], job["target"], job["id"], item_id),
        )


def _sync_vault() -> None:
    root = settings.kb_dir
    if not root.is_dir():
        return
    entries: list[tuple[str, str, str, str]] = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not _skip(d) and d not in _EXCLUDE_DIRS)
        for name in sorted(files):
            if not name.endswith(".md") or "待探" not in name:
                continue
            path = root / os.path.relpath(os.path.join(dirpath, name), root)
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            rel = path.relative_to(root).as_posix()
            for line in lines:
                match = _TODO_RE.match(line.strip())
                if not match:
                    continue
                rest = match.group(1)
                bold = _BOLD_RE.search(rest)
                title = (bold.group(1) if bold else
                         re.split(r"[—(（]", rest, maxsplit=1)[0]).strip()
                if title:
                    entries.append((title, rel, _area(path, root), rest))
    title_areas: dict[str, set[str]] = {}
    for title, _rel, area, _rest in entries:
        title_areas.setdefault(_key(title), set()).add(area)
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        for title, rel, area, rest in entries:
            # 来源键不用行号，笔记前面插行不会让已移出条目复活。
            sid = _digest(rel, _key(title))
            item_id = _upsert(
                c, title, "vault:" + area,
                WishlistSource(kind="vault", id=sid, label=f"{rel} · {rest}"),
                topic=f"{area}：{title}" if area else title,
            )
            # 旧任务只存裸标题，跨域同名时无法知道原本属于哪条待探。
            # 同一领域的多个笔记出处仍可安全沿用原任务。
            if len(title_areas[_key(title)]) == 1:
                _link_legacy_job(c, item_id, title)


def _question_source(row: sqlite3.Row) -> WishlistSource:
    return WishlistSource(
        kind="question", id=row["id"], label=row["question"],
        course_id=row["course_id"], page_id=row["page_id"], run_id=row["run_id"],
    )


def _save_question_in(c: sqlite3.Connection, row: sqlite3.Row, *, explicit: bool) -> str:
    course_id = row["course_id"]
    title = row["question"]
    item_id = _upsert(
        c, title, "question:" + (course_id or "unassigned"), _question_source(row),
        restore=explicit, topic=f"{title}（关联课程：{course_id}）" if course_id else title,
    )
    c.execute(
        "UPDATE learning_questions SET status='saved',wishlist_id=?,handled=? WHERE id=?",
        (item_id, int(explicit), row["id"]),
    )
    return item_id


def _sync_questions() -> None:
    traces = read_traces("tutor.jsonl", limit=1000)
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        for trace in reversed(traces):
            question = _text(trace.get("question"))
            if trace.get("source") == "test" or not trace.get("searched") or not question:
                continue
            cid, page = _text(trace.get("course_id")), _text(trace.get("page_id"))
            run_id, ts = _text(trace.get("run_id")), _text(trace.get("ts"))
            identity = run_id or _digest(cid or "", page or "", ts or "", question)
            qid = "trace-" + _digest(identity, cid or "", question)
            calls = trace.get("tool_calls") or []
            details = [str(call["args"]["query"]) for call in calls
                       if isinstance(call, dict) and call.get("name") == "web_search"
                       and isinstance(call.get("args"), dict) and call["args"].get("query")]
            c.execute(
                "INSERT OR IGNORE INTO learning_questions"
                "(id,question,legacy_key,course_id,page_id,run_id,created_at,detail,status)"
                " VALUES(?,?,?,?,?,?,?,?,'candidate')",
                (qid, question, _norm(question), cid, page, run_id, ts,
                 " / ".join(details) or None),
            )
        actions = c.execute(
            "SELECT * FROM catalog_actions WHERE id IN (SELECT MAX(id) FROM catalog_actions"
            " WHERE kind IN ('confirm_spark','dismiss_spark') GROUP BY target) ORDER BY id",
        ).fetchall()
        for action in actions:
            matches = c.execute(
                "SELECT * FROM learning_questions WHERE legacy_key=?", (action["target"],),
            ).fetchall()
            if not matches and action["kind"] == "confirm_spark":
                # 即便旧 Trace 不在最近窗口里，已确认的问题仍保留为无出处历史项。
                qid = "legacy-" + _digest(action["target"])
                c.execute(
                    "INSERT OR IGNORE INTO learning_questions"
                    "(id,question,legacy_key,created_at,status) VALUES(?,?,?,?,'candidate')",
                    (qid, action["label"] or action["target"], action["target"],
                     action["created_at"]),
                )
                matches = c.execute(
                    "SELECT * FROM learning_questions WHERE id=?", (qid,),
                ).fetchall()
            for row in matches:
                if row["handled"]:
                    continue  # 新界面的按源决策不能被旧全局 key 覆盖。
                if action["kind"] == "confirm_spark":
                    _save_question_in(c, row, explicit=False)
                else:
                    c.execute("UPDATE learning_questions SET status='dismissed' WHERE id=?",
                              (row["id"],))


def list_items(status: str = "pending") -> WishlistResponse:
    _sync_vault()
    _sync_questions()
    with _connect() as c:
        ids = c.execute(
            "SELECT id FROM wishlist_items" + (" WHERE status=?" if status != "all" else "")
            + " ORDER BY created_at DESC,rowid DESC", (status,) if status != "all" else (),
        ).fetchall()
        pending = c.execute(
            "SELECT COUNT(*) FROM wishlist_items WHERE status='pending'",
        ).fetchone()[0]
    return WishlistResponse(items=[_item(row["id"]) for row in ids], pending_count=pending)


def save_manual(title: str) -> WishlistItem:
    title = title.strip()
    if not title or len(title) > 500:
        raise ValueError("主题须为1至500个字符")
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        item_id = _upsert(
            c, title, "manual", WishlistSource(kind="manual", id=_key(title), label="手动输入"),
            restore=True,
        )
        _link_legacy_job(c, item_id, title)
    return _item(item_id)


def update_item(item_id: str, status: str) -> WishlistItem:
    if status not in ("pending", "removed"):
        raise ValueError("无效的待学状态")
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute("SELECT id FROM wishlist_items WHERE id=?", (item_id,)).fetchone():
            raise LookupError("待学条目不存在")
        c.execute("UPDATE wishlist_items SET status=? WHERE id=?", (status, item_id))
    return _item(item_id)


def start_item(item_id: str) -> WishlistStartResult:
    created = False
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM wishlist_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise LookupError("待学条目不存在")
        if row["status"] == "removed":
            raise ValueError("请先将条目重新加入待处理")
        target = row["job_target"] or row["topic"]
        job = c.execute(
            "SELECT * FROM catalog_actions WHERE kind='request_research' AND target=?"
            " ORDER BY id DESC LIMIT 1", (target,),
        ).fetchone()
        if job and job["status"] == "deleted":
            if row["status"] != "pending":
                raise ValueError("关联任务已删除，请先将条目重新加入待处理")
            job = None
        if not job:
            cursor = c.execute(
                "INSERT INTO catalog_actions(kind,target,label,status,created_at)"
                " VALUES('request_research',?,?,'queued',?)", (target, row["title"], _now()),
            )
            job = c.execute(
                "SELECT * FROM catalog_actions WHERE id=?", (cursor.lastrowid,),
            ).fetchone()
            created = True
        c.execute(
            "UPDATE wishlist_items SET status='started',job_kind='request_research',"
            "job_target=?,action_id=? WHERE id=?", (target, job["id"], item_id),
        )
        action_id = int(job["id"])
    if created:
        try:
            start_job("request_research", target, action_id=action_id)
        except OSError:
            with _connect() as c:
                # 创建进程失败时保留清单入口，任务区仍能查看失败原因并继续。
                c.execute("UPDATE wishlist_items SET status='pending' WHERE id=? AND action_id=?",
                          (item_id, action_id))
            raise
    item = _item(item_id)
    assert item.job is not None
    note = "已开始生成" if created else (
        "已有失败或停止的任务，请在任务区继续" if item.job.can_resume else "已关联现有任务"
    )
    return WishlistStartResult(item=item, job=item.job, created=created, note=note)


def list_questions(
    course_id: str | None = None, unassigned: bool = False, include_dismissed: bool = False,
) -> list[LearningQuestion]:
    _sync_questions()
    clauses, values = [], []
    if course_id is not None:
        clauses.append("course_id=?")
        values.append(course_id)
    elif unassigned:
        clauses.append("course_id IS NULL")
    if not include_dismissed:
        clauses.append("status!='dismissed'")
    with _connect() as c:
        rows = c.execute(
            "SELECT * FROM learning_questions"
            + (" WHERE " + " AND ".join(clauses) if clauses else "")
            + " ORDER BY created_at DESC,rowid DESC", values,
        ).fetchall()
    return [LearningQuestion(**dict(row)) for row in rows]


def save_question(question_id: str) -> WishlistItem:
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM learning_questions WHERE id=?", (question_id,)).fetchone()
        if not row:
            raise LookupError("延伸问题不存在")
        item_id = _save_question_in(c, row, explicit=True)
    return _item(item_id)


def dismiss_question(question_id: str) -> None:
    with _connect() as c:
        if not c.execute("SELECT id FROM learning_questions WHERE id=?", (question_id,)).fetchone():
            raise LookupError("延伸问题不存在")
        c.execute("UPDATE learning_questions SET status='dismissed',handled=1 WHERE id=?",
                  (question_id,))
