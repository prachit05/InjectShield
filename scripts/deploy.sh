#!/usr/bin/env bash
# Deploy InjectShield: base stacks, container images, then the app stacks, in dependency order.
#
#   scripts/deploy.sh                                # own AWS account: also creates per-service IAM roles
#   LAB_ROLE_ARN=<LabRole arn> scripts/deploy.sh     # AWS Academy Learner Lab: skip iam.yaml, run as LabRole
#   scripts/deploy.sh base                           # Phase 3 only: network, storage, queue, database, iam
#
# Order: network, storage, queue, database, iam | registry, build + push images |
#        auth, compute, autoscaling, monitoring, frontend (+ upload the web app)
#
# Optional environment:
#   DB_INSTANCE_CLASS   default db.t4g.micro (db.t3.micro if the account rejects Graviton)
#   DB_ENGINE_VERSION   default 16.15
#   ARCH                amd64 (default) or arm64: image platform and Fargate CPU architecture
#   IMAGE_TAG           tag to deploy; with SKIP_BUILD=1 it must already be in ECR
#   SKIP_BUILD=1        reuse IMAGE_TAG instead of building and pushing
#   CLASSIFIER=true     build the worker with the optional classifier (1 vCPU / 2 GB tasks)
#   MIN_WORKERS / MAX_WORKERS / TARGET_QUEUE_DEPTH   autoscaling (default 1 / 5 / 10)
#   ALARM_EMAIL         where CloudWatch alarms are emailed (confirm the SNS email once)
#   SCALING_ROLE_ARN    Learner Lab only, if the autoscaling service-linked role is unavailable
#   SKIP_BUDGET_CHECK=1 deploy without an AWS Budget (not recommended)
# Stacks are idempotent: re-running only applies changes.
set -euo pipefail
source "$(dirname "$0")/common.sh"

TARGET="${1:-all}"
[[ "$TARGET" == "all" || "$TARGET" == "base" ]] || { echo "usage: scripts/deploy.sh [all|base]" >&2; exit 2; }

LAB_ROLE_ARN="${LAB_ROLE_ARN:-}"
ARCH="${ARCH:-amd64}"
CLASSIFIER="${CLASSIFIER:-false}"
case "$ARCH" in
  amd64) CPU_ARCH=X86_64 ;;
  arm64) CPU_ARCH=ARM64 ;;
  *) echo "error: ARCH must be amd64 or arm64" >&2; exit 2 ;;
esac
if [[ "${SKIP_BUILD:-}" == "1" && -z "${IMAGE_TAG:-}" ]]; then
  echo "error: SKIP_BUILD=1 needs IMAGE_TAG (a tag already pushed to ECR)" >&2; exit 2
fi

deploy_stack() { # deploy_stack <name> [Param=Value ...]
  local name=$1; shift
  echo
  echo "==> $(stack_name "$name")  (infra/$name.yaml)"
  # A stack whose first create failed is stuck in ROLLBACK_COMPLETE and cannot be
  # updated; it holds no resources, so delete it and create it again.
  if [[ "$(aws_ cloudformation describe-stacks --stack-name "$(stack_name "$name")" \
        --query 'Stacks[0].StackStatus' --output text 2>/dev/null || true)" == "ROLLBACK_COMPLETE" ]]; then
    echo "    previous create failed; deleting the empty stack first"
    aws_ cloudformation delete-stack --stack-name "$(stack_name "$name")"
    aws_ cloudformation wait stack-delete-complete --stack-name "$(stack_name "$name")"
  fi
  aws_ cloudformation deploy \
    --stack-name "$(stack_name "$name")" \
    --template-file "$ROOT/infra/$name.yaml" \
    --parameter-overrides "ProjectName=$PROJECT" "$@" \
    --capabilities CAPABILITY_NAMED_IAM \
    --tags "Project=$PROJECT" \
    --no-fail-on-empty-changeset
}

check_budget() {
  [[ -n "$LAB_ROLE_ARN" || "${SKIP_BUDGET_CHECK:-}" == "1" ]] && return 0
  local count
  count=$(aws_ budgets describe-budgets --account-id "$(account_id)" --query 'length(Budgets || `[]`)' --output text 2>/dev/null || echo 0)
  if [[ "$count" == "0" || "$count" == "None" ]]; then
    echo "error: no AWS Budget exists in this account (requirement N6: budget alert before the first deploy)." >&2
    echo "  create one:  scripts/create-budget.sh you@example.com 5" >&2
    exit 1
  fi
  echo "budget check:     $count budget(s) found"
}

image_tag() {
  if [[ -n "${IMAGE_TAG:-}" ]]; then echo "$IMAGE_TAG"; return; fi
  local tag
  tag=$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo "build")
  # Uncommitted changes get a unique suffix so ECS always rolls out what was built.
  if [[ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]]; then tag="$tag-dirty-$(date +%Y%m%d%H%M%S)"; fi
  echo "$tag"
}

build_and_push() { # build_and_push <tag>
  local tag=$1 api_repo worker_repo registry
  command -v docker >/dev/null 2>&1 || { echo "error: docker is needed to build the images (or use SKIP_BUILD=1 IMAGE_TAG=...)" >&2; exit 1; }
  api_repo=$(stack_output registry ApiRepositoryUri)
  worker_repo=$(stack_output registry WorkerRepositoryUri)
  registry="${api_repo%%/*}"

  echo
  echo "==> building images for linux/$ARCH, tag $tag"
  aws_ ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  docker build --platform "linux/$ARCH" -f "$ROOT/api/Dockerfile" -t "$api_repo:$tag" "$ROOT"
  docker build --platform "linux/$ARCH" -f "$ROOT/worker/Dockerfile" \
    --build-arg "INSTALL_CLASSIFIER=$CLASSIFIER" -t "$worker_repo:$tag" "$ROOT"
  docker push "$api_repo:$tag"
  docker push "$worker_repo:$tag"
}

upload_frontend() {
  local bucket distribution config
  bucket=$(stack_output storage FrontendBucketName)
  distribution=$(stack_output frontend DistributionId)
  config=$(mktemp)
  cat >"$config" <<EOF
// Generated by scripts/deploy.sh. The API is served from this same origin by CloudFront.
window.INJECTSHIELD_CONFIG = {
  apiBase: "",
  authDisabled: false,
  region: "$REGION",
  userPoolClientId: "$(stack_output auth AppClientId)",
};
EOF
  echo
  echo "==> uploading the web app to s3://$bucket"
  aws_ s3 sync "$ROOT/frontend/" "s3://$bucket/" --delete --exclude config.js --exclude "*.md" \
    --cache-control "no-cache" --only-show-errors
  aws_ s3 cp "$config" "s3://$bucket/config.js" --content-type "application/javascript" \
    --cache-control "no-cache" --only-show-errors
  rm -f "$config"
  aws_ cloudfront create-invalidation --distribution-id "$distribution" --paths "/*" \
    --query Invalidation.Id --output text >/dev/null
}

show_identity
if [[ -n "$LAB_ROLE_ARN" ]]; then
  echo "mode:             Learner Lab (using $LAB_ROLE_ARN, iam.yaml skipped)"
else
  echo "mode:             own account (per-service IAM roles)"
fi
check_budget

# ---------- Phase 3: base infrastructure ----------
deploy_stack network
deploy_stack storage
deploy_stack queue
echo "    (RDS creation takes about 10 minutes on first deploy)"
deploy_stack database \
  "DbInstanceClass=${DB_INSTANCE_CLASS:-db.t4g.micro}" \
  "DbEngineVersion=${DB_ENGINE_VERSION:-16.15}"
if [[ -z "$LAB_ROLE_ARN" ]]; then
  deploy_stack iam
fi

if [[ "$TARGET" == "base" ]]; then
  echo
  echo "==> base stacks deployed."
  echo "prompts bucket: $(stack_output storage PromptsBucketName)"
  echo "scan queue:     $(stack_output queue ScanQueueUrl)"
  echo "database:       $(stack_output database DbEndpoint):$(stack_output database DbPort)"
  echo
  echo "Remember: scripts/teardown.sh at the end of every session."
  exit 0
fi

# ---------- Phase 4: images and services ----------
deploy_stack registry
TAG=$(image_tag)
if [[ "${SKIP_BUILD:-}" == "1" ]]; then
  echo "    skipping build, deploying existing tag $TAG"
else
  build_and_push "$TAG"
fi

if [[ -n "$LAB_ROLE_ARN" ]]; then
  EXEC_ROLE="$LAB_ROLE_ARN"; API_ROLE="$LAB_ROLE_ARN"; WORKER_ROLE="$LAB_ROLE_ARN"
else
  EXEC_ROLE=$(stack_output iam TaskExecutionRoleArn)
  API_ROLE=$(stack_output iam ApiTaskRoleArn)
  WORKER_ROLE=$(stack_output iam WorkerTaskRoleArn)
fi
if [[ "$CLASSIFIER" == "true" ]]; then WORKER_CPU=1024; WORKER_MEMORY=2048; else WORKER_CPU=256; WORKER_MEMORY=512; fi

# ---------- Phase 5: identity, compute, autoscaling ----------
# A brand-new account has no ECS service-linked role until ECS is first used, and
# CloudFormation's CreateCluster fails without it. Create it up front (it already
# exists in Learner Labs and older accounts, so "taken" is fine).
if ! aws_ iam get-role --role-name AWSServiceRoleForECS >/dev/null 2>&1; then
  echo
  echo "==> creating the ECS service-linked role (first ECS use in this account)"
  aws_ iam create-service-linked-role --aws-service-name ecs.amazonaws.com >/dev/null 2>&1 || true
  sleep 15 # new roles take a few seconds to propagate
fi
deploy_stack auth
echo "    (first deploy of the services takes a few minutes while tasks become healthy)"
deploy_stack compute \
  "ImageTag=$TAG" \
  "ExecutionRoleArn=$EXEC_ROLE" \
  "ApiTaskRoleArn=$API_ROLE" \
  "WorkerTaskRoleArn=$WORKER_ROLE" \
  "CpuArchitecture=$CPU_ARCH" \
  "WorkerCpu=$WORKER_CPU" \
  "WorkerMemory=$WORKER_MEMORY" \
  "ClassifierEnabled=$CLASSIFIER"
deploy_stack autoscaling \
  "MinWorkers=${MIN_WORKERS:-1}" \
  "MaxWorkers=${MAX_WORKERS:-5}" \
  "TargetQueueDepth=${TARGET_QUEUE_DEPTH:-10}" \
  "ScalingRoleArn=${SCALING_ROLE_ARN:-}"

# ---------- Phase 6: monitoring and frontend ----------
deploy_stack monitoring "AlarmEmail=${ALARM_EMAIL:-}"
echo "    (a new CloudFront distribution takes 5 to 10 minutes)"
deploy_stack frontend
upload_frontend

echo
echo "==> deployed $TAG. Key outputs:"
echo "web app:        $(stack_output frontend WebUrl)"
echo "api (direct):   $(stack_output compute ApiUrl)"
echo "dashboard:      $(stack_output monitoring DashboardUrl)"
echo "user pool:      $(stack_output auth UserPoolId)   app client: $(stack_output auth AppClientId)"
echo "scan queue:     $(stack_output queue ScanQueueUrl)"
echo "dead letters:   $(stack_output queue DeadLetterQueueUrl)"
echo
echo "Next: sign up in the web app, or scripts/create-user.sh you@example.com, then"
echo "      BASE_URL=$(stack_output frontend WebUrl) TOKEN=\$(scripts/token.sh you@example.com) scripts/smoke.sh"
echo "Remember: scripts/teardown.sh at the end of every session."
