# Brian mobile app

Expo (React Native) client for iOS and Android: sign-in, onboarding, goals and check-ins, the
streaming Coach chat, the Insights screen, and the actionable push notifications that feed Brian's
nudge optimizer.

- **Expo SDK 58** · React Native 0.88 · React 19.3 · TypeScript 6 · Expo Router (file-based routes in `src/app/`)
- **Server state:** TanStack Query · **API client:** `openapi-fetch`, typed from the backend's OpenAPI schema
- **Auth:** Supabase email one-time codes · **Push:** `expo-notifications` + Expo's push service (APNs and FCM)

## Setup

```bash
cd apps/mobile
npm install
cp .env.example .env   # then fill it in
npm start              # Expo dev server
```

| Variable | What it is |
| --- | --- |
| `EXPO_PUBLIC_API_URL` | Brian API base URL. On a physical phone use your computer's LAN IP (`http://192.168.x.y:8000`), not `127.0.0.1`. |
| `EXPO_PUBLIC_SUPABASE_URL` | Supabase project URL (local: `http://<LAN IP>:54321`). |
| `EXPO_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon / publishable key (`npx supabase status` prints the local one). |
| `EAS_PROJECT_ID` | EAS project id (`npx eas-cli@latest init`). Push tokens are scoped to it; without it the app runs but cannot receive pushes. |

`EXPO_PUBLIC_*` values are compiled into the app. Never put secrets in them.

Sign-in sends a 6-digit code by email. With the local Supabase stack, read it in the Mailpit inbox
that `npx supabase start` prints (usually `http://127.0.0.1:54324`).

## Run it in the iOS Simulator with Xcode

Needs a Mac with Xcode (App Store) and an iOS Simulator runtime (Xcode → Settings → Components),
CocoaPods (`brew install cocoapods`), and Docker Desktop running. From the repository root:

```bash
make up      # local Supabase + API + worker, and writes apps/mobile/.env for you
```

```bash
make ios     # = npm run ios = npx expo run:ios: builds with Xcode, boots a Simulator, installs, starts Metro
```

To work in Xcode itself: `npx expo prebuild --platform ios`, then `xed ios`, pick an iPhone
Simulator and press Run (⌘R) with `npm start` running. The `ios/` folder is generated (and
git-ignored); `expo prebuild` recreates it from `app.config.ts`.

In the Simulator:

1. **Sign in** with any email; the 6-digit code is in the local inbox at http://127.0.0.1:54324.
   Go through onboarding and allow notifications.
2. **Load realistic data and get a nudge**: three weeks of simulated history (goals, check-ins,
   nudges with their outcomes, what the optimizer learned, an insights playbook), then a nudge
   right away:

   ```bash
   make demo EMAIL=you@example.com
   ```

   Personas: `maya` (night-owl writer, the default), `sam` (early-bird analyst), `jordan` (busy
   parent), e.g. `make demo EMAIL=you@example.com PERSONA=sam`. Pull to refresh in the app.
3. **Another nudge any time**: `make nudge EMAIL=you@example.com`. It appears as a banner; long-press
   it (or click and hold) for the action buttons (**Done ✅ / Later / Reply** or **Reply / Less of
   these**). Your reaction is reported to the API, credited to the goal and fed to the optimizer:
   check the Today and Insights tabs. Nudges also arrive on their own at the times the worker plans.

How Simulator push works: there are no real APNs pushes in development. In a development build on
a simulator, the app registers a local token (`ExponentPushToken[simulator-…]`), and a backend
running on the same Mac with `ENVIRONMENT=local` and `PUSH_SIMULATOR_BUNDLE_ID` delivers those
nudges with `xcrun simctl push` in the same payload format Expo's push service uses. Release builds
never register such a token. Everything else (planning, copy, buttons, events, learning) is the
production path.

No Mac at hand? `npx eas-cli@latest build --profile simulator --platform ios` builds a Simulator app
in the cloud; install it on a Mac's Simulator with `eas build:run`.

## Expo Go vs. a development build

Most screens work in **Expo Go**, but nudges don't: Expo Go can't receive remote pushes for your
project, register notification action categories, or run the background notification task. Use a
development build (`npm run ios` above, or the cloud builds below) for anything involving nudges:

```bash
npx eas-cli@latest build --profile development --platform ios
```

```bash
npx eas-cli@latest build --profile development --platform android
```

Install the build on the phone, then `npm start` and open the project from the dev client. Real
pushes to a physical phone need `EAS_PROJECT_ID` and push credentials (see *Building for the
stores*).

## Browser preview

`npx expo start --web` renders the app in a browser for quick UI work (set `CORS_ORIGINS` on the
API, e.g. `["http://localhost:8081"]`). It uses JS bottom tabs (`src/app/(tabs)/_layout.web.tsx`)
and no-op notification modules (`*.web.ts`); notifications are native-only.

## Scripts

| Command | Does |
| --- | --- |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | `expo lint` (ESLint with `eslint-config-expo`) |
| `npm test` | Jest (`jest-expo` preset): SSE parser and notification-event mapping |
| `npm run ios` | Build with Xcode and run in the iOS Simulator (`expo run:ios`) |
| `npm run gen:api` | Regenerate `src/api/schema.ts` from `../../services/api/openapi.json` |

After changing the API, regenerate its OpenAPI file in `services/api`, then run `npm run gen:api`
and fix whatever `npm run typecheck` reports.

## How it fits together

```
src/
  app/                    routes (Expo Router)
    _layout.tsx           providers + auth gate (Stack.Protected): sign-in -> onboarding -> tabs
    (tabs)/               Today, Goals, Coach, Insights, Settings (native tabs)
    goal/new.tsx, goal/[id].tsx, nudge/[id].tsx
  api/                    schema.ts (generated), client.ts (auth middleware), queries.ts (TanStack hooks)
  lib/                    supabase, auth context, SSE parser, chat streaming, formatting
  notifications/          setup (channel + action categories), push-token registration,
                          event mapping, offline event queue, background task, observer hook
  components/, theme/     small design system with light and dark tokens
index.ts                  entry: defines the background notification task, then loads expo-router
```

### Nudges and the data they produce

Every push carries `{kind: "nudge", nudge_id, goal_id}` and a category with action buttons:

| Category | Buttons |
| --- | --- |
| `nudge_action` | **Done ✅** (`done`), **Later** (`snooze`), **Reply** (`reply`, text input) |
| `nudge_reflect` | **Reply** (`reply`, text input), **Less of these** (`not_helpful`) |

Each reaction becomes an event for `POST /v1/nudges/events`: tap → `opened`, a button → `action`
(with `action_id`, plus `text` for replies), an explicit iOS dismissal → `dismissed`, arrival while the
app is open → `received`. The server turns these into the rewards the optimizer learns from.

Events go into a persistent queue in AsyncStorage first, then are sent in batches: immediately, on
returning to the foreground, and after sign-in, with exponential backoff on network errors, 401, 429
and 5xx (other 4xx batches are dropped as invalid). Idempotency keys are derived from the
notification and the action, so one interaction seen twice (live listener plus the cold-start replay,
or the background task plus the listener) is stored once.

Platform behavior:
- **Android:** action buttons work without opening the app. A background task (registered in
  `index.ts`) receives action taps even when the app was killed, and records deliveries that arrive
  while the app is in the background.
- **iOS:** the OS only runs app code for an action of a killed app if the action opens the app, so
  every button opens Brian (otherwise the reaction would be lost). The nudge screen then confirms
  what was recorded. iOS also reports explicit dismissals (`customDismissAction`).

### Coach chat

`POST /v1/chat` streams server-sent events. The app reads them with `fetch` from `expo/fetch` (its
response body is a `ReadableStream` on iOS and Android), parses frames incrementally
(`src/lib/sse.ts`), appends `text` deltas to the reply bubble, and shows `tool` activity (for example
"Logging your progress") while Brian works. Opening a nudge and choosing **Talk to Brian about this**
starts a conversation tied to that nudge.

## Building for the stores

```bash
npx eas-cli@latest build --profile production --platform all
```

```bash
npx eas-cli@latest submit --profile production --platform ios
```

```bash
npx eas-cli@latest submit --profile production --platform android
```

Before the first store build:
- **Change the bundle identifier.** `com.example.brian` in `app.config.ts` is a placeholder; use a
  reverse-DNS name you own (it can't be changed after the first App Store / Play release).
- Upload push credentials: an APNs key for iOS (EAS can create it during `eas build`), and an FCM v1
  service-account key for Android in the Expo dashboard.
- Account deletion is built in (Settings → Delete account → `DELETE /v1/me`), as both stores require.
