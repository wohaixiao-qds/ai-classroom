"""Eval 观测与教训审核 API。计算口径集中在 services.eval_metrics。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.lessons import list_lessons, review_lesson
from app.schemas.eval import (
    EvalGaps,
    EvalLessons,
    EvalRepeats,
    EvalSummary,
    EvalTraces,
    LegacyCourseDetail,
    LegacyCourses,
    Lesson,
    LessonReview,
)
from app.services import eval_metrics
from app.services.legacy_revision import (
    RevisionBlocked,
    audit_legacy_courses,
    legacy_course_detail,
)

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])


@router.get("/summary", response_model=EvalSummary)
def summary(include_test: bool = False) -> dict[str, Any]:
    return eval_metrics.summary(include_test)


@router.get("/traces", response_model=EvalTraces)
def traces(limit: int = Query(50, ge=1, le=200), include_test: bool = False) -> dict[str, Any]:
    return eval_metrics.traces(limit, include_test)


@router.get("/repeats", response_model=EvalRepeats)
def repeats(include_test: bool = False) -> dict[str, Any]:
    return eval_metrics.repeats(include_test)


@router.get("/gaps", response_model=EvalGaps)
def gaps(include_test: bool = False) -> dict[str, Any]:
    return eval_metrics.gaps(include_test)


@router.get("/lessons", response_model=EvalLessons)
def lessons() -> dict[str, Any]:
    return {"lessons": list_lessons()}


@router.post("/lessons/{lesson_id}/review", response_model=Lesson)
def review(lesson_id: str, req: LessonReview) -> dict[str, Any]:
    if not review_lesson(lesson_id, req.status, req.text):
        raise HTTPException(404, "教训候选不存在")
    return next(r for r in list_lessons() if r["id"] == lesson_id)


@router.get("/legacy-courses", response_model=LegacyCourses)
def legacy_courses() -> dict[str, Any]:
    return audit_legacy_courses()


@router.get("/legacy-courses/{course_id}", response_model=LegacyCourseDetail)
def legacy_course(course_id: str) -> dict[str, Any]:
    try:
        return legacy_course_detail(course_id)
    except RevisionBlocked as exc:
        raise HTTPException(404, str(exc)) from exc
