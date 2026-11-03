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

_KNOWN_COURSE_KEYS = {
    "id", "title", "goal", "why", "prereqs", "part", "course_ref", "course_refs", "origin"
}


def _existing_courses_index() -> tuple[dict[str, list[str]], dict[str, str], set[str]]:
    """扫描课件目录:课名 → [课件id](同名课多门都保留)、id → 课名、全量 id 集。"""
    by_title: dict[str, list[str]] = {}
    id_title: dict[str, str] = {}
    all_ids: set[str] = set()
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 坏课件不挡列表
            continue
        cid = str(d.get("id", ""))
        title = str(d.get("title", ""))
        by_title.setdefault(title, []).append(cid)
        id_title[cid] = title
        all_ids.add(cid)
    return by_title, id_title, all_ids


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


def _course_file_ids(
    c: dict[str, Any],
    by_title: dict[str, list[str]],
    id_title: dict[str, str],
    all_ids: set[str],
    linked: dict[str, str],
) -> list[str]:
    """出课判定(取并集):course_refs 列表 + course_ref + meta.outline_course_id + 课名。
    列表端点的 prepared 计数与详情端点的逐课判定共用,勿两处漂移。"""
    title = str(c.get("title"))
    ref = str(c.get("course_ref", "") or "")
    fallback = next(iter(by_title.get(title) or []), None)
    file_id = ref if ref in all_ids else linked.get(str(c.get("id"))) or fallback
    refs = [r for r in [str(x) for x in (c.get("course_refs") or [])] if r in all_ids]
    if file_id and file_id not in refs:
        refs.insert(0, file_id)
    return refs


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
    by_title, id_title, all_ids = _existing_courses_index()
    linked = _outline_linked_ids()
    out: list[dict[str, Any]] = []
    for p in sorted((settings.data_dir / "research").glob("*.framework.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(d, dict):
            continue
        courses = d.get("courses") or d.get("subtopics") or []
        # 已有课件的课数:chips 上直接亮「已出 N」,不用点开逐个数
        prepared = sum(
            1 for c in courses if _course_file_ids(c, by_title, id_title, all_ids, linked)
        )
        out.append(
            {
                "topic": str(d.get("topic", p.stem)),
                "domain": str(d.get("domain", "")),
                "count": len(courses),
                "prepared": prepared,
            }
        )
    return out


@router.get("/outlines/{topic}")
def get_outline(topic: str) -> dict[str, Any]:
    d = _load_outline(topic)
    titles_by_id = {str(c.get("id")): str(c.get("title")) for c in d["courses"]}
    by_title, id_title, all_ids = _existing_courses_index()
    linked = _outline_linked_ids()
    status = _prep_status(topic, [str(c.get("title")) for c in d["courses"]])
    courses = []
    for c in d["courses"]:
        title = str(c.get("title"))
        refs = _course_file_ids(c, by_title, id_title, all_ids, linked)
        file_id = refs[0] if refs else None
        courses.append(
            {
                **c,
                "prereq_titles": [titles_by_id.get(p, p) for p in c.get("prereqs", [])],
                "course_file_id": file_id,
                "course_file_ids": refs,
                "course_file_titles": [id_title.get(r, r) for r in refs],
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
    # 大纲→vault 目录同步(全自动跟随):调篇/改结构后目录与大纲.md 快照跟走
    from app.services.vault_sync import sync_outline

    sync_outline(d, topic=topic)
    return {"ok": True, "count": len(body.courses)}


class OutlinePrepReq(BaseModel):
    title: str


@router.get("/outline-jobs")
def outline_jobs() -> list[dict[str, Any]]:
    """大纲点单备课的任务动态(最新一条按 target 去重),生成中心「正在造」用。"""
    db = settings.data_dir / "classroom.db"
    if not db.exists():
        return []
    conn: sqlite3.Connection = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT target, label, status, detail, created_at FROM catalog_actions"
            " WHERE kind='outline_prep' ORDER BY id DESC LIMIT 50"
        ).fetchall()
    finally:
        conn.close()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        if r["target"] in seen:
            continue
        seen.add(r["target"])
        out.append(
            {
                "target": r["target"],
                "title": r["label"] or r["target"],
                "status": r["status"],
                "detail": r["detail"],
            }
        )
    return out


@router.post("/outlines/attribute-all")
def attribute_all_courses() -> dict[str, Any]:
    """课件归位(P7):全局把每门已出课件归入最贴合的大纲课。幂等可重跑。"""
    from app.services.outline_attribution import attribute_all

    try:
        return attribute_all()
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/outlines/{topic}/prep")
def prep_course(topic: str, req: OutlinePrepReq) -> dict[str, Any]:
    d = _load_outline(topic)
    if not any(str(c.get("title")) == req.title for c in d["courses"]):
        raise HTTPException(404, f"大纲里没有「{req.title}」")
    by_title, _, _ = _existing_courses_index()
    if req.title in by_title:
        # 骨架课(0 节,取消/失败残留)放行重新点单;有内容的才挡
        skeleton = [
            cid
            for cid in by_title[req.title]
            if not json.loads(
                (settings.courses_dir / f"{cid}.csl.json").read_text(encoding="utf-8")
            ).get("sections")
        ]
        if not skeleton:
            cid0 = by_title[req.title][0]
            raise HTTPException(409, f"这门课已出过(course: {cid0});要重做先删旧课件")
        # 删骨架:点单后 outline_prep 会走续写模式(0 节=全新写)
        for cid in skeleton:
            (settings.courses_dir / f"{cid}.csl.json").unlink(missing_ok=True)
    target = f"{topic}::{req.title}"
    record_action("outline_prep", target, req.title)
    log = start_job("outline_prep", target)
    return {"queued": True, "target": target, "log": log}
