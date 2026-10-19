"""Postgres access for the worker. One connection per process, reopened if it drops."""

from __future__ import annotations

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from injectshield_shared.models import Verdict


class JobNotFound(Exception):
    pass


class WorkerRepository:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._conn: psycopg.Connection | None = None

    def _connection(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed or self._conn.broken:
            self._conn = psycopg.connect(self.dsn, autocommit=True)
        return self._conn

    def start(self, job_id: UUID) -> bool:
        """Mark the job scanning. Returns False if it is already done (an SQS redelivery)."""
        row = (
            self._connection()
            .execute(
                """
                UPDATE jobs SET status = 'scanning', attempts = attempts + 1, updated_at = now()
                WHERE id = %s AND status <> 'done'
                RETURNING id
                """,
                (job_id,),
            )
            .fetchone()
        )
        if row is not None:
            return True
        exists = self._connection().execute("SELECT 1 FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if exists is None:
            raise JobNotFound(str(job_id))
        return False

    def finish(self, job_id: UUID, verdict: Verdict) -> None:
        """Write the verdict and mark the job done in one transaction. Idempotent."""
        conn = self._connection()
        c = verdict.categories
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO verdicts (job_id, label, risk_score, prompt_injection, memory_injection,
                                      jailbreak, evidence, model_version, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id) DO NOTHING
                """,
                (
                    job_id,
                    verdict.label,
                    verdict.risk_score,
                    c.prompt_injection,
                    c.memory_injection,
                    c.jailbreak,
                    Jsonb([e.model_dump() for e in verdict.evidence]),
                    verdict.model_version,
                    verdict.latency_ms,
                ),
            )
            conn.execute(
                "UPDATE jobs SET status = 'done', error = NULL, updated_at = now() WHERE id = %s",
                (job_id,),
            )

    def record_failure(self, job_id: UUID, error: str, final: bool) -> None:
        """final=True on the last allowed attempt: the message is about to go to the DLQ."""
        self._connection().execute(
            "UPDATE jobs SET status = %s, error = %s, updated_at = now() WHERE id = %s AND status <> 'done'",
            ("failed" if final else "queued", error, job_id),
        )
