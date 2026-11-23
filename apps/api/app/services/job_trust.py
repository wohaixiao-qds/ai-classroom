"""只读生成任务的可信依据。程序核验与模型意见分开，不提供可信度分数。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.job_store import get_binding, material_hash
from app.core.trace import digest
from app.services.evidence import material_evidence
from app.services.publication import (
    PublicationBlocked,
    assert_publishable,
    content_hash,
    report_path,
)

JobKind = Literal["request_prep", "request_research", "outline_prep"]


class TrustSource(BaseModel):
    stage: Literal["outline", "material"]
    id: str
    url: str
    title: str
    fetched_at: str | None = None
    sha256: str | None = None
    excerpt: str = ""
    identity_status: Literal["unverified"] = "unverified"


class TrustCheck(BaseModel):
    id: str
    label: str
    status: Literal["passed", "failed", "unknown"]
    provider: Literal["program"] = "program"
    detail: str


class TrustMapping(BaseModel):
    course_id: str
    title: str
    source_ids: list[int] = Field(default_factory=list)
    goal: str = ""
    scope: str = ""


class TrustReviewItem(BaseModel):
    id: str
    verdict: str
    reason: str


class TrustReview(BaseModel):
    stage: Literal["material", "publication"]
    status: str
    reviewer: str
    input_hash: str | None = None
    prompt_hash: str | None = None
    reviewed_at: str | None = None
    items: list[TrustReviewItem] = Field(default_factory=list)


class JobTrustReport(BaseModel):
    kind: JobKind
    target: str
    topic: str
    course_id: str | None = None
    outline_hash: str | None = None
    material_hash: str | None = None
    content_hash: str | None = None
    sources: list[TrustSource] = Field(default_factory=list)
    checks: list[TrustCheck] = Field(default_factory=list)
    mappings: list[TrustMapping] = Field(default_factory=list)
    reviews: list[TrustReview] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    human_review: Literal["not_recorded"] = "not_recorded"
    publication_status: Literal["allowed", "blocked", "unknown"] = "unknown"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _safe_id(value: str) -> bool:
    return bool(value) and Path(value).name == value and value not in (".", "..")


def _web_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def _outline(topic: str) -> dict[str, Any] | None:
    # Reuse the persisted naming convention, never accept a caller supplied path.
    from app.agent.research import _slug

    return _read(settings.data_dir / "research" / f"{_slug(topic)}.framework.json")


def _review(stage: Literal["material", "publication"], review: dict[str, Any],
            status: str, reviewed_at: str | None = None) -> TrustReview:
    return TrustReview(
        stage=stage, status=status, reviewer=str(review.get("reviewer") or "未记录审查者"),
        input_hash=review.get("input_hash"), prompt_hash=review.get("prompt_hash"),
        reviewed_at=reviewed_at,
        items=[TrustReviewItem(id=str(i.get("id", "")), verdict=str(i.get("verdict", "")),
                               reason=str(i.get("reason", "")))
               for i in review.get("items", []) if isinstance(i, dict)],
    )


def _outline_checks(report: JobTrustReport, framework: dict[str, Any]) -> None:
    sources = framework.get("source_evidence") or []
    source_ids = {s.get("id") for s in sources if isinstance(s, dict)}
    courses = [c for c in framework.get("courses", []) if isinstance(c, dict)]
    graph = {str(c.get("id", "")): list(c.get("prereqs") or []) for c in courses}
    remaining = dict(graph)
    invalid = len(graph) != len(courses) or "" in graph
    invalid = invalid or any(p not in graph for ps in graph.values() for p in ps)
    while remaining:
        ready = [cid for cid, ps in remaining.items() if not ps]
        if not ready:
            invalid = True
            break
        remaining = {cid: [p for p in ps if p not in ready]
                     for cid, ps in remaining.items() if cid not in ready}
    report.checks.append(TrustCheck(
        id="outline_structure", label="大纲先修结构", status=(
            "failed" if invalid else "passed" if courses else "unknown"
        ), detail="检查课程 ID、先修悬空与环；不证明教学顺序或内容完整性。",
    ))
    mapped = 0
    for c in courses:
        ids = [sid for sid in c.get("source_ids", []) if type(sid) is int]
        mapped += bool(ids) and all(sid in source_ids for sid in ids)
        report.mappings.append(TrustMapping(
            course_id=str(c.get("id", "")), title=str(c.get("title", "")),
            source_ids=ids, goal=str(c.get("goal") or ""), scope=str(c.get("scope") or ""),
        ))
    report.checks.append(TrustCheck(
        id="outline_source_mapping", label="大纲来源关联记录",
        status="passed" if courses and mapped == len(courses) else "unknown",
        detail=f"{mapped}/{len(courses)} 门课记录了有效来源 ID；关联由模型提出，"
               "尚未验证参考目录覆盖或映射语义，不能据此判断领域完整性。",
    ))
    for s in sources:
        if not isinstance(s, dict):
            continue
        url = str(s.get("url", ""))
        if not _web_url(url):
            continue
        report.sources.append(TrustSource(
            stage="outline", id=str(s.get("id", "")), url=url,
            title=str(s.get("title") or url), fetched_at=s.get("fetched_at"),
            sha256=s.get("snapshot_sha256"), excerpt=str(s.get("excerpt") or ""),
        ))
    report.checks.append(TrustCheck(
        id="outline_fetch_records", label="大纲抓取记录",
        status="passed" if report.sources and all(
            s.fetched_at and s.sha256 for s in report.sources
        ) else "unknown",
        detail="仅核对保存的抓取时间与快照指纹记录；未保存完整正文时无法重新计算指纹。",
    ))


def build_job_trust(kind: JobKind, target: str) -> JobTrustReport:
    topic = target.partition("::")[0] if kind == "outline_prep" else target
    report = JobTrustReport(kind=kind, target=target, topic=topic, limitations=[
        "不提供可信度总分。原文命中证明摘录存在，不证明结论正确。",
        "来源发布主体身份未核实；网址与抓取成功不等于权威认证或独立多方印证。",
        "大纲来源关联由模型提出；参考目录覆盖、零基础适配和领域完整性尚未独立核验。",
        "语义结论由所标注模型提供，可能误判；未记录人工审核。",
    ])
    framework = _outline(topic) if kind != "request_prep" else None
    if framework:
        report.outline_hash = digest(framework)
        _outline_checks(report, framework)
    else:
        report.checks.append(TrustCheck(id="outline_records", label="大纲依据",
                                      status="unknown", detail="未找到本任务的大纲依据记录。"))
    binding = get_binding(kind, target)
    material: dict[str, Any] | None = None
    if binding:
        report.course_id = str(binding["course_id"])
        try:
            material = json.loads(binding["material_json"])
            if not isinstance(material, dict):
                material = None
        except (TypeError, ValueError):
            pass
        intact = material is not None and material_hash(material) == binding["material_hash"]
        report.checks.append(TrustCheck(
            id="material_binding", label="任务材料绑定", status="passed" if intact else "failed",
            detail="核对稳定任务绑定中的材料内容指纹。",
        ))
        if not intact:
            material = None
    if material:
        report.material_hash = material_hash(material)
        _material_checks(report, material)
    else:
        # Research saves its material before semantic review and before a prep
        # binding exists. Show this exact cache, never guess a course by title.
        from app.agent.research import _slug

        title = target.partition("::")[2] if kind == "outline_prep" else ""
        if not title and framework:
            entries = framework.get("courses") or []
            title = str(entries[0].get("title", "")) if entries else ""
        cached = _read(settings.data_dir / "research" /
                       f"{_slug(topic)}.{_slug(title)}.material.json") if title else None
        if not binding and cached:
            report.material_hash = material_hash(cached)
            _material_checks(report, cached)
        else:
            report.checks.append(TrustCheck(
                id="material_records", label="原料原文核验", status="unknown",
                detail="尚无有效绑定材料，不能推定通过。",
            ))
    if report.course_id and _safe_id(report.course_id):
        course = _read(settings.courses_dir / f"{report.course_id}.csl.json")
        if course:
            _publication_checks(report, course)
    return report


def _material_checks(report: JobTrustReport, material: dict[str, Any]) -> None:
    evidence: list[dict[str, Any]] = []
    try:
        evidence = material_evidence(material)
        matched = sum(e.get("quote_status") == "matched" for e in evidence)
        status: Literal["passed", "failed", "unknown"] = (
            "passed" if evidence and matched == len(evidence) else "unknown"
        )
        detail = f"{matched}/{len(evidence)} 条摘录可在指纹一致的保存正文中定位。"
    except (ValueError, TypeError, KeyError, AttributeError):
        status, detail = "failed", "保存正文指纹或摘录定位不一致，材料需要重新核验。"
    report.checks.append(TrustCheck(id="material_quotes", label="原料摘录与快照",
                                  status=status, detail=detail))
    snapshots = material.get("source_snapshots") or {}
    for s in material.get("sources", []):
        if not isinstance(s, dict):
            continue
        url = str(s.get("url", ""))
        if not _web_url(url):
            continue
        snapshot = snapshots.get(url) or {}
        quote = next((str(e.get("quote") or "") for e in evidence
                      if e.get("source_id") == s.get("id")), "")
        report.sources.append(TrustSource(
            stage="material", id=str(s.get("id", "")), url=url,
            title=str(s.get("title") or url), fetched_at=snapshot.get("fetched_at"),
            sha256=snapshot.get("sha256"), excerpt=quote,
        ))
    review = material.get("evidence_review") or {}
    if review:
        claims = [{"id": e["id"], "text": e["point"], "quote": e["quote"],
                   "context": e["context"]} for e in evidence]
        valid = bool(evidence) and review.get("input_hash") == digest(claims)
        items = review.get("items") or []
        complete = (len(items) == len(evidence)
                    and {i.get("id") for i in items} == {e["id"] for e in evidence}
                    and all(i.get("verdict") not in (None, "unreviewed") for i in items))
        state = "stale" if not valid else (
            "unreviewed" if not complete or review.get("error") else "completed"
        )
        report.reviews.append(_review("material", review, state))


def _publication_checks(report: JobTrustReport, course: dict[str, Any]) -> None:
    report.content_hash = content_hash(course)
    saved = _read(report_path(str(course["id"])))
    if not saved:
        report.checks.append(TrustCheck(id="publication_report", label="最终发布验收",
                                      status="unknown", detail="尚无最终课件审查报告。"))
        return
    current = saved.get("content_hash") == report.content_hash
    report.checks.append(TrustCheck(id="publication_version", label="审查版本一致性",
                                  status="passed" if current else "failed",
                                  detail="审查报告绑定当前课件正文指纹；内容改变后旧报告失效。"))
    review = saved.get("model_review") or {}
    if review:
        report.reviews.append(_review("publication", review,
                                     str(saved.get("status")) if current else "stale",
                                     saved.get("reviewed_at")))
    try:
        assert_publishable(course)
        report.publication_status = "allowed"
    except (PublicationBlocked, ValueError, TypeError, KeyError):
        report.publication_status = "blocked"
    report.checks.append(TrustCheck(
        id="publication_gate", label="发布规则验收",
        status="passed" if report.publication_status == "allowed" else "failed",
        detail="程序按最终报告、报告指纹与程序检查结果决定是否允许发布；模型意见仅作诊断。"
               "不等于事实认证。",
    ))
