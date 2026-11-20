"""待学清单与阅读延伸问题；状态与任务生命周期分别保存。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.jobs import JobSummary

WishlistStatus = Literal["pending", "started", "removed"]


class WishlistSource(BaseModel):
    kind: Literal["manual", "vault", "question"]
    id: str
    label: str
    course_id: str | None = None
    page_id: str | None = None
    run_id: str | None = None


class WishlistItem(BaseModel):
    id: str
    title: str
    status: WishlistStatus
    created_at: str
    sources: list[WishlistSource]
    job: JobSummary | None = None


class WishlistResponse(BaseModel):
    items: list[WishlistItem]
    pending_count: int


class WishlistSave(BaseModel):
    title: str = Field(min_length=1, max_length=500)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请输入想学的主题")
        return value


class WishlistUpdate(BaseModel):
    status: Literal["pending", "removed"]


class WishlistStartResult(BaseModel):
    item: WishlistItem
    job: JobSummary
    created: bool
    note: str


class LearningQuestion(BaseModel):
    id: str
    question: str
    course_id: str | None = None
    page_id: str | None = None
    run_id: str | None = None
    created_at: str | None = None
    detail: str | None = None
    status: Literal["candidate", "saved", "dismissed"]
    wishlist_id: str | None = None


class QuestionOperation(BaseModel):
    ok: bool
