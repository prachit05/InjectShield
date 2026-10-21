"""InjectShield ingest API.

It never scans inline: POST /scan stores the prompt in S3, records the job,
queues it in SQS and answers 202 with a job ID. Workers do the scanning.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from injectshield_shared import aws
from injectshield_shared.config import get_settings
from injectshield_shared.models import (
    JobList,
    JobMessage,
    JobResult,
    ScanAccepted,
    ScanRequest,
    StoredPrompt,
    s3_key_for,
)

from .auth import current_user
from .db import Repository
from .migrate import migrate
from .queue import JobQueue
from .storage import PromptStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("injectshield.api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.run_migrations:
        migrate(settings.dsn, Path(settings.schema_file))
    yield


app = FastAPI(
    title="InjectShield",
    version="0.1.0",
    description="Prompt injection, memory injection and jailbreak risk scanning as a service.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@lru_cache
def get_repo() -> Repository:
    return Repository(get_settings().dsn)


@lru_cache
def get_store() -> PromptStore:
    settings = get_settings()
    return PromptStore(aws.client("s3", settings), settings.bucket)


@lru_cache
def get_queue() -> JobQueue:
    settings = get_settings()
    return JobQueue(aws.client("sqs", settings), settings.queue_url)


User = Annotated[str, Depends(current_user)]
Repo = Annotated[Repository, Depends(get_repo)]


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"ok": True}


@app.post("/scan", status_code=status.HTTP_202_ACCEPTED, response_model=ScanAccepted)
def submit_scan(
    request: ScanRequest,
    user_id: User,
    repo: Repo,
    store: Annotated[PromptStore, Depends(get_store)],
    queue: Annotated[JobQueue, Depends(get_queue)],
) -> ScanAccepted:
    job_id = uuid4()
    submitted_at = datetime.now(UTC)
    key = s3_key_for(user_id, job_id)

    # Order matters: S3 and the job row exist before the worker can see the message.
    store.put(
        key,
        StoredPrompt(
            job_id=job_id, user_id=user_id, prompt=request.prompt, context=request.context, submitted_at=submitted_at
        ),
    )
    repo.create_job(job_id, user_id, key)
    try:
        queue.send(JobMessage(job_id=job_id, user_id=user_id, s3_key=key, submitted_at=submitted_at))
    except Exception as exc:
        log.exception("enqueue failed job_id=%s", job_id)
        repo.mark_failed(job_id, "could not queue job")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "scan queue unavailable") from exc

    log.info("queued job_id=%s prompt_chars=%d", job_id, len(request.prompt))  # never log the prompt body
    return ScanAccepted(job_id=job_id)


@app.get("/result/{job_id}", response_model=JobResult, response_model_exclude_none=True)
def get_result(job_id: UUID, user_id: User, repo: Repo) -> JobResult:
    result = repo.get_result(job_id, user_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return result


@app.get("/jobs", response_model=JobList)
def list_jobs(user_id: User, repo: Repo, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> JobList:
    return JobList(jobs=repo.list_jobs(user_id, limit))
