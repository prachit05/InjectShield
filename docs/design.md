# InjectShield design

Export of the design doc (19 October 2026), updated to match what was built. The
original is the "InjectShield Design Doc" on claude.ai; the decisions taken since are
listed under [Changes from the original plan](#changes-from-the-original-plan).

## Overview

InjectShield is a deployed AWS service that takes a prompt and returns a risk verdict
for prompt injection, memory injection and jailbreak attempts. It is the Cloud
Computing (702IT0C026) mini project, built from the "LLM Guardrail-as-a-Service" spec.

The API never scans inline. It stores the prompt, queues a job and answers with a job
ID at once; autoscaling workers do the scan and write the verdict for the client to fetch.

**Goals**

- Show compute, storage, messaging, database, identity, scaling and monitoring on AWS, each with a clear role.
- Stay responsive under load: workers scale on SQS queue depth, and a load test proves it live.
- Give a credible detector (rules plus memory-injection checks, optional small classifier) that reuses the QARC research.
- Build and tear down the whole stack from CloudFormation templates.

**Non-goals**

- A state-of-the-art detector. The cloud architecture earns the marks; detection only needs to be explainable.
- Real-time inline blocking for a production LLM app.
- Multi-region or high-availability guarantees beyond what the labs cover.

## Requirements

The system must accept a prompt from a logged-in user, return a job ID in under a
second, and produce a verdict within seconds at normal load.

| ID | Requirement | Type |
|---|---|---|
| F1 | Users sign up and log in through Cognito; every API call carries a valid JWT | Functional |
| F2 | `POST /scan` stores the prompt in S3, creates a job row, queues the job in SQS and returns `202` with a job ID | Functional |
| F3 | `GET /result/{id}` returns status (`queued`, `scanning`, `done`, `failed`) and, when done, the verdict | Functional |
| F4 | Verdict = overall risk score 0 to 1, label (`safe`, `suspicious`, `malicious`), category scores and the matched evidence | Functional |
| F5 | A user only sees their own jobs | Functional |
| F6 | A web page lets a user paste a prompt and see the verdict and their history | Functional |
| N1 | Workers scale out on SQS queue depth and back in when idle | Scalability |
| N2 | A job that fails 3 times goes to the dead-letter queue, never lost silently | Reliability |
| N3 | S3 and RDS encrypted at rest; each service has its own least-privilege IAM role; no admin ports open | Security |
| N4 | CloudWatch dashboard shows queue depth, running tasks, scan latency and errors; alarms on DLQ and errors | Observability |
| N5 | Whole stack builds from CloudFormation and is removed by `teardown.sh` | Deployability |
| N6 | AWS Budget alert exists before the first deploy; no NAT gateway | Cost |

Where each one is implemented: [services-used.md](services-used.md#requirements-and-where-they-are-met).

## Architecture

SQS splits the system in two: a thin ingest API that only stores and queues, and
scanner workers that scale on queue depth. That split is the main design decision.

A request goes browser, CloudFront, ALB, API (Cognito JWT checked), then the prompt to
S3 and a small job message to SQS. Workers read the job, fetch the prompt, scan it,
write the verdict to RDS, and the API reads it back on `GET /result`. Jobs that fail 3
times land in the dead-letter queue. The diagram is in the [README](../README.md).

**Detection pipeline (inside each worker)**

1. **Normalise**: Unicode NFKC, strip zero-width and bidi characters, decode base64 or URL-encoded blocks.
2. **Rules** (`rules.py`): weighted regex patterns for instruction override, role-play jailbreaks, system-prompt extraction and hidden payloads. Each hit adds its weight to its category and records the matched span.
3. **Memory injection** (`memory_injection.py`): scans the optional `context` field for text that tries to persist instructions ("remember that", "from now on", "always respond"), exfiltrate data, or impersonate the system or a tool, based on the QARC research.
4. **Classifier** (`classifier.py`, optional): a small pretrained prompt-injection model on CPU, loaded once per worker.
5. **Scoring** (`scoring.py`): each category score is capped at 1; overall risk is the highest category; `safe` below 0.4, `suspicious` 0.4 to 0.7, `malicious` above 0.7. Thresholds live in config.

Every detector implements `scan(prompt, context) -> list[Finding]`, so adding or
dropping one does not touch the worker loop.

## API and data model

| Method | Path | Returns |
|---|---|---|
| POST | `/scan` | `202 {"job_id": "uuid", "status": "queued"}` |
| GET | `/result/{job_id}` | `200` with status and, when done, the verdict; `404` if the job is not the caller's |
| GET | `/jobs?limit=20` | The caller's recent jobs for the history view |
| GET | `/health` | `200 {"ok": true}` for the ALB health check |

The SQS message stays small; the prompt lives in S3 at `prompts/{user_id}/{job_id}.json`:

```json
{ "job_id": "6f1c...", "user_id": "cognito-sub", "s3_key": "prompts/<sub>/6f1c....json", "submitted_at": "2026-10-19T09:00:00Z" }
```

RDS Postgres holds two tables, `jobs` and `verdicts` ([db/init.sql](../db/init.sql)).
Workers write the verdict with `INSERT ... ON CONFLICT (job_id) DO NOTHING`, so an SQS
redelivery never creates a duplicate.

## Repo structure

```
InjectShield/
├── README.md, Makefile, docker-compose.yml, .env.example, pyproject.toml
├── .github/workflows/ci.yml       # ruff, pytest (with Postgres), cfn-lint, script parse, image builds
├── shared/injectshield_shared/    # models, config, AWS client factory, EMF metrics
├── api/injectshield_api/          # main, auth (Cognito JWKS), queue, storage, db, migrate
├── worker/injectshield_worker/    # main loop, scanner, normalize, scoring, evaluate, detectors/
├── frontend/                      # index.html, config.js, src/{app,auth,api}.js, src/style.css
├── db/init.sql
├── infra/                         # network, storage, queue, database, iam, registry,
│                                  # auth, compute, autoscaling, monitoring, frontend
├── scripts/                       # deploy, teardown, create-budget, smoke, load-test.py,
│                                  # create-user, token, localstack/init-aws.sh
├── tests/                         # detectors, scoring, api, worker, db, infra, sample_prompts/
└── docs/                          # deployment.md, services-used.md, design.md, screenshots/
```

## Build phases

| Phase | Scope | Status |
|---|---|---|
| 0 | Tooling, repo, budget, AWS profile | Done |
| 1 | Detector core, sample prompts, tests | Done |
| 2 | Full flow locally (docker compose with Postgres and LocalStack), CI | Done |
| 3 | Network, storage, queue, database, IAM stacks; deploy and teardown scripts | Done |
| 4 | ECR, ECS cluster, ALB, API and worker services; image build and push in `deploy.sh` | Built; verify on first real deploy |
| 5 | Cognito, worker autoscaling, load test | Built; verify on first real deploy |
| 6 | Dashboard and alarms, web app on S3 + CloudFront, report docs | Built; screenshots come from the first real deploy |

If time runs short, cut the classifier first, then the frontend (demo with `curl` or
Swagger at `/docs`).

## Testing

Three layers: unit tests for each detector and for scoring against the sample prompts;
API and worker tests with moto mocking S3 and SQS (including the DLQ path) and real
Postgres tests in CI; and the deployed smoke test plus the load test. Detection accuracy
on the sample set (precision and recall per category, from
`python -m injectshield_worker.evaluate`) is reported in the viva, not as a headline claim.

## Risks

| Risk | Mitigation |
|---|---|
| Surprise AWS bill | Budget alert first, no NAT gateway, `db.t4g.micro`, `teardown.sh` after every session |
| Classifier image too large or slow on Fargate | Off by default; when enabled the worker gets 1 vCPU / 2 GB and loads the model once |
| Message processed twice | Idempotent verdict insert; delete the SQS message only after the DB commit |
| Poison message loops forever | DLQ after 3 receives, CloudWatch alarm on DLQ depth |
| Cognito wiring eats time | `AUTH_DISABLED` for local dev; the web app calls the Cognito API directly |
| Prompts contain sensitive text | S3 encryption, prompts deleted after 7 days, prompt bodies never logged |

## Changes from the original plan

The open questions are settled as follows, plus a few changes found while building.

- **ALB or API Gateway**: ALB, as proposed. It matches the labs and works directly with ECS.
- **Classifier**: `protectai/deberta-v3-base-prompt-injection-v2`, optional and off by
  default; enable with `CLASSIFIER=true scripts/deploy.sh`.
- **Separate `registry` stack**: the ECR repositories moved out of `compute.yaml` because
  the images must be pushed before the ECS services that run them are created.
- **Separate `frontend` stack, and the API through CloudFront**: the ALB has no
  certificate, and an HTTPS page cannot call an HTTP API. CloudFront serves the site and
  forwards the API paths to the ALB, so everything is HTTPS on one origin with no CORS.
- **No Hosted UI**: the web app calls Cognito's `SignUp` / `ConfirmSignUp` /
  `InitiateAuth` directly. The user pool then needs no callback URLs, which removes a
  circular dependency between the `auth` stack and the CloudFront domain.
- **Schema applied by the API at startup** (`RUN_MIGRATIONS=true`, under an advisory
  lock) instead of a one-off task, so RDS never has to be reachable from outside the VPC.
- **Learner Lab**: IAM is read-only there, so all tasks use `LabRole` and the IAM stack is
  skipped; budgets cannot be created, so the lab's credit cap stands in for N6.
