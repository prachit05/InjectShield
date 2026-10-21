#!/usr/bin/env bash
# Create a confirmed Cognito user without the email round trip (demo and load tests).
# Anyone can also sign up in the web app; this is only a shortcut for the stack owner.
#
#   scripts/create-user.sh you@example.com            # prompts for the password
#   INJECTSHIELD_PASSWORD=... scripts/create-user.sh you@example.com
set -euo pipefail
source "$(dirname "$0")/common.sh"

EMAIL="${1:?usage: scripts/create-user.sh you@example.com}"
PASSWORD="${INJECTSHIELD_PASSWORD:-}"
if [[ -z "$PASSWORD" ]]; then
  read -r -s -p "Password for $EMAIL (8+ chars, upper, lower, number): " PASSWORD
  echo
fi

POOL=$(stack_output auth UserPoolId)
[[ -n "$POOL" && "$POOL" != "None" ]] || { echo "error: $PROJECT-auth stack not found; deploy first" >&2; exit 1; }

if aws_ cognito-idp admin-get-user --user-pool-id "$POOL" --username "$EMAIL" >/dev/null 2>&1; then
  echo "user exists; setting the password"
else
  aws_ cognito-idp admin-create-user --user-pool-id "$POOL" --username "$EMAIL" \
    --user-attributes "Name=email,Value=$EMAIL" "Name=email_verified,Value=true" \
    --message-action SUPPRESS >/dev/null
fi
aws_ cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$EMAIL" \
  --password "$PASSWORD" --permanent
echo "user $EMAIL is ready in $POOL"
