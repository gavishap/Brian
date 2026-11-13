#!/usr/bin/env bash
# Stop the API and worker started by dev-up.sh. With --supabase, also stop the Supabase containers
# (the database is kept in Docker volumes; `make up` brings it back).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.dev"
SUPABASE="${SUPABASE_CLI:-npx --yes supabase@3.1.0}"

for name in worker api; do
  pidfile="$RUN/$name.pid"
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      echo "$name stopped"
    fi
    rm -f "$pidfile"
  fi
done

if [ "${1:-}" = "--supabase" ]; then
  (cd "$ROOT" && $SUPABASE stop)
fi
