.PHONY: help supabase api worker mobile test check openapi types

help:
	@echo "supabase  start the local Supabase stack (Postgres, Auth, Studio, mail inbox)"
	@echo "api       run the API on :8000"
	@echo "worker    run the background worker"
	@echo "mobile    start the Expo dev server"
	@echo "test      run backend tests (set TEST_DATABASE_URL)"
	@echo "check     lint, format check, type-check backend and mobile"
	@echo "openapi   regenerate services/api/openapi.json"
	@echo "types     regenerate the mobile app's API types from openapi.json"

supabase:
	npx supabase start

api:
	cd services/api && uv run brian-api

worker:
	cd services/api && uv run brian-worker

mobile:
	cd apps/mobile && npx expo start

test:
	cd services/api && uv run pytest

check:
	cd services/api && uv run ruff check src tests scripts && uv run ruff format --check src tests scripts && uv run mypy
	cd apps/mobile && npm run typecheck && npm run lint

openapi:
	cd services/api && uv run python scripts/export_openapi.py

types: openapi
	cd apps/mobile && npm run gen:api
