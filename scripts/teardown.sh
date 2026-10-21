#!/usr/bin/env bash
# Delete every InjectShield stack, newest layer first, so nothing keeps billing.
#
#   scripts/teardown.sh          # asks for confirmation
#   scripts/teardown.sh --yes    # no prompt
#
# Buckets are emptied first (CloudFormation cannot delete a non-empty bucket).
# Stacks that do not exist are skipped, so it is safe to run at any time.
set -euo pipefail
source "$(dirname "$0")/common.sh"

# Reverse of the deploy order, including later phases' stacks.
STACKS=(monitoring autoscaling compute auth iam database queue storage network)

show_identity
existing=()
for s in "${STACKS[@]}"; do
  if stack_exists "$s"; then existing+=("$s"); fi
done
if [[ ${#existing[@]} -eq 0 ]]; then
  echo "nothing to delete: no $PROJECT-* stacks in $REGION"
  exit 0
fi
echo "will delete: ${existing[*]/#/$PROJECT-}"

if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "Type 'delete' to continue: " answer
  [[ "$answer" == "delete" ]] || { echo "aborted"; exit 1; }
fi

empty_bucket() {
  local bucket=$1
  [[ -z "$bucket" || "$bucket" == "None" ]] && return 0
  if aws_ s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    echo "    emptying s3://$bucket"
    aws_ s3 rm "s3://$bucket" --recursive --only-show-errors
  fi
}

delete_stack() {
  local name; name=$(stack_name "$1")
  echo
  echo "==> deleting $name"
  aws_ cloudformation delete-stack --stack-name "$name"
  if ! aws_ cloudformation wait stack-delete-complete --stack-name "$name"; then
    echo "error: $name failed to delete. Reasons:" >&2
    aws_ cloudformation describe-stack-events --stack-name "$name" \
      --query "StackEvents[?ResourceStatus=='DELETE_FAILED'].[LogicalResourceId,ResourceStatusReason]" \
      --output text >&2 || true
    exit 1
  fi
  echo "    deleted"
}

for s in "${existing[@]}"; do
  if [[ "$s" == "storage" ]]; then
    empty_bucket "$(stack_output storage PromptsBucketName)"
    empty_bucket "$(stack_output storage FrontendBucketName)"
  fi
  delete_stack "$s"
done

left=$(aws_ cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE ROLLBACK_COMPLETE DELETE_FAILED \
  --query "StackSummaries[?starts_with(StackName, '$PROJECT-')].StackName" --output text)
echo
if [[ -n "$left" ]]; then
  echo "warning: stacks still present: $left" >&2
  exit 1
fi
echo "teardown complete: no $PROJECT-* stacks left in $REGION"
