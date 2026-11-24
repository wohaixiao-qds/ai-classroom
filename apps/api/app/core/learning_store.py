"""持久批改结果(Runtime):学习状态不依赖观测日志的窗口、保留期或裁判任务。

首次访问在事务内导入旧 grade.jsonl 全量数据,再以 mastery 历史补回已通过标记。
旧数据没有 source 时按历史 user 处理;明确标为 test 的记录不进入学习状态。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any

from app.core.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_grades (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    ts TEXT NOT NULL,
    result TEXT NOT NULL,
    gaps TEXT                              -- JSON 数组字符串;NULL=该次批改无错因(T2)
);
CREATE INDEX IF NOT EXISTS idx_learning_grades_checkpoint
    ON learning_grades(course_id, page_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_learning_grades_pass
    ON learning_grades(verdict, course_id, page_id);
CREATE TABLE IF NOT EXISTS learning_migrations (name TEXT PRIMARY KEY);
"""


def _insert(c: sqlite3.Connection, rec: dict[str, Any], rid: str) -> None:
    if rec.get("source") == "test" or rec.get("verdict") not in ("pass", "warn", "fail"):
        return
    if not rec.get("course_id") or not rec.get("page_id"):
        return
    # 错因结构化(T2):空错因存 NULL(与历史行同语义),非空列表才落 JSON 文本
    gaps = rec.get("gaps")
    gap_text = (
        json.dumps(gaps, ensure_ascii=False)
        if isinstance(gaps, list) and any(str(g).strip() for g in gaps)
        else None
    )
    c.execute(
        "INSERT OR IGNORE INTO learning_grades"
        " (id, course_id, page_id, verdict, ts, result, gaps)"
        " VALUES(?,?,?,?,?,?,?)",
        (
            rid,
            rec["course_id"],
            rec["page_id"],
            rec["verdict"],
            rec.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            json.dumps(rec, ensure_ascii=False),
            gap_text,
        ),
    )


def _conn() -> sqlite3.Connection:
    db = settings.data_dir / "classroom.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    # 并发首问只允许一人导入;标记和数据同事务提交,崩溃可重试。
    try:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute(
            "SELECT 1 FROM learning_migrations WHERE name='grade-runtime-v1'"
        ).fetchone():
            path = settings.traces_dir / "grade.jsonl"
            if path.exists():
                with path.open(encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(rec, dict):
                            rid = hashlib.sha256(f"{i}:{line}".encode()).hexdigest()
                            _insert(c, rec, str(rec.get("run_id") or f"legacy-{rid}"))
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoint_mastery'").fetchone():
                for row in c.execute("SELECT * FROM checkpoint_mastery").fetchall():
                    try:
                        history = json.loads(row["history"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(history, list):
                        continue
                    passes = [
                        h for h in history if isinstance(h, dict) and h.get("verdict") == "pass"
                    ]
                    has_pass = c.execute(
                        "SELECT 1 FROM learning_grades WHERE course_id=? AND page_id=?"
                        " AND verdict='pass' LIMIT 1",
                        (row["course_id"], row["page_id"]),
                    ).fetchone()
                    if passes and not has_pass:
                        _insert(
                            c,
                            {
                                "course_id": row["course_id"],
                                "page_id": row["page_id"],
                                "verdict": "pass",
                                "ts": passes[-1].get("ts", row["updated_at"]),
                                "recovered_from": "mastery",
                                "comment": "历史通过标记(无原始答案)",
                            },
                            f"mastery-{row['course_id']}-{row['page_id']}",
                        )
            c.execute("INSERT INTO learning_migrations VALUES('grade-runtime-v1')")
        # 错因结构化(T2):旧库增量加 gaps 列;新库建表已含,ALTER 容错跳过
        if not c.execute(
            "SELECT 1 FROM learning_migrations WHERE name='grade-gaps-v1'"
        ).fetchone():
            cols = {r["name"] for r in c.execute("PRAGMA table_info(learning_grades)").fetchall()}
            if "gaps" not in cols:
                c.execute("ALTER TABLE learning_grades ADD COLUMN gaps TEXT")
            c.execute("INSERT INTO learning_migrations VALUES('grade-gaps-v1')")
        c.commit()
    except BaseException:
        c.rollback()
        c.close()
        raise
    return c


def record_result(
    course_id: str,
    page_id: str,
    answer: str,
    result: dict[str, Any],
    *,
    source: str = "user",
    run_id: str | None = None,
) -> None:
    if source == "test":
        return
    with _conn() as c:
        _insert(
            c,
            {
                **result,
                "course_id": course_id,
                "page_id": page_id,
                "answer": answer,
                "source": source,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            run_id or uuid.uuid4().hex,
        )


def passed_checkpoints() -> dict[str, set[str]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT course_id, page_id FROM learning_grades WHERE verdict='pass'"
        ).fetchall()
    out: dict[str, set[str]] = {}
    for row in rows:
        out.setdefault(row["course_id"], set()).add(row["page_id"])
    return out


def last_result(
    course_id: str,
    page_id: str | None = None,
    *,
    passed: bool = False,
) -> dict[str, Any]:
    sql = "SELECT result FROM learning_grades WHERE course_id=?"
    params = [course_id]
    if page_id is not None:
        sql += " AND page_id=?"
        params.append(page_id)
    if passed:
        sql += " AND verdict='pass'"
    with _conn() as c:
        row = c.execute(sql + " ORDER BY ts DESC, rowid DESC LIMIT 1", params).fetchone()
    return json.loads(row[0]) if row else {}


def latest_gaps(course_id: str, page_id: str) -> list[str]:
    """该检查点最近一次「带错因」批改的 gaps(T2:复习卡「上次漏了」/答疑对症引导)。

    语义=最新非空:先错后过时仍取错的那次(历史缺口值得在复习时点名);
    旧数据列值 NULL / 空数组 / 坏 JSON 一律视为无错因,返回空列表。
    """
    with _conn() as c:
        row = c.execute(
            "SELECT gaps FROM learning_grades"
            " WHERE course_id=? AND page_id=? AND gaps IS NOT NULL AND gaps != '[]'"
            " ORDER BY ts DESC, rowid DESC LIMIT 1",
            (course_id, page_id),
        ).fetchone()
    if row is None or not row["gaps"]:
        return []
    try:
        parsed = json.loads(row["gaps"])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(g) for g in parsed if str(g).strip()]


def grade_history(course_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """笔记蒸馏使用 Runtime 结果,按课程取最近尝试,不会被其他课程挤出。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT result FROM learning_grades WHERE course_id=?"
            " ORDER BY ts DESC, rowid DESC LIMIT ?",
            (course_id, limit),
        ).fetchall()
    return [json.loads(r[0]) for r in rows]
