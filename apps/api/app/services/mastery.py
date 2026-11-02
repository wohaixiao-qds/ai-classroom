"""检查点掌握度与间隔复习(Runtime 层)——把「学完」延伸成「会忘、要复习」。

设计:借鉴 DeepTutor mastery/scheduler 的单人裁剪版
(见 docs/参考-同类项目拆解-2026-11.md #10/#11/#12):
- 掌握度 = 最近 5 次批改的加权正确率(pass=1/warn=0.5/fail=0,新权重高),
  低置信封顶:仅 1 次尝试 ≤0.5、2 次 ≤0.8——「一次蒙对不能算过」。
- 复习节奏 = 固定间隔序列 [1,3,7,14,30,60] 天:pass 且掌握度过门(0.9)→ 进位;
  warn/fail → 回到第 0 档(明天再来)。FSRS 全套/题型分轨对单人单课型属过度设计,不搬。
- 进入复习轮的条件:该检查点至少 pass 过一次(没过的属于「还没学会」,不叫复习)。
- 存储:与 progress/catalog_actions 同一 classroom.db 单文件,gitignore。
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any

from app.core.config import settings
from app.schemas.csl import AnyCourse, parse_course
from app.schemas.learning import ReviewDue, ReviewItem

_DB = settings.data_dir / "classroom.db"

INTERVAL_DAYS = [1, 3, 7, 14, 30, 60]
GATE = 0.9  # 掌握度过门才进位;DeepTutor 同款「90% before you advance」
_VERDICT_SCORE = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
_CAPS = {1: 0.5, 2: 0.8}  # 尝试次数 → 掌握度封顶;≥3 次不封顶

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoint_mastery (
    course_id      TEXT NOT NULL,
    page_id        TEXT NOT NULL,
    history        TEXT NOT NULL DEFAULT '[]',  -- [{"ts","verdict"}] 按时间序
    mastery        REAL NOT NULL DEFAULT 0,
    stage          INTEGER NOT NULL DEFAULT 0,  -- INTERVAL_DAYS 档位
    next_review_at TEXT,                          -- NULL=未进复习轮(从未 pass 过)
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (course_id, page_id)
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


def compute_mastery(verdicts: list[str]) -> float:
    """最近 5 次加权正确率 + 低置信封顶(见模块 docstring)。"""
    recent = verdicts[-5:]
    if not recent:
        return 0.0
    weights = [0.5, 0.625, 0.75, 0.875, 1.0][-len(recent) :]
    score = sum(
        _VERDICT_SCORE.get(v, 0.0) * w for v, w in zip(recent, weights, strict=True)
    ) / sum(weights)
    return round(min(score, _CAPS.get(len(verdicts), 1.0)), 3)


def record_grade(course_id: str, page_id: str, verdict: str) -> None:
    """批改后回写:累积历史 → 重算掌握度 → 推进/回退复习档位。幂等无害,可重复调。"""
    with _conn() as c:
        row = c.execute(
            "SELECT history, stage FROM checkpoint_mastery WHERE course_id=? AND page_id=?",
            (course_id, page_id),
        ).fetchone()
        history: list[dict[str, str]] = json.loads(row["history"]) if row else []
        stage = row["stage"] if row else 0
        history.append({"ts": _now(), "verdict": verdict})
        verdicts = [h["verdict"] for h in history]
        mastery = compute_mastery(verdicts)
        if verdict == "pass" and mastery >= GATE:
            stage += 1
        elif verdict != "pass":
            stage = 0  # 记不清/说反了 → 明天从头再来
        days = INTERVAL_DAYS[min(stage, len(INTERVAL_DAYS) - 1)]
        next_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        # 从未 pass 过不进复习轮(还没学会的不叫复习)
        entered = "pass" in verdicts
        c.execute(
            "INSERT INTO checkpoint_mastery"
            " (course_id,page_id,history,mastery,stage,next_review_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(course_id,page_id) DO UPDATE SET history=excluded.history,"
            " mastery=excluded.mastery, stage=excluded.stage,"
            " next_review_at=excluded.next_review_at, updated_at=excluded.updated_at",
            (
                course_id,
                page_id,
                json.dumps(history, ensure_ascii=False),
                mastery,
                stage,
                next_at if entered else None,
                _now(),
            ),
        )


def _load_course(course_id: str) -> AnyCourse | None:
    try:
        return parse_course(
            (settings.courses_dir / f"{course_id}.csl.json").read_text(encoding="utf-8")
        )
    except Exception:  # noqa: BLE001 单个坏课件不拖垮整张复习清单
        return None


def due_reviews() -> ReviewDue:
    """今日该复习的检查点(next_review_at 到期)+ 现役复习卡总数。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT course_id, page_id, mastery, next_review_at FROM checkpoint_mastery"
            " WHERE next_review_at IS NOT NULL"
        ).fetchall()
    now = datetime.now()
    total = len(rows)
    items: list[ReviewItem] = []
    course_cache: dict[str, AnyCourse | None] = {}
    for r in rows:
        due = datetime.strptime(r["next_review_at"], "%Y-%m-%dT%H:%M:%S")
        if due > now:
            continue
        cid = r["course_id"]
        if cid not in course_cache:
            course_cache[cid] = _load_course(cid)
        course = course_cache[cid]
        if course is None:
            continue
        hit = course.quiz_lookup().get(r["page_id"])
        if hit is None:
            continue  # 课件改版删了该检查点 → 该卡作废
        page_no, page_title, question = hit
        items.append(
            ReviewItem(
                course_id=cid,
                course_title=course.title,
                page_id=r["page_id"],
                page_title=page_title,
                page_no=page_no,
                question=question,
                mastery=r["mastery"],
                next_review_at=r["next_review_at"],
                overdue_days=max(0, (now - due).days),
            )
        )
    items.sort(key=lambda x: x.next_review_at)  # 逾期最久的最先
    return ReviewDue(items=items, total=total)


def rotation_stats() -> dict[str, Any]:
    """现役复习卡总数与到期数(学习台红点用,不用拉全量清单)。"""
    with _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM checkpoint_mastery WHERE next_review_at IS NOT NULL"
        ).fetchone()[0]
        due = c.execute(
            "SELECT COUNT(*) FROM checkpoint_mastery"
            " WHERE next_review_at IS NOT NULL AND next_review_at <= ?",
            (_now(),),
        ).fetchone()[0]
    return {"total": total, "due": due}
