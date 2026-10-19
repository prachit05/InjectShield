"""Postgres access for the API (psycopg 3 with a small connection pool)."""

from __future__ import annotations

from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from injectshield_shared.models import CategoryScores, JobResult, JobStatus, JobSummary, Verdict


class Repository:
    def __init__(self, dsn: str, max_size: int = 10):
        self.pool = ConnectionPool(dsn, min_size=1, max_size=max_size, kwargs={"row_factory": dict_row}, open=True)

    def create_job(self, job_id: UUID, user_id: str, s3_key: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO jobs (id, user_id, s3_key) VALUES (%s, %s, %s)",
                (job_id, user_id, s3_key),
            )

    def mark_failed(self, job_id: UUID, error: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'failed', error = %s, updated_at = now() WHERE id = %s",
                (error, job_id),
            )

    def get_result(self, job_id: UUID, user_id: str) -> JobResult | None:
        """Only returns the job if it belongs to user_id, so other users get a 404."""
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                SELECT j.id, j.status, j.error, j.created_at, j.updated_at,
                       v.label, v.risk_score, v.prompt_injection, v.memory_injection, v.jailbreak,
                       v.evidence, v.model_version, v.latency_ms
                FROM jobs j LEFT JOIN verdicts v ON v.job_id = j.id
                WHERE j.id = %s AND j.user_id = %s
                """,
                (job_id, user_id),
            ).fetchone()
        if row is None:
            return None
        verdict = None
        if row["label"] is not None:
            verdict = Verdict(
                label=row["label"],
                risk_score=row["risk_score"],
                categories=CategoryScores(
                    prompt_injection=row["prompt_injection"],
                    memory_injection=row["memory_injection"],
                    jailbreak=row["jailbreak"],
                ),
                evidence=row["evidence"],
                model_version=row["model_version"],
                latency_ms=row["latency_ms"],
            )
        return JobResult(
            job_id=row["id"],
            status=JobStatus(row["status"]),
            verdict=verdict,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_jobs(self, user_id: str, limit: int) -> list[JobSummary]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT j.id, j.status, j.created_at, v.label, v.risk_score
                FROM jobs j LEFT JOIN verdicts v ON v.job_id = j.id
                WHERE j.user_id = %s
                ORDER BY j.created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [
            JobSummary(
                job_id=r["id"],
                status=JobStatus(r["status"]),
                label=r["label"],
                risk_score=r["risk_score"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
