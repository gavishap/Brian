.PHONY: help up down down-all logs demo supabase api worker mobile ios seed nudge simulate test check openapi types

help:
	@echo "up        start Supabase (Docker), write .env files, run the API + worker in the background"
	@echo "down      stop the API + worker (down-all: also stop Supabase)"
	@echo "logs      follow the API and worker logs"
	@echo "demo      EMAIL=you@example.com [PERSONA=maya]: simulated history + a nudge right now"
	@echo "supabase  start the local Supabase stack (Postgres, Auth, Studio, mail inbox)"
	@echo "api       run the API on :8000"
	@echo "worker    run the background worker"
	@echo "mobile    start the Expo dev server"
	@echo "ios       build with Xcode and run in the iOS Simulator (macOS)"
	@echo "seed      EMAIL=you@example.com [PERSONA=maya]: fill an account with simulated history"
	@echo "nudge     EMAIL=you@example.com: send a nudge right now (e.g. to the Simulator)"
	@echo "simulate  run synthetic personas through the engine and report what it learned"
	@echo "test      run backend tests (set TEST_DATABASE_URL)"
	@echo "check     lint, format check, type-check backend and mobile"
	@echo "openapi   regenerate services/api/openapi.json"
	@echo "types     regenerate the mobile app's API types from openapi.json"

up:
	./scripts/dev-up.sh

down:
	./scripts/dev-down.sh

down-all:
	./scripts/dev-down.sh --supabase

logs:
	tail -f .dev/api.log .dev/worker.log

demo:
	./scripts/demo.sh $(EMAIL) $(or $(PERSONA),maya)

supabase:
	npx supabase start

api:
	cd services/api && uv run brian-api

worker:
	cd services/api && uv run brian-worker

mobile:
	cd apps/mobile && npx expo start

ios:
	cd apps/mobile && npm run ios

seed:
	cd services/api && uv run brian-dev seed --email $(EMAIL) --persona $(or $(PERSONA),maya)

nudge:
	cd services/api && uv run brian-dev nudge-now --email $(EMAIL)

simulate:
	cd services/api && uv run brian-dev simulate

test:
	cd services/api && uv run pytest

check:
	cd services/api && uv run ruff check src tests scripts && uv run ruff format --check src tests scripts && uv run mypy
	cd apps/mobile && npm run typecheck && npm run lint

openapi:
	cd services/api && uv run python scripts/export_openapi.py

types: openapi
	cd apps/mobile && npm run gen:api
