"""待学意图与阅读延伸问题的薄路由。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException

from app.schemas.wishlist import (
    LearningQuestion,
    QuestionOperation,
    WishlistItem,
    WishlistResponse,
    WishlistSave,
    WishlistStartResult,
    WishlistUpdate,
)
from app.services import wishlist

router = APIRouter(prefix="/api/v1", tags=["wishlist"])


@router.get("/wishlist", response_model=WishlistResponse)
def list_wishlist(
    status: Literal["pending", "started", "removed", "all"] = "pending",
) -> WishlistResponse:
    return wishlist.list_items(status)


@router.post("/wishlist", response_model=WishlistItem)
def save_wishlist(req: WishlistSave) -> WishlistItem:
    return wishlist.save_manual(req.title)


@router.patch("/wishlist/{item_id}", response_model=WishlistItem)
def update_wishlist(item_id: str, req: WishlistUpdate) -> WishlistItem:
    try:
        return wishlist.update_item(item_id, req.status)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/wishlist/{item_id}/start", response_model=WishlistStartResult)
def start_wishlist(item_id: str) -> WishlistStartResult:
    try:
        return wishlist.start_item(item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="任务未能启动，条目已保留，请重试") from exc


@router.get("/learning-questions", response_model=list[LearningQuestion])
def learning_questions(
    course_id: str | None = None,
    unassigned: bool = False,
    include_dismissed: bool = False,
) -> list[LearningQuestion]:
    if course_id is not None and unassigned:
        raise HTTPException(status_code=422, detail="course_id 与 unassigned 不可同时使用")
    return wishlist.list_questions(course_id, unassigned, include_dismissed)


@router.post("/learning-questions/{question_id}/save", response_model=WishlistItem)
def save_question(question_id: str) -> WishlistItem:
    try:
        return wishlist.save_question(question_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/learning-questions/{question_id}/dismiss", response_model=QuestionOperation)
def dismiss_question(question_id: str) -> QuestionOperation:
    try:
        wishlist.dismiss_question(question_id)
        return QuestionOperation(ok=True)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
