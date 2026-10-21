# InjectShield: notes for Claude Code

Guardrail-as-a-service on AWS (Cloud Computing 702IT0C026 mini project, team: Raj Singh
and Prachi). A prompt goes in; a risk verdict for prompt injection, memory injection and
jailbreak comes out. Start with `docs/handoff.md` for what has been done and what is
left; `docs/design.md` is the design doc; `docs/deployment.md` is the AWS runbook.

## Architecture in one paragraph

The API (FastAPI, `api/`) never scans inline: `POST /scan` stores the prompt in S3,
inserts a `jobs` row in Postgres, sends `{job_id, s3_key}` to SQS and returns `202`.
Workers (`worker/`) long-poll SQS, scan with regex detectors, write `verdicts` and delete
the message only after the commit. 3 failed receives move a message to the DLQ.
`shared/` holds the Pydantic models and settings both use. `frontend/` is a static page
(no build step) that talks to Cognito directly and to the API through CloudFront.

## Commands

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                                   # 133 tests; set TEST_DATABASE_URL to run the 8 Postgres ones
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/cfn-lint --regions us-east-1 us-west-2 ap-south-1 --include-checks I -- infra/*.yaml
PYTHONPATH=shared:worker .venv/bin/python -m injectshield_worker.evaluate tests/sample_prompts
docker compose up --build -d                       # local stack: web app :8080, API :8000 (auth off)
scripts/smoke.sh && python3 scripts/load-test.py --count 100
```

AWS (see `docs/deployment.md`; never deploy without the user's go-ahead, it costs money):

```bash
aws login --profile injectshield --region <region>  # browser sign-in, no stored keys
AWS_PROFILE=injectshield AWS_REGION=<region> ARCH=arm64 scripts/deploy.sh
AWS_PROFILE=injectshield AWS_REGION=<region> scripts/teardown.sh   # end of every session
```

## Rules for changes

- Every `infra/*.yaml` must be deployed by `scripts/deploy.sh` and deleted by
  `scripts/teardown.sh` in reverse order; `tests/test_infra.py` enforces it.
- The retry count is 3 in three places (queue.yaml, compute.yaml task env, worker
  settings); keep them equal.
- Never log prompt bodies. Every DB query is scoped to the caller's `user_id`.
- Scripts must run on macOS's bash 3.2 with `set -u`: expand possibly-empty arrays as
  `${A[@]+"${A[@]}"}`, and test with `/bin/bash`.
- The frontend has a strict CSP (no inline scripts or styles; set styles through the
  DOM, not `style=""` attributes).

## Things learned the hard way (deploying to a brand-new AWS account)

- AWS "Free plan" accounts are locked to one region (for Raj's account,
  `ap-southeast-2`); `scripts/common.sh` defaults to us-east-1, so always pass
  `AWS_REGION`. The plan allows every service used here.
- In zsh, `P="--profile x"; aws $P ...` passes one argument. Use `AWS_PROFILE=...`.
- A new account has no ECS service-linked role, so the first CreateCluster fails;
  `deploy.sh` now creates the role first and deletes stacks stuck in ROLLBACK_COMPLETE.
- Apple-silicon Mac: deploy with `ARCH=arm64` (native build, Graviton Fargate).
- Autoscaling reacts 4 to 5 minutes after a backlog appears (three one-minute SQS
  datapoints). One worker clears about 1,300 jobs a minute, so the demo needs about
  20,000 jobs (`load-test.py --count 20000 --concurrency 40 --no-wait`) to show the
  scale-out while the backlog is still high.
- Pushing changes under `.github/workflows/` needs a GitHub token with `workflow` scope.
- `scripts/dashboard-images.sh` renders the dashboard graphs to `docs/screenshots/`.
