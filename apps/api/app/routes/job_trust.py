"""生成任务的来源与验收依据，只读访问。"""
from __future__ import annotations

from fastapi import APIRouter

from app.services.job_trust import JobKind, JobTrustReport, build_job_trust

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs/trust", response_model=JobTrustReport)
def job_trust(kind: JobKind, target: str) -> JobTrustReport:
    return build_job_trust(kind, target)
