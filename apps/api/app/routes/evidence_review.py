"""已发布课件的本地人工原文审查入口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas.evidence_review import (
    EvidenceReviewCourses,
    EvidenceReviewDetail,
    EvidenceReviewSave,
    EvidenceReviewSaved,
    EvidenceReviewTranslate,
    EvidenceReviewTranslation,
)
from app.services import human_evidence_review
from app.services.human_evidence_review import (
    CourseNotReviewable,
    ReviewConflict,
    ReviewDataInvalid,
    ReviewTranslationFailed,
)

router = APIRouter(prefix="/api/v1/evidence-review", tags=["evidence-review"])


@router.get("/courses", response_model=EvidenceReviewCourses)
def review_courses() -> dict[str, Any]:
    try:
        return human_evidence_review.list_courses()
    except ReviewDataInvalid as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{course_id}/translate", response_model=EvidenceReviewTranslation)
def translate_evidence(
    course_id: str, req: EvidenceReviewTranslate,
) -> dict[str, Any]:
    try:
        return human_evidence_review.translate_evidence(
            course_id,
            block_id=req.block_id,
            evidence_id=req.evidence_id,
            input_hash=req.input_hash,
        )
    except CourseNotReviewable as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ReviewDataInvalid as exc:
        raise HTTPException(502, str(exc)) from exc
    except ReviewTranslationFailed as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/{course_id}", response_model=EvidenceReviewDetail)
def review_course(
    course_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, object]:
    try:
        return human_evidence_review.get_course(course_id, offset=offset, limit=limit)
    except CourseNotReviewable as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReviewDataInvalid as exc:
        raise HTTPException(409, str(exc)) from exc


@router.put("/{course_id}", response_model=EvidenceReviewSaved)
def save_review(course_id: str, req: EvidenceReviewSave) -> dict[str, object]:
    try:
        return human_evidence_review.save_review(
            course_id,
            block_id=req.block_id,
            reviewer=req.reviewer,
            input_hash=req.input_hash,
            verdict=req.verdict,
            reason=req.reason,
        )
    except CourseNotReviewable as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ReviewDataInvalid as exc:
        raise HTTPException(422, str(exc)) from exc
