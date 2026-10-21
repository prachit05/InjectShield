"""Apply db/init.sql at API startup (RUN_MIGRATIONS=true).

This replaces the manual "run init.sql once against RDS" step: RDS stays
private to the VPC, and every deploy converges on the same schema. init.sql is
idempotent, and an advisory lock stops two API tasks starting together from
racing each other.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

log = logging.getLogger("injectshield.api.migrate")

LOCK_ID = 7_302_026  # any constant shared by every API task


def migrate(dsn: str, schema_file: Path) -> None:
    sql = schema_file.read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute(sql)  # no parameters, so multiple statements are allowed
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    log.info("schema applied from %s", schema_file.name)
