"""发布前强制验收:结构/原文定位/最终正文语义,失败保留草稿与报告。"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.trace import digest
from app.services.csl_validator import validate_course
from app.services.evidence import course_evidence_report, material_evidence
from app.services.evidence_review import review_claims


class PublicationBlocked(RuntimeError):
    pass


def content_hash(course: dict[str, Any]) -> str:
    payload = copy.deepcopy(course)
    payload.setdefault("meta", {}).pop("publication_review", None)
    return digest(payload)


def report_path(course_id: str) -> Path:
    return settings.data_dir / "publication" / f"{course_id}.json"


def assert_publishable(course: dict[str, Any]) -> None:
    """必须存在服务生成的、与当前内容绑定的完整报告;不信任课件自报通过。"""
    path = report_path(str(course["id"]))
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicationBlocked("发布被拦截:缺少有效的最终课件审查报告") from exc
    summary = course.get("meta", {}).get("publication_review") or {}
    blocks = course_evidence_report(course)["blocks"]
    expected_ids = {b["id"] for b in blocks}
    linked_ids = {b["id"] for b in blocks if b["evidence_ids"]}
    actual_ids = [i.get("id") for i in report.get("items", [])]
    if (
        report.get("status") != "model_reviewed"
        or report.get("errors")
        or report.get("content_hash") != content_hash(course)
        or summary.get("report_hash") != digest(report)
        or any(i.get("id") in linked_ids and i.get("verdict") == "not_applicable"
               for i in report.get("items", []))
        or not report.get("items")
        or set(actual_ids) != expected_ids or len(actual_ids) != len(expected_ids)
        or any(i.get("verdict") not in ("supported", "not_applicable") for i in report["items"])
    ):
        raise PublicationBlocked("发布被拦截:审查未通过、未完成或内容已变化,请查看审查报告")


def is_review_draft(course: dict[str, Any]) -> bool:
    """新课从建骨架起即为草稿;历史未审课保留兼容展示。"""
    meta = course.get("meta") or {}
    if not meta.get("publication_required") and not meta.get("publication_review"):
        return False
    try:
        assert_publishable(course)
    except (PublicationBlocked, ValueError, TypeError, KeyError):
        return True
    return False


def review_course(
    course: dict[str, Any], material: dict[str, Any], *, learning_goal: str = ""
) -> dict[str, Any]:
    """每次审查完整最终内容,不继承作者会话;不等价于人工复核。"""
    errors = list(validate_course(course)["errors"])
    evidence_report = course_evidence_report(course)
    errors.extend(evidence_report["errors"])
    try:
        original = {e["id"]: e for e in material_evidence(material)}
        source_urls = {s.get("id", i): s.get("url")
                       for i, s in enumerate(material.get("sources", []), 1)}
        for i, source in enumerate(course.get("meta", {}).get("sources", []), 1):
            if source_urls.get(source.get("id", i)) != source.get("url"):
                errors.append(f"来源 {source.get('id', i)} URL 与原料不一致")
        for item in course.get("meta", {}).get("evidence", []):
            source = original.get(item["id"], {})
            if source.get("quote_status") != "matched" or any(
                item.get(k) != source.get(k)
                for k in ("source_id", "quote", "context", "source_hash")
            ):
                errors.append(f"证据 {item['id']} 未获原文快照验证或已变化")
        if not original:
            errors.append("缺少可验证的原文证据")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"原文证据重验失败:{type(exc).__name__}")
    review: dict[str, Any] = {"items": []}
    if not errors:
        # 未直接关联的题目/图示也送审,提供同节依据,避免自动漏审。
        by_section: dict[str, dict[str, Any]] = {}
        for section in course.get("sections", []):
            refs = {eid for b in section["blocks"] for eid in b.get("evidence_ids", [])}
            by_section[section["id"]] = {
                "heading": section["heading"],
                "evidence": [
                    {key: original[eid].get(key) for key in
                     ("id", "source_id", "quote", "context", "source_hash")}
                    for eid in sorted(refs) if eid in original
                ],
            }
        claims = [
            {
                "id": b["id"],
                "text": b["text"],
                "learning_goal": learning_goal,
                "section": by_section[b["id"].rsplit(":", 1)[0]],
            }
            for b in evidence_report["blocks"]
        ]
        print(f"发布审查:最终课件 {len(claims)} 块逐项核对", flush=True)
        checkpoint_path = report_path(str(course["id"])).with_suffix(".checkpoint.json")
        previous = None
        if checkpoint_path.exists():
            try:
                previous = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = None

        def checkpoint(value: dict[str, Any]) -> None:
            from app.core.job_progress import ensure_job_active

            ensure_job_active()
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = checkpoint_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(checkpoint_path)

        review = review_claims(claims, course_mode=True, previous=previous, checkpoint=checkpoint)
        expected = {c["id"] for c in claims}
        actual = [i["id"] for i in review["items"]]
        if set(actual) != expected or len(actual) != len(expected):
            errors.append("最终课件审查缺项或重复,禁止发布")
        linked_ids = {b["id"] for b in evidence_report["blocks"] if b["evidence_ids"]}
        for item in review["items"]:
            if item["verdict"] == "not_applicable" and item["id"] in linked_ids:
                errors.append(f"{item['id']} 显式关联证据的块不能用不适用代替核对")
            if item["verdict"] not in ("supported", "not_applicable"):
                errors.append(f"{item['id']} [{item['verdict']}] {item['reason']}")
    status = "model_reviewed" if not errors and review["items"] else "blocked"
    if review.get("error") or any(i["verdict"] == "unreviewed" for i in review["items"]):
        status = "unreviewed"
    report = {
        "version": 1,
        "course_id": course["id"],
        "content_hash": content_hash(course),
        "status": status,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "errors": errors,
        "items": review["items"],
        "model_review": review,
    }
    from app.core.job_progress import ensure_job_active

    ensure_job_active()
    path = report_path(str(course["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    # 保存历次失败便于定位,最新报告用于发布校验。
    history = path.with_name(f"{course['id']}-{digest(report)[:12]}.json")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    history.write_text(text, encoding="utf-8")
    temp = path.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)
    course.setdefault("meta", {})["publication_review"] = {
        "status": status,
        "content_hash": report["content_hash"],
        "report_hash": digest(report),
        "reviewed_at": report["reviewed_at"],
        "reviewer": review.get("reviewer", "未完成"),
    }
    (settings.courses_dir / f"{course['id']}.csl.json").write_text(
        json.dumps(course, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def ensure_publication(
    course: dict[str, Any],
    material: dict[str, Any],
    *,
    learning_goal: str = "",
    job_binding: dict[str, Any] | None = None,
    prerequisite_titles: list[str] | None = None,
) -> dict[str, Any]:
    """首次审查加最多两轮定点修订;只重用绑定课件,不重建规划。"""
    from app.agent.prep import run_prep

    for attempt in range(3):
        if job_binding:
            from app.core.job_store import ensure_active

            ensure_active(job_binding)
        report = review_course(course, material, learning_goal=learning_goal)
        if job_binding:
            ensure_active(job_binding)
        if report["status"] == "model_reviewed":
            assert_publishable(course)
            if attempt == 0:
                from app.core.job_progress import emit_progress

                emit_progress("revision", "skipped", "本次审查通过，无需定点修订")
            return course
        # 审查服务失败不能让作者猜着改,保留草稿供恢复审查。
        if (
            attempt == 2
            or not report["items"]
            or any(i["verdict"] == "unreviewed" for i in report["items"])
        ):
            break
        print(f"发布审查未通过,定点修订 {attempt + 1}/2", flush=True)
        from app.core.job_progress import emit_progress

        emit_progress("revision", "running", f"定点修订 {attempt + 1}/2："
                      f"{len(report['errors'])} 项待处理意见")
        result = run_prep(
            material,
            resume_course_id=str(course["id"]),
            learning_goal=learning_goal,
            job_binding=job_binding,
            prerequisite_titles=prerequisite_titles,
            revision_feedback="\n".join(report["errors"]),
        )
        if not result.get("ok"):
            break
        emit_progress("revision", "completed", "修订章节已保存，等待重新审查")
        course = result["course"]
    raise PublicationBlocked(f"课程未发布:最终课件审查未通过;报告 {report_path(str(course['id']))}")
