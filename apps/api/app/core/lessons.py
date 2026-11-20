"""经验教训审核闸:模型仅提候选,人工确认后才进入下一轮 system。"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from app.core.config import settings
from app.core.trace import digest


def _legacy_lines() -> list[str]:
    try:
        text = (settings.data_dir / "agent_lessons.md").read_text(encoding="utf-8")
    except OSError:
        return []
    # 兼容旧账本,不改写人的文件。
    import re

    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return [
        s.strip().removeprefix("- ").strip()
        for s in text.splitlines()
        if s.strip() and not s.lstrip().startswith("#")
    ]


def _conn() -> sqlite3.Connection:
    path = settings.data_dir / "classroom.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS agent_lessons (
        id TEXT PRIMARY KEY, text TEXT NOT NULL, status TEXT NOT NULL,
        run_id TEXT, evidence TEXT NOT NULL, created_at TEXT NOT NULL, reviewed_at TEXT
    )""")
    with c:
        for line in _legacy_lines():
            if "[待审]" in line:
                c.execute(
                    "INSERT OR IGNORE INTO agent_lessons VALUES(?,?,'pending',NULL,?,?,NULL)",
                    (
                        "legacy-" + digest(line),
                        line.replace("[待审]", "").strip(),
                        json.dumps({"origin": "legacy"}),
                        time.strftime("%Y-%m-%dT%H:%M:%S"),
                    ),
                )
    return c


def propose_lesson(run_id: str, text: str, evidence: dict[str, Any], *, source: str) -> None:
    if source == "test":
        return
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO agent_lessons VALUES(?,?,'pending',?,?,?,NULL)",
            (
                run_id,
                text,
                run_id,
                json.dumps(evidence, ensure_ascii=False),
                time.strftime("%Y-%m-%dT%H:%M:%S"),
            ),
        )


def list_lessons() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM agent_lessons ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
    return [{**dict(r), "evidence": json.loads(r["evidence"])} for r in rows]


def review_lesson(lesson_id: str, status: str, text: str | None = None) -> bool:
    if status not in ("approved", "rejected"):
        raise ValueError("无效的审核状态")
    with _conn() as c:
        cur = c.execute(
            "UPDATE agent_lessons SET status=?, text=COALESCE(?,text), reviewed_at=? WHERE id=?",
            (status, text, time.strftime("%Y-%m-%dT%H:%M:%S"), lesson_id),
        )
    return cur.rowcount > 0


def approved_lessons() -> str:
    approved = [r["text"] for r in list_lessons() if r["status"] == "approved"]
    # 未带待审标记的旧手写行视为人的既有规则;待审行必须走审核 API。
    manual = [s for s in _legacy_lines() if "[待审]" not in s]
    lines = list(dict.fromkeys([*manual, *approved]))[:20]
    return "\n".join(f"- {line}" for line in lines)[:6000]
