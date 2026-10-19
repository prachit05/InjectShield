-- InjectShield schema. Idempotent: safe to run more than once.

CREATE TABLE IF NOT EXISTS jobs (
  id           UUID PRIMARY KEY,
  user_id      TEXT NOT NULL,          -- Cognito sub
  s3_key       TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued','scanning','done','failed')),
  attempts     INT  NOT NULL DEFAULT 0,
  error        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_user_created ON jobs (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS verdicts (
  job_id           UUID PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  label            TEXT NOT NULL CHECK (label IN ('safe','suspicious','malicious')),
  risk_score       REAL NOT NULL,
  prompt_injection REAL NOT NULL,
  memory_injection REAL NOT NULL,
  jailbreak        REAL NOT NULL,
  evidence         JSONB NOT NULL DEFAULT '[]',
  model_version    TEXT NOT NULL,
  latency_ms       INT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
