"""学习进度(Runtime 层)—— 课件「学完」的服务端判定。

为什么进 SQLite 而不是只信 localStorage:完成判定是写回闸门的一环,
CLI/网页/未来自动建议都要同一真相;浏览器数据太易失。
判定(2026-08-24 对齐):进度覆盖到最后一页(done,由播放引擎自然停止时上报)
+ 该课所有检查点至少 pass 过一次(grade 轨迹,现成数据)。
"""

from __future__ import annotations

import sqlite3
import time

from app.core.config import settings
from app.core.trace import read_traces
from app.schemas.csl import Course
from app.schemas.learning import CompletionState

_DB = settings.data_dir / "classroom.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS course_progress (
    course_id TEXT PRIMARY KEY,
    done      INTEGER NOT NULL DEFAULT 0,  -- 播放已自然走到最后一页末
    done_at   TEXT
);
"""


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB)
    c.executescript(_SCHEMA)
    return c


def mark_done(course_id: str) -> None:
    """播放引擎到达课程自然终点时上报(幂等)。"""
    with _conn() as c:
        c.execute(
            "INSERT INTO course_progress(course_id, done, done_at) VALUES(?,1,?)"
            " ON CONFLICT(course_id) DO UPDATE SET done=1, done_at=excluded.done_at",
            (course_id, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )


def completion(course_id: str) -> CompletionState:
    """完成态:done + 检查点全过 → ready(写回闸门)。"""
    p = settings.courses_dir / f"{course_id}.csl.json"
    try:
        course = Course.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 课件不存在/损坏 → 一律未就绪
        return CompletionState(done=False, checkpoints_total=0, checkpoints_passed=0, ready=False)

    cp_ids = [pg.id for pg in course.pages if pg.checkpoint is not None]
    passed = {
        g.get("page_id")
        for g in read_traces("grade.jsonl", limit=500)
        if g.get("course_id") == course_id and g.get("verdict") == "pass"
    }
    n_pass = sum(1 for i in cp_ids if i in passed)
    with _conn() as c:
        row = c.execute(
            "SELECT done FROM course_progress WHERE course_id=?", (course_id,)
        ).fetchone()
    done = bool(row and row[0])
    return CompletionState(
        done=done,
        checkpoints_total=len(cp_ids),
        checkpoints_passed=n_pass,
        ready=done and n_pass >= len(cp_ids),
    )
