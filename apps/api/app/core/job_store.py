"""任务跨重试的产物绑定。执行尝试用 action id,材料与课件用稳定 binding id。"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from app.core.catalog_store import _conn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_bindings (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    course_id TEXT NOT NULL UNIQUE,
    material_json TEXT NOT NULL,
    material_hash TEXT NOT NULL,
    plan_hash TEXT,
    UNIQUE(kind, target)
);
"""


def material_hash(material: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def get_binding(kind: str, target: str) -> dict[str, Any] | None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        row = c.execute("SELECT * FROM job_bindings WHERE kind=? AND target=?",
                        (kind, target)).fetchone()
    return dict(row) if row else None


def bind_material(kind: str, target: str, material: dict[str, Any],
                  *, legacy_course_id: str | None = None) -> dict[str, Any]:
    """首次保留原料快照并预留课件 id;重试输入变动必须显式处理。"""
    fingerprint = material_hash(material)
    with _conn() as c:
        c.executescript(_SCHEMA)
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM job_bindings WHERE kind=? AND target=?",
                        (kind, target)).fetchone()
        if row:
            if row["material_hash"] != fingerprint:
                raise ValueError("备课材料已变化,拒绝沿用旧规划续写;原课件保留,请先审阅材料差异")
            return dict(row)
        binding_id = uuid.uuid4().hex
        course_id = legacy_course_id or f"course-{binding_id[:16]}"
        c.execute("INSERT INTO job_bindings"
                  " (id,kind,target,course_id,material_json,material_hash) VALUES(?,?,?,?,?,?)",
                  (binding_id, kind, target, course_id,
                   json.dumps(material, ensure_ascii=False), fingerprint))
        row = c.execute("SELECT * FROM job_bindings WHERE id=?", (binding_id,)).fetchone()
    return dict(row)


def record_plan(binding_id: str, path: Path) -> None:
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    with _conn() as c:
        c.execute("UPDATE job_bindings SET plan_hash=? WHERE id=?", (fingerprint, binding_id))


def check_plan(binding: dict[str, Any], path: Path) -> None:
    expected = binding.get("plan_hash")
    if expected and (
        not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected
    ):
        raise ValueError("恢复规划已变化或丢失,拒绝继续写入;原课件保留,请先审阅规划")


def incomplete_course_ids() -> set[str]:
    """发布时过滤其他任务的恢复产物;绑定本身不等于成功交付。"""
    with _conn() as c:
        c.executescript(_SCHEMA)
        rows = c.execute(
            "SELECT b.course_id FROM job_bindings b LEFT JOIN catalog_actions a ON a.id="
            " (SELECT MAX(id) FROM catalog_actions WHERE kind=b.kind AND target=b.target)"
            " WHERE a.status IS NULL OR a.status!='done'"
        ).fetchall()
    return {str(row["course_id"]) for row in rows}


def ensure_active(binding: dict[str, Any]) -> None:
    """取消/新重试之后,旧循环不得继续修改同一产物。CLI 不带执行尝试则跳过。"""
    action_id = binding.get("action_id")
    if action_id is None:
        return
    with _conn() as c:
        latest = c.execute(
            "SELECT id,status FROM catalog_actions WHERE kind=? AND target=?"
            " ORDER BY id DESC LIMIT 1", (binding["kind"], binding["target"]),
        ).fetchone()
    if not latest or latest["id"] != action_id or latest["status"] not in ("queued", "running"):
        raise RuntimeError("任务已取消或已有新的执行尝试,停止写入旧任务产物")
