# Deploying InjectShield to AWS

## Which AWS account

| Account | Works? | Notes |
|---|---|---|
| **AWS Academy Learner Lab** | Yes | Free (lab credits). IAM is read-only, so every task uses the lab's `LabRole` instead of per-service roles (a documented limit on requirement N3). Budgets cannot be created; the lab's credit cap plays that role (N6). Regions: us-east-1 / us-west-2 only. Credentials expire with each lab session. |
| **Own AWS account** | Yes | Meets every requirement as written. Needs a card; with teardown after each session the project costs a few dollars at most. |
| AWS Academy *guided lab* (one exercise, e.g. Storage Gateway) | **No** | Read-only outside that exercise: creating a queue, cluster, user pool or role is denied. |

## Phase 3: base infrastructure

Stacks, in deploy order (each imports outputs of the ones before it):

| Stack | Template | Creates |
|---|---|---|
| `injectshield-network` | `infra/network.yaml` | VPC, 2 public subnets in 2 AZs, internet gateway, free S3 gateway endpoint, security groups ALB → API → RDS and worker → RDS. No NAT gateway. |
| `injectshield-storage` | `infra/storage.yaml` | Prompts bucket (SSE-S3, public access blocked, TLS-only, prompts expire after 7 days), frontend bucket. |
| `injectshield-queue` | `infra/queue.yaml` | Scan queue (long polling, 60 s visibility) and DLQ after 3 receives. Both encrypted. |
| `injectshield-database` | `infra/database.yaml` | RDS Postgres 16.15 on db.t4g.micro, encrypted, not publicly accessible, password generated into Secrets Manager. |
| `injectshield-iam` | `infra/iam.yaml` | ECS execution role, API task role (S3 put + SQS send), worker task role (S3 get + SQS receive/delete). Each is scoped to the exact ARNs of the resources above, which is why IAM deploys last. Skipped in Learner Lab. |

The schema (`db/init.sql`) is applied by the API at startup (`RUN_MIGRATIONS=true`),
so RDS never has to be opened to the internet.

### Own account

```bash
aws login --profile injectshield              # browser sign-in; or `aws configure --profile injectshield`
aws configure set region us-east-1 --profile injectshield
scripts/create-budget.sh you@example.com 5   # once, before anything else (N6)
scripts/deploy.sh base                        # Phase 3 stacks only; refuses to run until a budget exists
```

### AWS Academy Learner Lab

1. Start the lab and wait for the green dot.
2. **AWS Details → AWS CLI: Show**: paste the three lines into `~/.aws/credentials` under `[injectshield]`.
3. Find the LabRole ARN and deploy:

```bash
aws iam get-role --role-name LabRole --profile injectshield --query Role.Arn --output text
LAB_ROLE_ARN=arn:aws:iam::<account-id>:role/LabRole scripts/deploy.sh base
```

If RDS rejects `db.t4g.micro`, rerun with `DB_INSTANCE_CLASS=db.t3.micro`.

## Phases 4 to 6: the whole service

`scripts/deploy.sh` with no argument deploys everything: the base stacks above, then

| Stack | Template | Creates |
|---|---|---|
| `injectshield-registry` | `infra/registry.yaml` | ECR repositories `injectshield/api` and `injectshield/worker` (scan on push, last 5 images kept, emptied on delete). |
| (images) | `api/Dockerfile`, `worker/Dockerfile` | `deploy.sh` builds both for `linux/amd64` and pushes them, tagged with the git commit. |
| `injectshield-auth` | `infra/auth.yaml` | Cognito user pool (email sign-in, verified by code) and a public web client. |
| `injectshield-compute` | `infra/compute.yaml` | ECS cluster (Container Insights on), internet-facing ALB, API service (1 task behind the ALB, health check `/health`) and worker service (no inbound traffic). 0.25 vCPU / 0.5 GB tasks, logs to CloudWatch for 7 days, DB credentials injected from Secrets Manager, circuit-breaker rollback on bad deploys. |
| `injectshield-autoscaling` | `infra/autoscaling.yaml` | Worker target tracking on `ApproximateNumberOfMessagesVisible` (target 10), 1 to 5 tasks. |
| `injectshield-monitoring` | `infra/monitoring.yaml` | Dashboard `injectshield`; alarms on DLQ not empty, scan errors and API 5xx, sent to an SNS topic. |
| `injectshield-frontend` | `infra/frontend.yaml` | CloudFront distribution: the web app from the private frontend bucket (origin access control), and `/scan`, `/result/*`, `/jobs`, `/health` forwarded to the ALB uncached. |

Docker Desktop must be running. On an Apple-silicon Mac the amd64 build runs under
emulation and takes a few minutes the first time; `ARCH=arm64 scripts/deploy.sh`
builds natively and runs the tasks on Graviton instead (also cheaper).

A first deploy takes about 25 minutes (RDS about 10, CloudFront about 5 to 10). Re-runs
only change what changed; a code change rebuilds the images and rolls the services.

Useful options (all environment variables):

| Variable | Effect |
|---|---|
| `ALARM_EMAIL=you@example.com` | Alarm emails (confirm the SNS subscription email once) |
| `MIN_WORKERS`, `MAX_WORKERS`, `TARGET_QUEUE_DEPTH` | Autoscaling bounds and target (default 1, 5, 10) |
| `ARCH=arm64` | Build arm64 images and run on Graviton Fargate |
| `CLASSIFIER=true` | Build the worker with the optional classifier; tasks get 1 vCPU / 2 GB |
| `SKIP_BUILD=1 IMAGE_TAG=<tag>` | Redeploy an image already in ECR without Docker |
| `SCALING_ROLE_ARN=<LabRole arn>` | Learner Lab only, if autoscaling cannot create its service-linked role |

### Why the frontend goes through CloudFront

The ALB only listens on HTTP (no domain, so no certificate). A page served over HTTPS
cannot call an HTTP API, so CloudFront fronts both: the page and the API share one HTTPS
origin, which also removes any need for CORS. The API is still reachable directly at the
ALB URL that `deploy.sh` prints, for curl and the load test.

The web app talks to Cognito directly (`SignUp`, `ConfirmSignUp`, `InitiateAuth`), so the
user pool needs no callback URLs and the `auth` stack does not depend on the CloudFront
domain.

## Demo flow

```bash
# 1. a user: sign up in the web app (verification code by email), or skip the email:
scripts/create-user.sh you@example.com

# 2. the web app: open the "web app" URL deploy.sh printed, sign in, try the examples

# 3. smoke test through CloudFront
export BASE_URL=https://<distribution>.cloudfront.net
export TOKEN=$(scripts/token.sh you@example.com)
scripts/smoke.sh

# 4. autoscaling: 500 jobs, then watch the dashboard (queue depth, running tasks)
python3 scripts/load-test.py --count 500
```

Scale-out needs three consecutive one-minute SQS datapoints above the target, so it
starts about 4 to 5 minutes after the backlog appears. One worker clears about 1,100
jobs a minute, so the backlog has to outlast that delay: 500 jobs are gone before the
alarm fires. Submit about 20,000 (`--count 20000 --concurrency 40 --no-wait`, roughly
6 minutes at 55 submissions a second) to see the workers scale out while the backlog
is still high. Scale-in waits for 15 minutes of low queue depth (target tracking is
deliberately slow to remove capacity), then goes back to `MIN_WORKERS`.

Afterwards, `scripts/dashboard-images.sh` saves the key graphs (backlog vs workers,
throughput, latency, dead-letter queue) as PNGs in `docs/screenshots/`.

To demonstrate the DLQ, send a malformed message straight to the queue; it fails three
times, lands in the DLQ and the `injectshield-dlq-not-empty` alarm fires:

```bash
aws sqs send-message --profile injectshield --queue-url <scan queue url> --message-body '{"not":"a job"}'
```

### Every session ends with

```bash
scripts/teardown.sh          # empties the buckets, deletes stacks newest-first, confirms none are left
```

Deleting the CloudFront distribution takes 5 to 15 minutes; the script waits for it.

## Cost while the whole stack is running (us-east-1, approximate)

| Item | Approx. per hour |
|---|---|
| RDS db.t4g.micro + 20 GB gp3 | $0.02 |
| ALB (hour + minimal LCU) | $0.025 |
| Fargate: 1 API + 1 worker task, 0.25 vCPU / 0.5 GB each | $0.025 (each extra worker about $0.012) |
| Public IPv4 addresses (2 for the ALB, 1 per task) | $0.02 |
| Container Insights, CloudWatch dashboard and alarms | under $0.01 |
| Secrets Manager secret | ~$0.40 per month, prorated |
| Cognito, CloudFront, ECR, S3, SQS, VPC, S3 endpoint | ~$0 at this usage |

About **$0.10 per hour**, a little more while the load test scales the workers out.
A two-hour session costs around $0.20; leaving everything up for a month would cost
about $70, which is why `teardown.sh` ends every session and the $5 budget alerts early.
No NAT gateway, no interface endpoints, no Multi-AZ.

## How the scripts were checked before any real deploy

- `cfn-lint` (AWS's template linter, with AWS's resource schemas) passes on every
  template with no errors, warnings or informational findings in us-east-1, us-west-2
  and ap-south-1. CI runs it on every push.
- The Phase 3 scripts were run end to end against moto (a local AWS simulator). This
  covered the budget guard, deploying every stack with cross-stack imports, idempotent
  re-runs, Learner Lab mode, emptying non-empty buckets and deleting in reverse order.
- The Phase 4 to 6 additions to `deploy.sh` and `teardown.sh` were dry-run under macOS's
  bash 3.2 against a stub `aws` and `docker` that record every call: own-account,
  Learner Lab, `base`, `ARCH=arm64` and `SKIP_BUILD` modes, stack order, parameters and
  the generated `config.js`. `tests/test_infra.py` checks that every template is
  deployed, torn down in reverse order, and that the retry count matches across the
  queue, the task definition and the worker.
- The application path (API, two workers, Postgres, S3 and SQS via moto server, the web
  app in headless Chrome, `smoke.sh`, `load-test.py`) was run end to end locally.

Moto and the stubs do not cover everything real AWS does (ECS rollouts, CloudFront,
Cognito email, autoscaling alarms), so watch the first real deploy in the
CloudFormation console; a failed stack shows the reason under its Events tab.
