# Brian

Brian is a proactive AI coach for long-term goals, as an iOS and Android app. You tell it what
you're working toward; it helps make the goal concrete, checks in through push notifications,
and learns from how you respond (acted, replied, opened, dismissed or ignored) **when** to nudge
you, **how** to nudge you, and **which words** work, using a bandit policy over timing and style,
Claude for the writing, and a weekly reflection that turns your data into a written playbook.

* **Mobile**: Expo SDK 58 (React Native, Expo Router, TypeScript): `apps/mobile`
* **Backend**: Python 3.13, FastAPI, SQLAlchemy, APScheduler: `services/api`
* **Auth + database**: Supabase (Auth, Postgres with row-level security): `supabase/`
* **AI**: Claude (`claude-opus-5-5`) through the Anthropic Python SDK's tool runner and structured outputs
* **Push**: Expo push service (APNs + FCM)

```mermaid
flowchart LR
    App[Expo app] -- REST + SSE --> API[FastAPI]
    App -- sign in --> Auth[Supabase Auth]
    API --> DB[(Supabase Postgres)]
    Worker[Worker: plan · send · learn] --> DB
    API -- coach agent --> Claude
    Worker -- copy · reflection --> Claude
    Worker -- push --> Expo[Expo push] --> App
```

## How it works

1. **Coach chat.** A Claude agent with tools over your data (create and update goals, log
   check-ins, add milestones, read progress and nudge insights, change nudge settings, schedule a
   reminder, remember facts). Replies stream to the app as server-sent events.
2. **Proactive nudges.** Every few minutes the worker plans the next nudge per user: which goal,
   which time window, and which type, tone, framing and length, chosen by Thompson sampling with
   population priors, inside your quiet hours and a fatigue-aware daily budget.
3. **Personalised copy.** Just before sending, Claude writes the notification in that style,
   grounded in your goal, your reason for it, your progress and what has worked before.
4. **Feedback.** The app reports reactions, including action buttons on the notification
   (Done ✅ / Later / Reply / Less of these). Outcomes become rewards that update the policy; a
   "Done" tap also logs the check-in.
5. **Reflection.** Weekly, Claude reviews your engagement data and writes a playbook (what works,
   what to avoid, phrasing guidelines, experiments) that steers future copy and appears in the
   Insights tab.

Every decision is logged with its probability and context, so new policies can be evaluated
offline before they ship. Details: [docs/nudge-engine.md](docs/nudge-engine.md) ·
[docs/architecture.md](docs/architecture.md).

## Repository layout

```
apps/mobile/            Expo app (see apps/mobile/README.md)
services/api/           FastAPI API + background worker (one Docker image)
  src/brian/agent/        coach agent: prompt, tools, streaming chat loop, Claude client
  src/brian/nudges/       arms, Thompson-sampling policy, planner, copywriter, push, outcomes
  src/brian/insights/     engagement analytics and weekly reflection
  src/brian/routers/      HTTP endpoints
  openapi.json            API contract (generated; the app's types are generated from it)
  tests/                  pytest suite against a real Postgres
supabase/               Supabase config, SQL migrations (schema source of truth), email template
docs/                   architecture and nudge-engine design
.github/workflows/      CI (lint, types, tests) and manual EAS builds
```

## Local development

Prerequisites: Node 22+, [uv](https://docs.astral.sh/uv/), Docker (for the local Supabase stack),
and for device testing Xcode and/or Android Studio, or a phone with a development build.

```bash
# 1. Supabase: Postgres + Auth + Studio + a local inbox for sign-in codes (http://127.0.0.1:54324)
npx supabase start
```

```bash
# 2. Backend
cd services/api
cp .env.example .env        # add ANTHROPIC_API_KEY to enable the coach and AI copy
uv sync
uv run brian-api            # http://127.0.0.1:8000/docs
```

```bash
# 3. Worker (in another terminal): plans, sends and learns from nudges
cd services/api && uv run brian-worker
```

```bash
# 4. Mobile app
cd apps/mobile
cp .env.example .env        # API URL and Supabase URL/anon key (`npx supabase status` prints them)
npm install
npx expo start
```

On a physical phone, point `EXPO_PUBLIC_API_URL` and `EXPO_PUBLIC_SUPABASE_URL` at your
computer's LAN IP instead of 127.0.0.1. Push notifications with action buttons need a development
build on a real device (`npx expo run:ios` / `npx expo run:android`, or `eas build --profile
development`); everything else works in a simulator. `PUSH_DRY_RUN=true` logs pushes instead of
sending them.

`docker compose up --build` runs the API and worker in containers against the local Supabase
stack instead of steps 2-3.

### iOS Simulator (Xcode) with realistic data

On a Mac with Xcode: `cd apps/mobile && npm run ios` builds the app with Xcode and launches it in
the Simulator. Then fill your account with three weeks of simulated history and send yourself a
nudge, which a local backend delivers straight into the Simulator (`xcrun simctl push`):

```bash
cd services/api && uv run brian-dev seed --email you@example.com --persona maya
```

```bash
cd services/api && uv run brian-dev nudge-now --email you@example.com
```

Step by step: [apps/mobile/README.md](apps/mobile/README.md#run-it-in-the-ios-simulator-with-xcode).

### Simulating the engine

`brian-dev simulate` runs synthetic people with hidden preferences (timing, tone, framing, type,
length) through the real planner, dispatcher, event ingestion and learning code on a simulated
clock, and compares the learning policy with a random one. A 28-day run:

| Person | Learning policy engaged | Random policy engaged | Learned best timing |
|---|---|---|---|
| Maya (night owl) | 77% | 54% | evening (truth: evening, night) |
| Sam (early bird) | 71% | 36% | morning (truth: early morning, morning) |
| Jordan (busy parent) | 62% | 31% | midday (truth: midday, afternoon) |

```bash
cd services/api && uv run brian-dev simulate --days 28
```

Details and how to read the report: [docs/nudge-engine.md](docs/nudge-engine.md#9-simulation).

## Tests and checks

```bash
cd services/api
# Any Postgres 15+ you can create databases on; the Supabase CLI's works:
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run pytest
uv run ruff check src tests scripts && uv run ruff format --check src tests scripts && uv run mypy
```

The suite applies the real migrations to a fresh database and covers the API, the full nudge loop
(plan → send → react → learn), schema drift, and the coach agent driven through the real SDK tool
runner against a mocked Claude transport (request shape, tool execution, byte-identical history
replay). After changing API models, regenerate the contract and the app's types:

```bash
cd services/api && uv run python scripts/export_openapi.py
```

```bash
cd apps/mobile && npm run gen:api && npm run typecheck && npm run lint && npm test
```

## Deploying

1. **Supabase**: create a project, then `npx supabase link --project-ref <ref>` and
   `npx supabase db push`. In the dashboard set the Auth site URL / redirect URLs to `brian://`,
   paste `supabase/templates/magic_link.html` into the Magic Link email template (so emails
   contain the 6-digit code), and configure SMTP for production email.
2. **Backend**: build `services/api/Dockerfile` and run two processes from it: `brian-api`
   (HTTP, port 8000 or `$PORT`) and `brian-worker`. `services/api/fly.toml` does this on Fly.io.
   Set `DATABASE_URL`, `SUPABASE_URL`, `ANTHROPIC_API_KEY`, and optionally
   `SUPABASE_SERVICE_ROLE_KEY` (full account deletion) and `EXPO_ACCESS_TOKEN`.
3. **Mobile**: replace the placeholder bundle id `com.example.brian` in `apps/mobile/app.config.ts`,
   run `npx eas-cli init`, set up push credentials (`eas credentials`: APNs key for iOS, FCM V1
   service account for Android), then `eas build` and `eas submit`, or run the *EAS build* GitHub
   workflow (needs the `EXPO_TOKEN` secret).

## Configuration

Backend settings are environment variables (see `services/api/.env.example` and
`services/api/src/brian/config.py`). The most important knobs:

| Variable | Default | Purpose |
|---|---|---|
| `COACH_MODEL` / `COPY_MODEL` / `REFLECTION_MODEL` | `claude-opus-5-5` | Model per job |
| `COACH_EFFORT` / `COPY_EFFORT` / `REFLECTION_EFFORT` | `medium` / `low` / `high` | Thinking effort per job (cost vs quality) |
| `LLM_REFUSAL_FALLBACKS` | `true` | Server-side fallback when a request is declined |
| `POLICY_PRIOR_STRENGTH` | `4` | How many pseudo-observations a new user borrows from the population |
| `POLICY_EPSILON` | `0.1` | Minimum exploration |
| `POLICY_USER_HALF_LIFE_DAYS` | `45` | How fast old evidence fades |
| `NUDGE_ATTRIBUTION_HOURS` | `3` | Window in which a reaction counts for a nudge |
| `NUDGE_MIN_GAP_MINUTES` | `150` | Minimum time between nudges |
| `CHAT_DAILY_MESSAGE_LIMIT` | `200` | Per-user cost guard |

## Next steps

* Sign in with Apple and Google (Supabase providers + `expo-apple-authentication` /
  Google Sign-In); Apple requires Sign in with Apple once any other social login is offered.
* Let Brian answer notification replies in the background (run a coach turn, push the answer).
* An internal analytics dashboard over `nudges` / `nudge_events` and an offline policy-evaluation
  notebook (the SQL in docs/nudge-engine.md is the starting point).
* A contextual bandit (e.g. Vowpal Wabbit) once traffic allows; health/calendar signals as context.
* Crash reporting and product analytics (Sentry, PostHog), localisation, privacy policy.
