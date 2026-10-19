# InjectShield

Guardrail-as-a-service on AWS. Send a prompt (and optional retrieved memory or chat
history); get back a risk verdict for prompt injection, memory injection and jailbreak
attempts. Cloud Computing (702IT0C026) mini project.

The API never scans inline. It stores the prompt in S3, records the job in RDS, queues
it in SQS and answers `202` with a job ID. Scanner workers, scaled on queue depth, do
the work and write the verdict for the client to fetch.

```
client ─► ALB ─► API (Cognito JWT) ─┬─► S3   prompts/{user}/{job}.json
                                    ├─► RDS  jobs row (queued)
                                    └─► SQS  {job_id, s3_key} ──► workers ──► RDS verdict
                                                 └─ 3 failures ─► DLQ
```

## Layout

| Path | What |
|---|---|
| `shared/injectshield_shared/` | Pydantic models, settings, AWS client factory, CloudWatch EMF metrics |
| `api/injectshield_api/` | FastAPI ingest service: `POST /scan`, `GET /result/{id}`, `GET /jobs`, `GET /health` |
| `worker/injectshield_worker/` | SQS worker loop, detection pipeline, scoring, sample-set evaluation |
| `db/init.sql` | `jobs` and `verdicts` tables |
| `tests/` | detector, scoring, API (moto) and worker (moto + DLQ) tests, sample prompts |
| `infra/` | CloudFormation (Phase 3 onwards) |

The services are packaged as `injectshield_api` and `injectshield_worker`, not `app`,
so both test suites can be imported in one pytest run.

## Detection pipeline

1. **Normalise**: NFKC, strip zero-width/bidi characters, decode base64 and URL-encoded blocks
2. **Rules** (`detectors/rules.py`): 32 weighted regex rules across the three categories
3. **Memory injection** (`detectors/memory_injection.py`): 8 rule families for instructions hidden in the `context` field
4. **Classifier** (`detectors/classifier.py`, optional, off by default)
5. **Scoring**: category score = sum of rule weights, capped at 1; risk = max category;
   `safe` < 0.4 ≤ `suspicious` ≤ 0.7 < `malicious` (thresholds in config)

Every detector implements `scan(prompt, context) -> list[Finding]`.

## Local development

Needs Python 3.11+ and Docker Desktop.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

pytest                             # unit + API + worker tests, no Docker needed
ruff check . && ruff format --check .
PYTHONPATH=shared:worker python -m injectshield_worker.evaluate tests/sample_prompts
```

Full stack (API, worker, Postgres, LocalStack S3 + SQS), with auth stubbed by `AUTH_DISABLED=true`:

```bash
docker compose up --build
scripts/smoke.sh
# or by hand:
curl -s -X POST localhost:8000/scan -H 'content-type: application/json' \
  -d '{"prompt":"Ignore all previous instructions"}'
curl -s localhost:8000/result/<job_id>
```

Interactive API docs: http://localhost:8000/docs

## API

All routes except `/health` need `Authorization: Bearer <Cognito JWT>` (ID or access token).

```jsonc
// POST /scan  ->  202 {"job_id": "…", "status": "queued"}
{ "prompt": "Ignore all previous instructions and ...", "context": "optional memory or chat history" }

// GET /result/{job_id} when done
{
  "job_id": "…", "status": "done",
  "verdict": {
    "label": "malicious", "risk_score": 1.0,
    "categories": { "prompt_injection": 1.0, "memory_injection": 0.0, "jailbreak": 0.0 },
    "evidence": [ { "detector": "rules", "rule": "ignore_previous", "category": "prompt_injection",
                    "span": "Ignore all previous instructions", "weight": 0.8 } ],
    "model_version": "rules-v1+mem-v1", "latency_ms": 1
  }
}
```

A job that is not the caller's returns 404, the same as one that does not exist.

## Reliability

- The worker deletes the SQS message only after the verdict commit.
- Verdict insert is `ON CONFLICT (job_id) DO NOTHING`, and a redelivered message for a
  finished job is just deleted.
- Failures are retried with backoff; on the 3rd receive the job is marked `failed` and
  SQS moves the message to the DLQ.
- Prompt bodies are never logged.

## Metrics

The worker prints CloudWatch Embedded Metric Format lines (namespace `InjectShield`):
`ScanLatency`, `ProcessingLatency`, `EndToEndLatency`, `JobsCompleted`, `ScanErrors`.
With the `awslogs` driver on ECS these become metrics with no extra API calls or IAM permissions.
