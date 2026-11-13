-- Brian: initial schema.
--
-- Every table lives in `public` with row-level security enabled. The mobile app talks to the
-- Brian API (which connects as the table owner and bypasses RLS); the policies below only let a
-- signed-in user *read* their own rows through Supabase's auto-generated APIs (useful for
-- Realtime subscriptions). All writes go through the API so the nudge engine sees every change.

-- ---------------------------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------------------------

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------------------------
-- Profiles: one row per auth user, created by trigger on sign-up.
-- ---------------------------------------------------------------------------------------------

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text check (char_length(display_name) <= 80),
  timezone text not null default 'UTC',
  locale text not null default 'en-US',
  nudge_intensity text not null default 'balanced'
    check (nudge_intensity in ('gentle', 'balanced', 'intense')),
  quiet_hours_start time not null default '22:00',
  quiet_hours_end time not null default '07:30',
  nudges_paused_until timestamptz,
  onboarded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, nullif(new.raw_user_meta_data ->> 'display_name', ''))
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------------------------
-- Devices: Expo push tokens (Expo's push service fans out to APNs and FCM).
-- ---------------------------------------------------------------------------------------------

create table public.devices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  expo_push_token text not null unique,
  platform text not null check (platform in ('ios', 'android', 'web')),
  device_name text,
  app_version text,
  enabled boolean not null default true,
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index devices_user_enabled_idx on public.devices (user_id) where enabled;

-- ---------------------------------------------------------------------------------------------
-- Goals, milestones and check-ins.
-- ---------------------------------------------------------------------------------------------

create table public.goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  title text not null check (char_length(title) between 1 and 200),
  description text,
  why text,
  category text not null default 'other'
    check (category in ('health', 'fitness', 'learning', 'career', 'finance',
                        'relationships', 'mindfulness', 'creativity', 'other')),
  cadence text not null default 'daily'
    check (cadence in ('daily', 'weekdays', 'weekly', 'flexible')),
  target_per_period smallint not null default 1 check (target_per_period between 1 and 14),
  target_date date,
  status text not null default 'active'
    check (status in ('active', 'paused', 'completed', 'archived')),
  priority smallint not null default 2 check (priority between 1 and 3),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index goals_user_status_idx on public.goals (user_id, status);

create trigger goals_touch before update on public.goals
  for each row execute function public.touch_updated_at();

create table public.milestones (
  id uuid primary key default gen_random_uuid(),
  goal_id uuid not null references public.goals (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  title text not null check (char_length(title) between 1 and 200),
  due_date date,
  position smallint not null default 0,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);

create index milestones_goal_idx on public.milestones (goal_id, position);

-- ---------------------------------------------------------------------------------------------
-- Nudges: one row per proactive message. The policy's decision is stored with the
-- probability it had of being chosen (propensities) and the features it saw (context),
-- which is what makes off-policy evaluation of new policies possible later.
-- ---------------------------------------------------------------------------------------------

create table public.nudges (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  goal_id uuid references public.goals (id) on delete set null,
  source text not null default 'policy'
    check (source in ('policy', 'user_scheduled', 'agent')),
  status text not null default 'planned'
    check (status in ('planned', 'sending', 'sent', 'delivered', 'failed', 'cancelled')),

  -- decision
  policy_version text not null,
  arms jsonb not null default '{}'::jsonb,
  propensities jsonb not null default '{}'::jsonb,
  context jsonb not null default '{}'::jsonb,
  scheduled_for timestamptz not null,
  expires_at timestamptz not null,

  -- content
  title text,
  body text,
  category_id text,
  copy_source text,
  requested_text text,

  -- delivery
  sent_at timestamptz,
  delivered_at timestamptz,
  push_tickets jsonb not null default '[]'::jsonb,
  receipts_checked_at timestamptz,
  error text,

  -- outcome
  first_interaction_at timestamptz,
  outcome text check (outcome in ('completed', 'replied', 'snoozed', 'opened',
                                  'dismissed', 'ignored', 'negative_feedback')),
  reward real check (reward between 0 and 1),
  finalized_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index nudges_due_idx on public.nudges (scheduled_for) where status = 'planned';
create index nudges_user_time_idx on public.nudges (user_id, scheduled_for desc);
create index nudges_open_outcome_idx on public.nudges (expires_at)
  where finalized_at is null and status in ('sent', 'delivered');
create index nudges_receipts_idx on public.nudges (sent_at)
  where status = 'sent' and receipts_checked_at is null;

create trigger nudges_touch before update on public.nudges
  for each row execute function public.touch_updated_at();

-- Raw, append-only interaction log. Outcomes and rewards are derived from it.
create table public.nudge_events (
  id bigint generated always as identity primary key,
  nudge_id uuid not null references public.nudges (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  event_type text not null
    check (event_type in ('sent', 'delivered', 'failed', 'received', 'opened', 'action',
                          'dismissed', 'replied', 'expired', 'finalized', 'cancelled')),
  action_id text,
  payload jsonb not null default '{}'::jsonb,
  client_event_id text,
  occurred_at timestamptz not null default now(),
  received_at timestamptz not null default now(),
  constraint nudge_events_client_event_key unique (user_id, client_event_id)
);

create index nudge_events_nudge_idx on public.nudge_events (nudge_id, occurred_at);

create table public.check_ins (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  goal_id uuid not null references public.goals (id) on delete cascade,
  nudge_id uuid references public.nudges (id) on delete set null,
  kind text not null check (kind in ('done', 'progress', 'skipped', 'note')),
  value numeric,
  note text check (char_length(note) <= 2000),
  source text not null default 'app' check (source in ('app', 'notification', 'chat', 'agent')),
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index check_ins_user_time_idx on public.check_ins (user_id, occurred_at desc);
create index check_ins_goal_time_idx on public.check_ins (goal_id, occurred_at desc);

-- ---------------------------------------------------------------------------------------------
-- Bandit sufficient statistics. user_id NULL = population-level stats (used as the prior
-- for users with little data). successes/failures are time-decayed reward sums.
-- ---------------------------------------------------------------------------------------------

create table public.policy_stats (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users (id) on delete cascade,
  dimension text not null,
  context_key text not null default 'all',
  arm text not null,
  successes double precision not null default 0 check (successes >= 0),
  failures double precision not null default 0 check (failures >= 0),
  pulls integer not null default 0,
  updated_at timestamptz not null default now(),
  constraint policy_stats_key unique nulls not distinct (user_id, dimension, context_key, arm)
);

-- ---------------------------------------------------------------------------------------------
-- Coach chat. `content` holds the exact content blocks sent to / received from Claude,
-- replayed verbatim on later turns (append-only history keeps thinking blocks valid and the
-- prompt cache warm). `display_text` is what the app renders.
-- ---------------------------------------------------------------------------------------------

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  title text,
  model text not null,
  nudge_id uuid references public.nudges (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index conversations_user_idx on public.conversations (user_id, updated_at desc);

create trigger conversations_touch before update on public.conversations
  for each row execute function public.touch_updated_at();

create table public.chat_messages (
  id bigint generated always as identity primary key,
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  seq integer not null,
  role text not null check (role in ('user', 'assistant', 'system')),
  content jsonb not null,
  display_text text,
  stop_reason text,
  usage jsonb,
  created_at timestamptz not null default now(),
  constraint chat_messages_seq_key unique (conversation_id, seq)
);

create index chat_messages_user_time_idx on public.chat_messages (user_id, created_at desc);

-- Durable facts the coach has learned about the user ("works night shifts").
create table public.memories (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  content text not null check (char_length(content) between 1 and 500),
  source text not null default 'agent' check (source in ('agent', 'user', 'reflection')),
  created_at timestamptz not null default now()
);

create index memories_user_idx on public.memories (user_id, created_at desc);

-- ---------------------------------------------------------------------------------------------
-- Insights: periodic reflection over a user's engagement data. `stats` is computed
-- deterministically; `playbook` is written by Claude and fed back into nudge copywriting.
-- ---------------------------------------------------------------------------------------------

create table public.insights (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  period_start timestamptz not null,
  period_end timestamptz not null,
  stats jsonb not null,
  playbook jsonb not null,
  summary text not null,
  model text,
  created_at timestamptz not null default now()
);

create index insights_user_idx on public.insights (user_id, created_at desc);

-- ---------------------------------------------------------------------------------------------
-- Row-level security: read-only access to your own rows for signed-in users.
-- ---------------------------------------------------------------------------------------------

alter table public.profiles enable row level security;
alter table public.devices enable row level security;
alter table public.goals enable row level security;
alter table public.milestones enable row level security;
alter table public.nudges enable row level security;
alter table public.nudge_events enable row level security;
alter table public.check_ins enable row level security;
alter table public.policy_stats enable row level security;
alter table public.conversations enable row level security;
alter table public.chat_messages enable row level security;
alter table public.memories enable row level security;
alter table public.insights enable row level security;

create policy "read own profile" on public.profiles
  for select to authenticated using ((select auth.uid()) = id);
create policy "read own devices" on public.devices
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own goals" on public.goals
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own milestones" on public.milestones
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own nudges" on public.nudges
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own nudge events" on public.nudge_events
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own check-ins" on public.check_ins
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own policy stats" on public.policy_stats
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own conversations" on public.conversations
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own chat messages" on public.chat_messages
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own memories" on public.memories
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "read own insights" on public.insights
  for select to authenticated using ((select auth.uid()) = user_id);
