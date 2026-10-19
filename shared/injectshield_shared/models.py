"""Pydantic schemas: the contract between frontend, API, queue and worker."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

MAX_PROMPT_CHARS = 20_000
MAX_CONTEXT_CHARS = 50_000

Label = Literal["safe", "suspicious", "malicious"]
Category = Literal["prompt_injection", "memory_injection", "jailbreak"]
CATEGORIES: tuple[Category, ...] = ("prompt_injection", "memory_injection", "jailbreak")


class JobStatus(StrEnum):
    QUEUED = "queued"
    SCANNING = "scanning"
    DONE = "done"
    FAILED = "failed"


class ScanRequest(BaseModel):
    """Body of POST /scan."""

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    context: str | None = Field(
        default=None,
        max_length=MAX_CONTEXT_CHARS,
        description="Optional retrieved memory or chat history to check for memory injection",
    )


class ScanAccepted(BaseModel):
    """202 response of POST /scan."""

    job_id: UUID
    status: JobStatus = JobStatus.QUEUED


class JobMessage(BaseModel):
    """SQS message body. Kept small: the prompt itself lives in S3."""

    job_id: UUID
    user_id: str
    s3_key: str
    submitted_at: datetime


class StoredPrompt(BaseModel):
    """S3 object body at prompts/{user_id}/{job_id}.json."""

    job_id: UUID
    user_id: str
    prompt: str
    context: str | None = None
    submitted_at: datetime


class Evidence(BaseModel):
    detector: str
    rule: str
    category: Category
    span: str
    weight: float


class CategoryScores(BaseModel):
    prompt_injection: float = Field(default=0.0, ge=0.0, le=1.0)
    memory_injection: float = Field(default=0.0, ge=0.0, le=1.0)
    jailbreak: float = Field(default=0.0, ge=0.0, le=1.0)


class Verdict(BaseModel):
    label: Label
    risk_score: float = Field(ge=0.0, le=1.0)
    categories: CategoryScores
    evidence: list[Evidence] = Field(default_factory=list)
    model_version: str
    latency_ms: int | None = None


class JobResult(BaseModel):
    """Response of GET /result/{job_id}."""

    job_id: UUID
    status: JobStatus
    verdict: Verdict | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class JobSummary(BaseModel):
    job_id: UUID
    status: JobStatus
    label: Label | None = None
    risk_score: float | None = None
    created_at: datetime


class JobList(BaseModel):
    """Response of GET /jobs."""

    jobs: list[JobSummary]


def s3_key_for(user_id: str, job_id: UUID) -> str:
    return f"prompts/{user_id}/{job_id}.json"
