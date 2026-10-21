# Shared settings for deploy.sh / teardown.sh / create-budget.sh. Source, don't run.
#
# Environment:
#   AWS_PROFILE   CLI profile to use            (default: injectshield)
#   AWS_REGION    region                        (default: the profile's region, else us-east-1)
#   PROJECT       stack/resource name prefix    (default: injectshield)
#   AWS_CLI       path to the aws executable    (default: aws)

PROJECT="${PROJECT:-injectshield}"
PROFILE="${AWS_PROFILE:-injectshield}"
AWS_BIN="${AWS_CLI:-aws}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v "$AWS_BIN" >/dev/null 2>&1; then
  echo "error: aws CLI not found (set AWS_CLI to its path)" >&2
  exit 1
fi

REGION="${AWS_REGION:-$("$AWS_BIN" configure get region --profile "$PROFILE" 2>/dev/null || true)}"
REGION="${REGION:-us-east-1}"

aws_() { "$AWS_BIN" --profile "$PROFILE" --region "$REGION" "$@"; }

stack_name() { echo "$PROJECT-$1"; }

stack_exists() {
  aws_ cloudformation describe-stacks --stack-name "$(stack_name "$1")" >/dev/null 2>&1
}

stack_output() { # stack_output <stack> <OutputKey>
  aws_ cloudformation describe-stacks --stack-name "$(stack_name "$1")" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

account_id() { aws_ sts get-caller-identity --query Account --output text; }

show_identity() {
  local who
  if ! who=$(aws_ sts get-caller-identity --query Arn --output text 2>&1); then
    echo "error: AWS credentials for profile '$PROFILE' are missing or expired:" >&2
    echo "  $who" >&2
    echo "Learner Lab: paste fresh keys from 'AWS Details' into ~/.aws/credentials under [$PROFILE]." >&2
    exit 1
  fi
  echo "account identity: $who"
  echo "region:           $REGION"
  echo "project prefix:   $PROJECT"
}
