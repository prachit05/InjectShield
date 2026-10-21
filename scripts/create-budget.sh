#!/usr/bin/env bash
# Create the monthly AWS Budget with email alerts (requirement N6). Run once,
# before the first deploy, on your own account. Learner Lab accounts have their
# own credit limit and do not allow creating budgets.
#
#   scripts/create-budget.sh you@example.com [monthly-limit-usd, default 5]
set -euo pipefail
source "$(dirname "$0")/common.sh"

EMAIL="${1:?usage: scripts/create-budget.sh you@example.com [monthly-limit-usd]}"
LIMIT="${2:-5}"
NAME="$PROJECT-monthly"

show_identity
account=$(account_id)

if aws_ budgets describe-budget --account-id "$account" --budget-name "$NAME" >/dev/null 2>&1; then
  echo "budget '$NAME' already exists; nothing to do"
  exit 0
fi

subscriber="{\"SubscriptionType\":\"EMAIL\",\"Address\":\"$EMAIL\"}"
aws_ budgets create-budget --account-id "$account" \
  --budget "{\"BudgetName\":\"$NAME\",\"BudgetLimit\":{\"Amount\":\"$LIMIT\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
  --notifications-with-subscribers "[
    {\"Notification\":{\"NotificationType\":\"ACTUAL\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":80,\"ThresholdType\":\"PERCENTAGE\"},\"Subscribers\":[$subscriber]},
    {\"Notification\":{\"NotificationType\":\"FORECASTED\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":100,\"ThresholdType\":\"PERCENTAGE\"},\"Subscribers\":[$subscriber]}
  ]"

echo "created budget '$NAME': \$$LIMIT/month, email to $EMAIL at 80% actual and 100% forecast"
