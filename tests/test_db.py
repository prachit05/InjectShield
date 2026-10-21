"""Real-Postgres tests for the migration and both repositories.

Set TEST_DATABASE_URL to an admin DSN (CI starts a postgres service; locally
`docker compose up -d postgres` and use postgresql://injectshield:injectshield@localhost:5432/injectshield).
Each test runs in a throwaway database. Skipped when TEST_DATABASE_URL is unset.
"""

import os
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from injectshield_api.db import Repository  # noqa: E402
from injectshield_api.migrate import migrate  # noqa: E402
from injectshield_shared.config import Settings  # noqa: E402
from injectshield_shared.models import CategoryScores, Evidence, JobStatus, Verdict  # noqa: E402
from injectshield_worker.db import JobNotFound, WorkerRepository  # noqa: E402

ADMIN_DSN = os.environ.get("TEST_DATABASE_URL")
SCHEMA = Path(__file__).resolve().parents[1] / "db" / "init.sql"

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def dsn():
    name = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    test_dsn = psycopg.conninfo.make_conninfo(ADMIN_DSN, dbname=name)
    migrate(test_dsn, SCHEMA)
    yield test_dsn
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def repos(dsn):
    api = Repository(dsn, max_size=2)
    worker = WorkerRepository(dsn)
    yield api, worker
    api.pool.close()


def verdict(label="malicious", risk=0.9):
    return Verdict(
        label=label,
        risk_score=risk,
        categories=CategoryScores(prompt_injection=risk),
        evidence=[
            Evidence(
                detector="rules",
                rule="ignore_previous",
                category="prompt_injection",
                span="Ignore all previous instructions",
                weight=0.8,
            )
        ],
        model_version="rules-v1+mem-v1",
        latency_ms=2,
    )


def test_migration_is_idempotent(dsn):
    migrate(dsn, SCHEMA)  # second run must not fail
    with psycopg.connect(dsn) as conn:
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert {"jobs", "verdicts"} <= tables


def test_full_job_lifecycle(repos):
    api, worker = repos
    job_id = uuid.uuid4()
    api.create_job(job_id, "user-a", "prompts/user-a/x.json")
    assert api.get_result(job_id, "user-a").status == JobStatus.QUEUED

    assert worker.start(job_id) is True
    assert api.get_result(job_id, "user-a").status == JobStatus.SCANNING

    worker.finish(job_id, verdict())
    result = api.get_result(job_id, "user-a")
    assert result.status == JobStatus.DONE
    assert result.verdict.label == "malicious"
    assert result.verdict.evidence[0].span == "Ignore all previous instructions"
    assert result.verdict.categories.prompt_injection == pytest.approx(0.9)


def test_other_users_cannot_read_job(repos):
    api, _ = repos
    job_id = uuid.uuid4()
    api.create_job(job_id, "user-a", "k")
    assert api.get_result(job_id, "user-b") is None
    assert api.list_jobs("user-b", 20) == []


def test_redelivery_is_idempotent(repos, dsn):
    api, worker = repos
    job_id = uuid.uuid4()
    api.create_job(job_id, "user-a", "k")
    worker.start(job_id)
    worker.finish(job_id, verdict("malicious", 0.9))

    assert worker.start(job_id) is False  # already done: worker just deletes the message
    worker.finish(job_id, verdict("safe", 0.0))  # ON CONFLICT DO NOTHING keeps the first verdict

    assert api.get_result(job_id, "user-a").verdict.label == "malicious"
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM verdicts WHERE job_id = %s", (job_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT attempts FROM jobs WHERE id = %s", (job_id,)).fetchone()[0] == 1


def test_failures_requeue_then_fail(repos):
    api, worker = repos
    job_id = uuid.uuid4()
    api.create_job(job_id, "user-a", "k")
    worker.start(job_id)
    worker.record_failure(job_id, "boom", final=False)
    assert api.get_result(job_id, "user-a").status == JobStatus.QUEUED
    worker.record_failure(job_id, "boom", final=True)
    result = api.get_result(job_id, "user-a")
    assert result.status == JobStatus.FAILED
    assert result.error == "boom"


def test_unknown_job_raises(repos):
    _, worker = repos
    with pytest.raises(JobNotFound):
        worker.start(uuid.uuid4())


def test_list_jobs_newest_first_with_verdicts(repos):
    api, worker = repos
    first, second = uuid.uuid4(), uuid.uuid4()
    api.create_job(first, "user-a", "k1")
    api.create_job(second, "user-a", "k2")
    worker.start(second)
    worker.finish(second, verdict("safe", 0.1))
    jobs = api.list_jobs("user-a", 20)
    assert [j.job_id for j in jobs] == [second, first]
    assert jobs[0].label == "safe"
    assert jobs[1].label is None
    assert len(api.list_jobs("user-a", 1)) == 1


def test_dsn_from_parts_escapes_password():
    settings = Settings(db_host="db.example", db_user="injectshield", db_password="p@ss:w/rd#1", db_sslmode="require")
    assert settings.dsn == "postgresql://injectshield:p%40ss%3Aw%2Frd%231@db.example:5432/injectshield?sslmode=require"
