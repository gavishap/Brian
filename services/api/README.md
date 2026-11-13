# Brian API and worker

One Python package, two processes:

* `brian-api`: FastAPI app (REST + server-sent events for chat). Docs at `/docs` when running.
* `brian-worker`: APScheduler process that plans, sends, finalizes and reflects on nudges.

```bash
uv sync
cp .env.example .env
uv run brian-api        # :8000
uv run brian-worker
```

## Modules (`src/brian/`)

| Module | What it does |
|---|---|
| `config.py` | All settings (environment variables) |
| `auth.py` | Verifies Supabase access tokens; `CurrentProfile` dependency |
| `models.py` | SQLAlchemy models mirroring `supabase/migrations` |
| `schemas.py` | API request/response models (the OpenAPI contract) |
| `goals.py`, `progress.py` | Goal domain logic, periods and streaks |
| `agent/` | Coach agent: `prompts.py`, `tools.py` (typed tools via `beta_async_tool`), `coach.py` (streaming tool-runner loop with append-only history), `llm.py` (client, fallbacks) |
| `nudges/arms.py` | The decision space and eligibility rules |
| `nudges/policy.py` | Thompson sampling with population priors, decay and propensities |
| `nudges/planner.py` | Picks goal, time and style for the next nudge |
| `nudges/copywriter.py`, `templates.py` | Claude-written copy with template fallback |
| `nudges/dispatcher.py`, `push.py` | Claims due nudges, sends via Expo, receipts, expiry |
| `nudges/outcomes.py`, `rewards.py`, `stats_store.py` | Events → outcomes → rewards → policy statistics |
| `insights/` | Engagement analytics and the weekly Claude reflection (playbook) |
| `jobs.py`, `worker.py` | Scheduled jobs; `POST /internal/tick` runs them on demand |

## Tests

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run pytest
```

Each run creates a fresh database, applies `tests/sql/supabase_auth_shim.sql` (a stand-in for
Supabase's `auth` schema) and the real migrations, and drops it afterwards.

After changing anything in `schemas.py` or the routers: `uv run python scripts/export_openapi.py`
(CI checks `openapi.json` is current), then `npm run gen:api` in `apps/mobile`.
