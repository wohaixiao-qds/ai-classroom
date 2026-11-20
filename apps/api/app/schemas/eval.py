"""Eval API 契约,由 OpenAPI 生成前端类型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Assessment(BaseModel):
    verdict: str
    reason: str = ""
    skip_reason: str | None = None
    version: str | None = None
    model: str | None = None
    selection: str | None = None
    elapsed_s: float = 0
    usage: dict[str, int] = Field(default_factory=dict)


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ms: float = 0
    error: str | None = None
    result: str | None = None
    feedback: str | None = None
    reused_from_call: int | None = None


class ResearchEvidence(BaseModel):
    matched: int
    total: int
    reviewed: int
    review_error: str | None = None
    verdicts: dict[str, int]


class ResearchCost(BaseModel):
    generation_s: float
    tool_s: float
    review_s: float
    generation_usage: dict[str, int]
    review_usage: dict[str, int]
    total_usage: dict[str, int]


class ResearchOutline(BaseModel):
    courses: int
    sourced_courses: int
    sources: int


class TraceRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_id: str | None = None
    ts: str = ""
    stage: str = ""
    status: str = "unknown"
    source: str = "user"
    course_id: str = ""
    page_id: str | None = None
    question: str = ""
    answer: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    cited_pages: list[int] = Field(default_factory=list)
    citation_valid: bool | None = None
    tool_error: bool = False
    searched: bool | int = False
    soft_landed: bool = False
    truncated: bool = False
    turns: int | None = None
    elapsed_s: float = 0
    usage: dict[str, int] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)
    self_eval: Assessment | None = None
    research_evidence: ResearchEvidence | None = None
    research_cost: ResearchCost | None = None
    research_outline: ResearchOutline | None = None
    validation_errors: list[str] = Field(default_factory=list)
    material_path: str | None = None
    fetched: int = 0
    guard_violations: list[str] = Field(default_factory=list)
    reteach: list[str] = Field(default_factory=list)
    error: str | None = None
    topic: str = ""
    subtopic: str = ""
    verdict: str | None = None
    score: int | None = None
    raw_score: int | None = None
    tutored: bool = False


class QualityMetrics(BaseModel):
    answers: int
    checked: int
    coverage_pct: float | None
    support_rate_pct: float | None
    assessment_counts: dict[str, int]
    skip_reasons: dict[str, int]
    citation_checks: int
    valid_citation_pct: float | None
    citation_unknown: int
    guard_violations: int
    reteach: int
    tool_used: int
    tool_error: int
    searched: int
    soft_landed: int
    truncated: int


class CostMetrics(BaseModel):
    avg_elapsed_s: float
    in_tokens: int
    out_tokens: int
    judge_in_tokens: int
    judge_out_tokens: int
    judge_elapsed_s: float
    unknown_usage: int


class StageMetrics(BaseModel):
    total: int
    statuses: dict[str, int]


class EvalSummary(BaseModel):
    asks: int
    quality: QualityMetrics
    cost: CostMetrics
    stages: dict[str, StageMetrics]
    verdict_counts: dict[str, int]
    tutored_grades: int
    window: int = 1000
    eval_version: str


class EvalTraces(BaseModel):
    tutor: list[TraceRecord]
    grade: list[TraceRecord]
    research: list[TraceRecord]
    prep: list[TraceRecord]


class RepeatGroup(BaseModel):
    question: str
    course_id: str
    page_id: str | None
    count: int
    comparable: bool
    history: list[TraceRecord]


class EvalRepeats(BaseModel):
    repeats: list[RepeatGroup]
    count: int


class GapSignal(BaseModel):
    kind: Literal["searched", "repeated", "checkpoint_fail"]
    question: str
    detail: str
    course_id: str = ""
    ts: str | None = None


class EvalGaps(BaseModel):
    gaps: list[GapSignal]
    count: int


class Lesson(BaseModel):
    id: str
    text: str
    status: Literal["pending", "approved", "rejected"]
    run_id: str | None
    evidence: dict[str, Any]
    created_at: str
    reviewed_at: str | None


class EvalLessons(BaseModel):
    lessons: list[Lesson]


class LessonReview(BaseModel):
    status: Literal["approved", "rejected"]
    text: str | None = Field(default=None, min_length=1, max_length=1000)
