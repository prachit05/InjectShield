#!/usr/bin/env bash
# Print a Cognito ID token for an existing user, for curl, smoke.sh and load-test.py.
#
#   TOKEN=$(scripts/token.sh you@example.com)        # prompts for the password on stderr
#   INJECTSHIELD_PASSWORD=... scripts/token.sh you@example.com
set -euo pipefail
source "$(dirname "$0")/common.sh"

EMAIL="${1:?usage: scripts/token.sh you@example.com}"
PASSWORD="${INJECTSHIELD_PASSWORD:-}"
if [[ -z "$PASSWORD" ]]; then
  read -r -s -p "Password for $EMAIL: " PASSWORD </dev/tty
  echo >&2
fi

CLIENT=$(stack_output auth AppClientId)
[[ -n "$CLIENT" && "$CLIENT" != "None" ]] || { echo "error: $PROJECT-auth stack not found; deploy first" >&2; exit 1; }

# JSON, not shorthand, so passwords containing commas or '=' survive.
params=$(USERNAME="$EMAIL" PASSWORD="$PASSWORD" python3 -c \
  'import json, os; print(json.dumps({"USERNAME": os.environ["USERNAME"], "PASSWORD": os.environ["PASSWORD"]}))')

# InitiateAuth needs no AWS credentials; the CLI call just reuses the region.
aws_ cognito-idp initiate-auth --client-id "$CLIENT" --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters "$params" \
  --query AuthenticationResult.IdToken --output text
