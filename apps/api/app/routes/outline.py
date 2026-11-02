"""领域大纲路由(P7·M2):查看 / 调整 / 按课点单备课。

大纲实体 = data/research/{slug}.framework.json(P7·M1 的 courses 形态)。
点单备课 = outline_prep 后台任务(原料调研→备课→按大纲钦定先修链→发布)。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent.research import validate_framework
from app.core.catalog_store import record_action
from app.core.config import settings
from app.services.executor import start_job
from app.services.outline_attribution import _load_outline, _outline_path

router = APIRouter(prefix="/api/v1", tags=["outline"])

_KNOWN_COURSE_KEYS = {"id", "title", "goal", "why", "prereqs", "part", "course_ref", "origin"}


def _existing_course_ids_by_title() -> dict[str, str]:
    """课名 → 已出课件 id(判定「这门大纲课出了没有」)。"""
    out: dict[str, str] = {}
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out[str(d.get("title", ""))] = str(d.get("id", ""))
        except Exception:  # noqa: BLE001 坏课件不挡列表
            continue
    return out


def _outline_linked_ids() -> dict[str, str]:
    """大纲课 id → 已出课件 id(出课时写进 meta.outline_course_id 的精确链)。"""
    out: dict[str, str] = {}
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            oid = str(d.get("meta", {}).get("outline_course_id", "") or "")
            if oid:
                out[oid] = str(d.get("id", ""))
        except Exception:  # noqa: BLE001
            continue
    return out


def _prep_status(topic: str, titles: list[str]) -> dict[str, str]:
    """点单备课的最新状态(catalog_actions,target = "主题::课名")。"""
    out: dict[str, str] = {}
    db = settings.data_dir / "classroom.db"
    if not db.exists():
        return out
    conn: sqlite3.Connection = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        for t in titles:
            row = conn.execute(
                "SELECT status FROM catalog_actions WHERE target=? ORDER BY id DESC LIMIT 1",
                (f"{topic}::{t}",),
            ).fetchone()
            if row:
                out[t] = str(row["status"])
    finally:
        conn.close()
    return out


@router.get("/outlines")
def list_outlines() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted((settings.data_dir / "research").glob("*.framework.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(d, dict):
            continue
        courses = d.get("courses") or d.get("subtopics") or []
        out.append(
            {
                "topic": str(d.get("topic", p.stem)),
                "domain": str(d.get("domain", "")),
                "count": len(courses),
            }
        )
    return out


@router.get("/outlines/{topic}")
def get_outline(topic: str) -> dict[str, Any]:
    d = _load_outline(topic)
    titles_by_id = {str(c.get("id")): str(c.get("title")) for c in d["courses"]}
    by_title = _existing_course_ids_by_title()
    linked = _outline_linked_ids()
    status = _prep_status(topic, [str(c.get("title")) for c in d["courses"]])
    existing_ids = set(by_title.values())
    courses = []
    for c in d["courses"]:
        title = str(c.get("title"))
        # 出课判定三级:course_ref(调研钦定收编) > meta.outline_course_id(点单出课写回) > 课名
        ref = str(c.get("course_ref", "") or "")
        file_id = (
            ref if ref in existing_ids else linked.get(str(c.get("id"))) or by_title.get(title)
        )
        courses.append(
            {
                **c,
                "prereq_titles": [titles_by_id.get(p, p) for p in c.get("prereqs", [])],
                "course_file_id": file_id,
                "prep_status": status.get(title),
            }
        )
    return {
        "topic": str(d.get("topic", topic)),
        "domain": str(d.get("domain", "")),
        "courses": courses,
    }


class OutlineEdit(BaseModel):
    courses: list[dict[str, Any]]


@router.put("/outlines/{topic}")
def save_outline(topic: str, body: OutlineEdit) -> dict[str, Any]:
    """审阅调整(调序/删课/改字段)写回;过校验器才落盘。未知字段丢弃。"""
    d = _load_outline(topic)
    d["courses"] = [{k: c[k] for k in _KNOWN_COURSE_KEYS if k in c} for c in body.courses]
    errs = validate_framework(d)
    if errs:
        raise HTTPException(422, ";".join(errs[:5]))
    _outline_path(topic).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(body.courses)}


class OutlinePrepReq(BaseModel):
    title: str


@router.post("/outlines/{topic}/attribute")
def attribute_courses(topic: str) -> dict[str, Any]:
    """旧课归位(P7·选2):LLM 匹配已出课件↔大纲课,写 course_ref。幂等可重跑。"""
    from app.services.outline_attribution import attribute_existing_courses

    try:
        return attribute_existing_courses(topic)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/outlines/{topic}/prep")
def prep_course(topic: str, req: OutlinePrepReq) -> dict[str, Any]:
    d = _load_outline(topic)
    if not any(str(c.get("title")) == req.title for c in d["courses"]):
        raise HTTPException(404, f"大纲里没有「{req.title}」")
    by_title = _existing_course_ids_by_title()
    if req.title in by_title:
        raise HTTPException(409, f"这门课已出过(course: {by_title[req.title]});要重做先删旧课件")
    target = f"{topic}::{req.title}"
    record_action("outline_prep", target, req.title)
    log = start_job("outline_prep", target)
    return {"queued": True, "target": target, "log": log}
