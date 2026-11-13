#!/usr/bin/env bash
# Start everything Brian needs locally, except the app itself:
#   Supabase (Postgres + Auth + mail inbox, in Docker), the API on :8000 and the background worker.
# Then `make ios` builds the app with Xcode and runs it in the iOS Simulator.
#
# Safe to re-run: it keeps your existing .env settings (e.g. ANTHROPIC_API_KEY) and only refreshes
# the Supabase connection values. Logs and process ids go to .dev/ (git-ignored).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.dev"
API_DIR="$ROOT/services/api"
APP_DIR="$ROOT/apps/mobile"
SUPABASE="${SUPABASE_CLI:-npx --yes supabase@3.1.0}"
API_URL="http://127.0.0.1:8000"
mkdir -p "$RUN"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "Missing $1: $2"
}

# merge_env TARGET UPDATES: set each KEY=value from UPDATES in TARGET, replacing an existing or
# commented-out (# KEY=...) line, appending keys that aren't there. Other lines are kept as they are.
merge_env() {
  local target="$1" updates="$2" tmp
  [ -s "$updates" ] || die "Nothing to write into $target: is Supabase running? (try: $SUPABASE status)"
  tmp="$(mktemp)"
  awk '
    NR == FNR { if (match($0, /^[A-Za-z_][A-Za-z0-9_]*=/)) { key = substr($0, 1, RLENGTH - 1); value[key] = $0 } next }
    {
      line = $0; probe = line; sub(/^#[ \t]*/, "", probe)
      if (match(probe, /^[A-Za-z_][A-Za-z0-9_]*=/)) {
        key = substr(probe, 1, RLENGTH - 1)
        if (key in value) { if (!(key in done)) print value[key]; done[key] = 1; next }
      }
      print line
    }
    END { for (key in value) if (!(key in done)) print value[key] }
  ' "$updates" "$target" > "$tmp"
  mv "$tmp" "$target"
}

start_bg() {  # start_bg NAME COMMAND...  (runs in services/api, where its .env is)
  local name="$1"; shift
  local pidfile="$RUN/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pidfile"))"
    return
  fi
  # A plain backgrounded command (not part of an && list), so $! is the server's own pid, and with
  # all three standard streams redirected it doesn't hold this script's terminal or pipe open.
  (
    cd "$API_DIR"
    nohup "$@" >>"$RUN/$name.log" 2>&1 </dev/null &
    echo $! >"$pidfile"
  )
  echo "$name started (logs: .dev/$name.log)"
}

need docker "install Docker Desktop (https://www.docker.com/products/docker-desktop/) and start it"
need node "install Node.js 22+ (e.g. brew install node)"
need uv "install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
docker info >/dev/null 2>&1 || die "Docker is installed but not running: start Docker Desktop and try again."

say "1/5  Supabase (first run downloads Docker images; this can take a few minutes)"
cd "$ROOT"
$SUPABASE start

say "2/5  Writing services/api/.env and apps/mobile/.env from supabase status"
[ -f "$API_DIR/.env" ] || cp "$API_DIR/.env.example" "$API_DIR/.env"
$SUPABASE status -o env \
  --override-name db.url=DATABASE_URL \
  --override-name api.url=SUPABASE_URL \
  --override-name auth.jwt_secret=SUPABASE_JWT_SECRET \
  --override-name auth.service_role_key=SUPABASE_SERVICE_ROLE_KEY >"$RUN/status.api.env"
grep -E '^(DATABASE_URL|SUPABASE_URL|SUPABASE_JWT_SECRET|SUPABASE_SERVICE_ROLE_KEY)=' "$RUN/status.api.env" \
  >"$RUN/api.env.updates" || true
merge_env "$API_DIR/.env" "$RUN/api.env.updates"

[ -f "$APP_DIR/.env" ] || cp "$APP_DIR/.env.example" "$APP_DIR/.env"
$SUPABASE status -o env \
  --override-name api.url=EXPO_PUBLIC_SUPABASE_URL \
  --override-name auth.anon_key=EXPO_PUBLIC_SUPABASE_ANON_KEY >"$RUN/status.app.env"
grep -E '^EXPO_PUBLIC_SUPABASE_(URL|ANON_KEY)=' "$RUN/status.app.env" >"$RUN/app.env.updates" || true
grep -q '^EXPO_PUBLIC_SUPABASE_ANON_KEY=' "$RUN/app.env.updates" || die "supabase status printed no anon key"
# The iOS Simulator shares the Mac's network, so 127.0.0.1 reaches the API. (A physical phone needs
# the Mac's LAN IP instead.)
echo "EXPO_PUBLIC_API_URL=\"$API_URL\"" >>"$RUN/app.env.updates"
merge_env "$APP_DIR/.env" "$RUN/app.env.updates"
MAILPIT_URL="$($SUPABASE status -o env --override-name mailpit.url=MAILPIT |
  sed -n 's/^MAILPIT="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' || true)"

say "3/5  Backend dependencies"
(cd "$API_DIR" && uv sync --quiet)

say "4/5  API and worker"
start_bg api "$API_DIR/.venv/bin/brian-api"
start_bg worker "$API_DIR/.venv/bin/brian-worker"
ready=""
for _ in $(seq 1 60); do
  if curl -fsS "$API_URL/readyz" >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ -n "$ready" ] || { tail -n 30 "$RUN/api.log" >&2; die "The API did not become ready; see .dev/api.log"; }
echo "API ready at $API_URL (docs: $API_URL/docs)"

say "5/5  App dependencies"
(cd "$APP_DIR" && npm install --no-audit --no-fund --loglevel=error)

if ! grep -qE '^ANTHROPIC_API_KEY=.+' "$API_DIR/.env"; then
  echo
  echo "Note: no ANTHROPIC_API_KEY in services/api/.env, so nudges use templates and the Coach"
  echo "chat is off. Add a key there and run 'make down && make up' to turn Claude on."
fi

cat <<EOF

Everything is running. Next:
  1. make ios                      build with Xcode and open the app in the iOS Simulator
  2. Sign in with any email; the 6-digit code is in the local inbox: ${MAILPIT_URL:-http://127.0.0.1:54324}
     Finish onboarding and allow notifications.
  3. make demo EMAIL=you@example.com
                                   three weeks of simulated history, then a nudge in the Simulator
  make simulate                    synthetic people vs the optimizer (report in the terminal)
  make logs / make down            follow the API and worker logs / stop them
EOF
