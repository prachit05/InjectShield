# InjectShield handoff

Status as of 22 October 2026. Everything below is on the `phases-4-6` branch of
`prachit05/InjectShield` (not merged into `main` yet).

## What InjectShield is

A security checker for AI prompts. An app sends it a user's prompt (and optionally the
AI's saved memory or chat history); it answers `safe`, `suspicious` or `malicious`
with a 0 to 1 risk score, a score for each attack type (prompt injection, memory
injection, jailbreak) and the exact phrases that matched.

The cloud design is the point of the project. The API never does the scanning itself:
it stores the prompt, puts a job on a queue and replies at once with a job ID. Separate
workers take jobs off the queue, and AWS adds workers when the queue gets long and
removes them when it is empty. So the service stays responsive under load, and a job
that keeps failing lands in a dead-letter queue with an alarm instead of vanishing.

```
Browser ─HTTPS─► CloudFront ─┬─► S3 (web page)
                             └─► Load balancer ─► API (ECS Fargate) ─┬─► S3      prompt text
                                     ▲ login token                   ├─► RDS     job row
                                  Cognito                            └─► SQS ─► Workers (ECS Fargate, 1–5) ─► RDS verdict
                                                                          └─ 3 failures ─► DLQ ─► CloudWatch alarm
```

## What was built

The repo already had phases 0 to 3 (detector, API, worker, local Docker setup, base
AWS templates). This branch adds phases 4 to 6 from the design doc:

| Area | Files | What |
|---|---|---|
| AWS infrastructure | `infra/registry.yaml`, `auth.yaml`, `compute.yaml`, `autoscaling.yaml`, `monitoring.yaml`, `frontend.yaml` | Container registry, Cognito login, ECS cluster + load balancer + API and worker services, autoscaling on queue depth, CloudWatch dashboard and 3 alarms, CloudFront for the web app |
| Web app | `frontend/` | Sign up / sign in, paste a prompt, live verdict with evidence, history. Plain HTML/JS, no build step |
| Scripts | `scripts/deploy.sh` (all 11 stacks + image build), `teardown.sh`, `load-test.py`, `create-user.sh`, `token.sh`, `dashboard-images.sh` | One-command deploy and teardown, load testing, report graphs |
| Tests | `tests/test_infra.py` | Templates, deploy order and teardown order stay in step |
| Docs | `docs/deployment.md`, `docs/services-used.md`, `docs/design.md`, this file | Runbook, AWS services and where each requirement is met, design doc |

16 AWS services in total; `docs/services-used.md` lists each one and its job.

## What was tested, and the results

**Locally:** 133 automated tests pass (including real Postgres), lint and CloudFormation
lint are clean, and the detector scores precision 1.00 and recall 1.00 on the 60 sample
prompts. The full stack ran in Docker and in a browser.

**On AWS** (Raj's account, Sydney region `ap-southeast-2`, deployed 21–22 October):

| Requirement | Test | Result |
|---|---|---|
| F1–F6 product | Signed in through Cognito in the web app, scanned prompts, viewed history | ✅ Correct verdicts; no token returns 401 |
| N1 autoscaling | 20,000 prompts in 6.4 minutes through CloudFront | ✅ Backlog peaked near 11,000; workers went 1 → 5; backlog cleared in about 2 minutes; then 5 → 4 → 3 → 2 → 1 when idle |
| N1 throughput | Same run | One worker about 1,300 jobs/min, five workers about 6,800 jobs/min; 19,994 of 20,000 accepted (6 network errors), none failed |
| N2 dead-letter queue | Sent a malformed message to the queue | ✅ Rejected 3 times, moved to the DLQ, `injectshield-dlq-not-empty` alarm went to ALARM |
| N3 security | Encrypted S3/RDS/SQS, one role per service, only port 80 on the load balancer open | ✅ As deployed |
| N4 monitoring | Dashboard and alarms | ✅ Custom metrics, task counts and alarms all live |
| N6 cost | Budget alert, no NAT gateway | ✅ |
| N5 teardown | `scripts/teardown.sh` | ⏳ Not run on AWS yet |

Graphs from the AWS run are in `docs/screenshots/`: `autoscaling.png` (backlog vs
workers, both load tests), `throughput.png`, `latency.png`, `dead-letter-queue.png`.
Under the deliberate flood, jobs waited in the queue for up to about 3 minutes while
the scan itself stayed near 0 ms; that wait is the backlog the autoscaling then clears.

## What is left

1. **Screenshots that need a person:** signing up with a real email (Cognito sends the
   code), the web app, and the CloudWatch dashboard in the console.
2. **Teardown (N5):** run `scripts/teardown.sh` and confirm nothing is left. This takes
   the live site down; `deploy.sh` brings it back in about 15 minutes with a new URL.
3. **Merge** the `phases-4-6` pull request into `main`.
4. **Viva prep:** `docs/services-used.md` maps each requirement to its code.

## How to run it yourself

**Locally (free, no AWS):** needs Python 3.11 and Docker Desktop.

```bash
git clone https://github.com/prachit05/InjectShield && cd InjectShield
git switch phases-4-6
docker compose up --build -d     # then open http://localhost:8080 (login is off locally)
scripts/smoke.sh                 # one prompt end to end
docker compose down              # stop
```

**On AWS:** the live deployment is in Raj's AWS account, so it can only be managed from
his machine or with access he grants. To deploy a separate copy in your own account,
follow `docs/deployment.md`: sign the CLI in with `aws login`, then run `deploy.sh` with
your account's region. Running costs about $0.10 an hour; run `teardown.sh` after every
session.

**With Claude Code:** open the repo folder in Claude Code. It reads `CLAUDE.md`
automatically, which has the commands and the problems already solved. Ask it, for
example, "run the project locally" or "deploy to my AWS account".
