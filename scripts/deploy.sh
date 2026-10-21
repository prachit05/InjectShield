#!/usr/bin/env bash
# Deploy the InjectShield stacks in dependency order.
#
#   scripts/deploy.sh                       # own AWS account: also creates per-service IAM roles
#   LAB_ROLE_ARN=<LabRole arn> scripts/deploy.sh    # AWS Academy Learner Lab: skip iam.yaml
#
# Optional: DB_INSTANCE_CLASS (default db.t4g.micro), DB_ENGINE_VERSION (default 16.15),
#           SKIP_BUDGET_CHECK=1 to deploy without an AWS Budget (not recommended).
# Stacks are idempotent: re-running only applies changes.
set -euo pipefail
source "$(dirname "$0")/common.sh"

LAB_ROLE_ARN="${LAB_ROLE_ARN:-}"

deploy_stack() { # deploy_stack <name> [Param=Value ...]
  local name=$1; shift
  echo
  echo "==> $(stack_name "$name")  (infra/$name.yaml)"
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

show_identity
if [[ -n "$LAB_ROLE_ARN" ]]; then
  echo "mode:             Learner Lab (using $LAB_ROLE_ARN, iam.yaml skipped)"
else
  echo "mode:             own account (per-service IAM roles)"
fi
check_budget

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

echo
echo "==> deployed. Key outputs:"
echo "prompts bucket: $(stack_output storage PromptsBucketName)"
echo "scan queue:     $(stack_output queue ScanQueueUrl)"
echo "dead letters:   $(stack_output queue DeadLetterQueueUrl)"
echo "database:       $(stack_output database DbEndpoint):$(stack_output database DbPort)"
if [[ -z "$LAB_ROLE_ARN" ]]; then
  echo "api role:       $(stack_output iam ApiTaskRoleArn)"
  echo "worker role:    $(stack_output iam WorkerTaskRoleArn)"
fi
echo
echo "Remember: scripts/teardown.sh at the end of every session."
