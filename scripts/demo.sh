#!/usr/bin/env bash
# Give an account three weeks of simulated history, then send it a nudge right away.
#   scripts/demo.sh you@example.com [persona]      persona: maya (default), sam or jordan
# Sign in once in the app with that email first. The nudge goes to the devices the account has
# registered: in the iOS Simulator it is delivered by the local API with `xcrun simctl push`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EMAIL="${1:?usage: scripts/demo.sh EMAIL [persona]}"
PERSONA="${2:-maya}"

# Keep the account in this Mac's time zone so "evening" means your evening.
TZ_NAME="$(readlink /etc/localtime 2>/dev/null | sed 's#.*zoneinfo/##')"
TZ_ARGS=()
[ -n "$TZ_NAME" ] && TZ_ARGS=(--timezone "$TZ_NAME")

cd "$ROOT/services/api"
uv run brian-dev seed --email "$EMAIL" --persona "$PERSONA" ${TZ_ARGS[@]+"${TZ_ARGS[@]}"}
echo
if ! uv run brian-dev nudge-now --email "$EMAIL"; then
  echo
  echo "History is loaded, but no nudge was sent yet: open the app in the Simulator signed in as"
  echo "$EMAIL and allow notifications so it registers, then run: make nudge EMAIL=$EMAIL"
  exit 0
fi
echo
echo "Pull to refresh in the app. Long-press the notification to see its buttons."
