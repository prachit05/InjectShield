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
scripts/deploy.sh                             # refuses to run until a budget exists
```

### AWS Academy Learner Lab

1. Start the lab and wait for the green dot.
2. **AWS Details → AWS CLI: Show**: paste the three lines into `~/.aws/credentials` under `[injectshield]`.
3. Find the LabRole ARN and deploy:

```bash
aws iam get-role --role-name LabRole --profile injectshield --query Role.Arn --output text
LAB_ROLE_ARN=arn:aws:iam::<account-id>:role/LabRole scripts/deploy.sh
```

If RDS rejects `db.t4g.micro`, rerun with `DB_INSTANCE_CLASS=db.t3.micro`.

### Every session ends with

```bash
scripts/teardown.sh          # empties the buckets, deletes stacks newest-first, confirms none are left
```

## Cost while Phase 3 is running (us-east-1, approximate)

| Item | Approx. |
|---|---|
| RDS db.t4g.micro + 20 GB gp3 | ~$0.02 per hour |
| Secrets Manager secret | ~$0.40 per month, prorated |
| S3, SQS, VPC, S3 endpoint | ~$0 at this usage |

No NAT gateway, no interface endpoints, no Multi-AZ. Running `teardown.sh` after
each session keeps the total well under the $5 budget.

## How the scripts were checked before any real deploy

- `cfn-lint` (AWS's template linter, with AWS's resource schemas) passes on every
  template with no errors, warnings or informational findings in us-east-1, us-west-2
  and ap-south-1. CI runs it on every push.
- `deploy.sh`, `teardown.sh` and `create-budget.sh` were run end to end against moto
  (a local AWS simulator). This covered the budget guard, deploying every stack with
  cross-stack imports, idempotent re-runs, Learner Lab mode, emptying non-empty buckets
  and deleting in reverse order. Moto does not implement a few CloudFormation features
  that real AWS does (`Ref` on a secret, VPC delete ordering), so the first real
  deploy should still be watched in the CloudFormation console.
