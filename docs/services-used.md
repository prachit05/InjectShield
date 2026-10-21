# AWS services used

Each AWS service has one job. The split that matters: **SQS separates a thin ingest
API from scanner workers that scale on queue depth.**

| Area | Service | Role in InjectShield | Defined in |
|---|---|---|---|
| Compute | **ECS on Fargate** | Runs the API (behind the ALB) and the scanner workers as separate services, with no servers to manage | `infra/compute.yaml` |
| Compute | **ECR** | Stores the API and worker images that `deploy.sh` builds and pushes | `infra/registry.yaml` |
| Networking | **VPC** | Two public subnets in two AZs, security groups chained ALB → API → RDS and worker → RDS, free S3 gateway endpoint, no NAT gateway | `infra/network.yaml` |
| Networking | **Elastic Load Balancing (ALB)** | Public entry point for the API; health-checks `/health` and only sends traffic to healthy tasks | `infra/compute.yaml` |
| Networking | **CloudFront** | HTTPS for the web app and the API under one origin; serves the static site from the private bucket | `infra/frontend.yaml` |
| Storage | **S3** | Prompts bucket (encrypted, TLS-only, deleted after 7 days) so queue messages stay small; private frontend bucket | `infra/storage.yaml` |
| Messaging | **SQS** | Scan queue that decouples API from workers (long polling, 60 s visibility); dead-letter queue after 3 failed receives | `infra/queue.yaml` |
| Database | **RDS for PostgreSQL** | `jobs` and `verdicts` tables; encrypted, not publicly accessible, reachable only from the two task security groups | `infra/database.yaml`, `db/init.sql` |
| Identity | **Cognito** | User sign-up and sign-in; the API verifies the JWT on every call and scopes every query to the caller's `sub` | `infra/auth.yaml`, `api/injectshield_api/auth.py` |
| Identity | **IAM** + **Secrets Manager** | One least-privilege task role per service, scoped to exact ARNs; the DB password is generated into Secrets Manager and injected at task start | `infra/iam.yaml`, `infra/database.yaml` |
| Scaling | **Application Auto Scaling** | Target tracking on scan-queue depth: 1 to 5 worker tasks | `infra/autoscaling.yaml` |
| Monitoring | **CloudWatch** (+ SNS) | Logs, EMF metrics from the worker, Container Insights task counts, one dashboard, alarms on DLQ, scan errors and 5xx, emailed through SNS | `infra/monitoring.yaml`, `shared/injectshield_shared/metrics.py` |
| Deployment | **CloudFormation** | Every resource above, in 11 stacks with cross-stack exports; `teardown.sh` removes them all | `infra/`, `scripts/deploy.sh`, `scripts/teardown.sh` |
| Cost | **AWS Budgets** | Monthly budget with email alerts, required before `deploy.sh` runs | `scripts/create-budget.sh` |

## Requirements and where they are met

| ID | Requirement | Where |
|---|---|---|
| F1 | Cognito sign-up and log-in; every API call carries a valid JWT | `auth.yaml`; `auth.py` verifies signature (JWKS), issuer, expiry and client; `frontend/src/auth.js` |
| F2 | `POST /scan` stores in S3, creates a job row, queues in SQS, returns `202` | `api/injectshield_api/main.py` (`submit_scan`) |
| F3 | `GET /result/{id}` returns `queued` / `scanning` / `done` / `failed` and the verdict | `main.py` (`get_result`), `worker/injectshield_worker/db.py` |
| F4 | Verdict: risk 0–1, label, three category scores, evidence | `worker/injectshield_worker/scoring.py`, `shared/.../models.py` (`Verdict`) |
| F5 | A user only sees their own jobs | Every query filters on `user_id`; another user's job is a 404 (`tests/test_api.py`) |
| F6 | Web page: paste a prompt, see the verdict and history | `frontend/`, served by `frontend.yaml` |
| N1 | Workers scale out on queue depth and back in when idle | `autoscaling.yaml`; shown with `scripts/load-test.py` |
| N2 | A job failing 3 times goes to the DLQ, never lost silently | `queue.yaml` redrive policy; worker marks the job `failed` on the last attempt; DLQ alarm in `monitoring.yaml`; `tests/test_worker.py` |
| N3 | Encryption at rest; per-service least-privilege roles; no admin ports | SSE-S3, encrypted RDS and SQS; `iam.yaml`; security groups open only 80 on the ALB (Learner Lab: shared `LabRole`, a documented limit) |
| N4 | Dashboard with queue depth, running tasks, latency and errors; alarms | `monitoring.yaml` |
| N5 | Whole stack from CloudFormation, removed by `teardown.sh` | `infra/`, `scripts/`; `tests/test_infra.py` keeps the scripts and templates in step |
| N6 | Budget alert before the first deploy; no NAT gateway | `create-budget.sh` and the budget guard in `deploy.sh`; public subnets with tight security groups instead of NAT |
