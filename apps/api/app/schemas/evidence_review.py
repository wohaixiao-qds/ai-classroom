"""本地课件人工证据审查 API 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReviewVerdict = Literal["supported", "unsupported", "uncertain"]
ReviewStatus = Literal["unreviewed", "supported", "unsupported", "uncertain"]


class EvidenceReviewCourse(BaseModel):
    course_id: str
    title: str
    total_blocks: int
    reviewed_blocks: int
    supported: int
    unsupported: int
    uncertain: int


class EvidenceReviewCourses(BaseModel):
    courses: list[EvidenceReviewCourse]


class EvidenceReviewSource(BaseModel):
    id: int | None = None
    title: str
    url: str


class EvidenceReviewEvidence(BaseModel):
    """只提供人工核对所需的原文，不把模型已有结论展示给审阅者。"""

    id: str
    point: str
    source_id: int | None = None
    quote: str | None = None
    context: str | None = None
    quote_status: Literal["matched", "missing"]


class EvidenceReviewBlock(BaseModel):
    id: str
    section: str
    text: str
    evidence_ids: list[str]
    evidence: list[EvidenceReviewEvidence]
    sources: list[EvidenceReviewSource]
    input_hash: str
    verdict: ReviewStatus
    reason: str = ""
    reviewer: str = ""
    stale: bool = False


class EvidenceReviewDetail(BaseModel):
    course_id: str
    title: str
    offset: int
    limit: int
    total_blocks: int
    reviewed_blocks: int
    supported: int
    unsupported: int
    uncertain: int
    evidence_errors: list[str] = Field(default_factory=list)
    blocks: list[EvidenceReviewBlock]


class EvidenceReviewSave(BaseModel):
    block_id: str = Field(min_length=1, max_length=240)
    reviewer: str = Field(min_length=1, max_length=80)
    input_hash: str = Field(min_length=64, max_length=64)
    verdict: ReviewVerdict
    reason: str = Field(min_length=1, max_length=2000)


class EvidenceReviewSaved(BaseModel):
    block_id: str
    reviewer: str
    verdict: ReviewVerdict
    reason: str
    reviewed_at: str
    reviewed_blocks: int
    total_blocks: int


class EvidenceReviewTranslate(BaseModel):
    block_id: str = Field(min_length=1, max_length=240)
    evidence_id: str = Field(min_length=1, max_length=120)
    input_hash: str = Field(min_length=64, max_length=64)


class EvidenceReviewTranslation(BaseModel):
    evidence_id: str
    quote_translation: str | None = None
    context_translation: str | None = None
