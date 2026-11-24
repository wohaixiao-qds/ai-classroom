"""领域大纲路由(P7·M2):查看 / 调整 / 按课点单备课。

大纲实体 = data/research/{slug}.framework.json(P7·M1 的 courses 形态)。
点单备课 = outline_prep 后台任务(原料调研→备课→按大纲钦定先修链→发布)。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.agent.research import validate_framework
from app.core.catalog_store import record_action
from app.core.config import settings
from app.core.job_store import get_binding, incomplete_course_ids
from app.schemas.learning import CumulativePaper
from app.services.executor import reconcile_job, start_job
from app.services.outline_attribution import _load_outline, _outline_path
from app.services.publication import is_review_draft

router = APIRouter(prefix="/api/v1", tags=["outline"])

_KNOWN_COURSE_KEYS = {
    "id", "title", "goal", "why", "scope", "prereqs", "part", "course_ref",
    "course_refs", "origin", "source_ids",
}


def _existing_courses_index(
    topic: str | None = None,
) -> tuple[dict[str, list[str]], dict[str, str], set[str]]:
    """扫描课件目录:课名 → [课件id](同名课多门都保留)、id → 课名、全量 id 集。"""
    by_title: dict[str, list[str]] = {}
    id_title: dict[str, str] = {}
    all_ids: set[str] = set()
    pending = incomplete_course_ids()
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        if p.name.removesuffix(".csl.json") in pending:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 坏课件不挡列表
            continue
        if is_review_draft(d):
            continue
        if not (d.get("sections") or d.get("pages")):
            continue
        meta = d.get("meta") or {}
        if topic is not None and meta.get("job_kind") == "outline_prep" and not str(
            meta.get("job_target", "")
        ).startswith(topic + "::"):
            continue
        cid = str(d.get("id", ""))
        title = str(d.get("title", ""))
        by_title.setdefault(title, []).append(cid)
        id_title[cid] = title
        all_ids.add(cid)
    return by_title, id_title, all_ids


def _outline_linked_ids(topic: str | None = None) -> dict[str, str]:
    """大纲课 id → 已出课件 id(出课时写进 meta.outline_course_id 的精确链)。"""
    out: dict[str, str] = {}
    pending = incomplete_course_ids()
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        if p.name.removesuffix(".csl.json") in pending:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if is_review_draft(d):
                continue
            meta = d.get("meta") or {}
            if topic is not None and meta.get("job_kind") == "outline_prep" and not str(
                meta.get("job_target", "")
            ).startswith(topic + "::"):
                continue
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
    out: list[dict[str, Any]] = []
    for p in sorted((settings.data_dir / "research").glob("*.framework.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(d, dict):
            continue
        topic = str(d.get("topic", p.stem))
        by_title, id_title, all_ids = _existing_courses_index(topic)
        linked = _outline_linked_ids(topic)
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


class OutlineSource(BaseModel):
    id: int
    title: str
    url: HttpUrl
    fetched_at: str
    snapshot_sha256: str
    excerpt: str


class OutlineCourse(BaseModel):
    id: str
    title: str
    goal: str
    why: str | None = None
    scope: str | None = None
    origin: str | None = None
    part: str | None = None
    prereqs: list[str] = Field(default_factory=list)
    source_ids: list[int] = Field(default_factory=list)
    course_ref: str | None = None
    course_refs: list[str] | None = None
    prereq_titles: list[str]
    course_file_id: str | None
    course_file_ids: list[str]
    course_file_titles: list[str]
    prep_status: str | None


class OutlineDetail(BaseModel):
    topic: str
    domain: str
    courses: list[OutlineCourse]
    source_evidence: list[OutlineSource]
    source_status: Literal["recorded", "historical_unrecorded"]


@router.get("/outlines/{topic}", response_model=OutlineDetail)
def get_outline(topic: str) -> dict[str, Any]:
    d = _load_outline(topic)
    titles_by_id = {str(c.get("id")): str(c.get("title")) for c in d["courses"]}
    by_title, id_title, all_ids = _existing_courses_index(topic)
    linked = _outline_linked_ids(topic)
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
        "source_evidence": d.get("source_evidence", []),
        "source_status": "recorded" if d.get("source_evidence") else "historical_unrecorded",
    }


class OutlineEdit(BaseModel):
    courses: list[dict[str, Any]]


@router.put("/outlines/{topic}")
def save_outline(topic: str, body: OutlineEdit) -> dict[str, Any]:
    """审阅调整(调序/删课/改字段)写回;过校验器才落盘。保留服务端生成的来源快照。"""
    d = _load_outline(topic)
    previous = {c["id"]: c for c in d["courses"]}
    courses = []
    for c in body.courses:
        old = previous.get(str(c.get("id")), {})
        updated = {k: c[k] for k in _KNOWN_COURSE_KEYS if k in c and c[k] is not None}
        if c.get("source_ids", old.get("source_ids", [])) != old.get("source_ids", []):
            raise HTTPException(422, "大纲来源编号由调研生成，不能在编辑大纲时修改")
        if "source_ids" in old:
            updated["source_ids"] = old["source_ids"]
        else:
            updated.pop("source_ids", None)
        courses.append(updated)
    d["courses"] = courses
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


@router.get("/books/{topic}/cumulative", response_model=CumulativePaper)
def book_cumulative(topic: str) -> CumulativePaper:
    """书末综合复测组卷(T3):一本书全部课程读完后的邀请状态 + 抽样卷。

    只读端点;答题复用现有 POST /api/v1/grade(course_id + page_id 即卷内定位),
    判过照常进 mastery 间隔轮。与 due_reviews(今日到期队列)是两条独立入口。
    """
    from app.services.cumulative import build_paper

    try:
        return build_paper(topic)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


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
    target = f"{topic}::{req.title}"
    binding = get_binding("outline_prep", target)
    from app.core.catalog_store import latest_job

    previous = latest_job("outline_prep", target)
    if binding and previous and previous["status"] == "done":
        raise HTTPException(409, f"这门课已交付(course: {binding['course_id']})")
    entry = next(c for c in d["courses"] if str(c.get("title")) == req.title)
    # 大纲明确挂接的课件才拦截;全库同名课不构成任务归属证据。
    refs = [*(entry.get("course_refs") or []), entry.get("course_ref")]
    if not binding and any(
        ref and (settings.courses_dir / f"{ref}.csl.json").exists() for ref in refs
    ):
        raise HTTPException(409, "大纲此处已有挂接课件,请先审阅现有内容")
    reconcile_job("outline_prep", target)
    row = record_action("outline_prep", target, req.title)
    log = (start_job("outline_prep", target, action_id=row["id"]) if row["created"] else "")
    return {"queued": True, "target": target, "log": log}
