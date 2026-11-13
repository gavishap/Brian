"""Developer commands: `uv run brian-dev <command>`.

  simulate    Run synthetic people with hidden preferences through the real engine and report
              how well the policy learned them (vs a random policy).
  seed        Fill a real account (by email) with realistic history: goals, check-ins, weeks of
              nudges and reactions, learned preferences and insights. For the app in the Simulator.
  nudge-now   Plan and send a nudge to an account right now (e.g. to the iOS Simulator).

All commands use DATABASE_URL and refuse to run when ENVIRONMENT=production.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from datetime import timedelta
from typing import Any

import numpy as np
from sqlalchemy import select, text, update

from brian.config import get_settings
from brian.db import get_engine, get_sessionmaker
from brian.insights.reflection import run_reflection
from brian.models import Device, Goal, Memory, Nudge, Profile
from brian.nudges.copywriter import generate_copy
from brian.nudges.dispatcher import dispatch_due_nudges
from brian.nudges.planner import choose_arms, choose_goal, decision_context
from brian.nudges.push import ExpoPushClient
from brian.progress import progress_for_goals
from brian.sim.personas import PERSONAS
from brian.sim.runner import (
    SIM_TOKEN_PREFIX,
    SimulationResult,
    create_person,
    delete_people,
    prepare_account,
    restore_population_stats,
    simulate_person,
    snapshot_population_stats,
    template_copy,
)
from brian.timeutils import to_local, utcnow


def _pct(value: float | None) -> str:
    return "  -  " if value is None else f"{value * 100:4.0f}%"


def print_report(results: list[SimulationResult]) -> None:
    weeks = max(len(r.weekly_quality) for r in results)
    print("\nDecision quality: average true engagement probability of the nudges each policy chose")
    header = f"{'person':8} {'policy':9} {'nudges':>6} {'engaged':>8} " + " ".join(
        f"{'wk' + str(i + 1):>6}" for i in range(weeks)
    )
    print(header)
    print("-" * len(header))
    for r in results:
        cells = " ".join(f"{_pct(q):>6}" for q in r.weekly_quality)
        print(f"{r.persona:8} {r.policy:9} {r.nudges:>6} {_pct(r.engagement_rate):>8} {cells}")

    print("\nWhat the learning policy believes vs the hidden truth")
    for r in results:
        if r.policy != "learning":
            continue
        persona = PERSONAS[r.persona]
        print(f"\n{persona.display_name}: {persona.summary}")
        for dimension in ("time_window", "tone", "framing", "nudge_type", "length"):
            learned = r.learned.get(dimension) or []
            truth = r.truth.get(dimension) or []
            best = learned[0][0] if learned else "-"
            hit = "yes" if best in truth[:2] else "no"
            top = ", ".join(f"{arm} {score:.2f}" for arm, score in learned[:3])
            print(f"  {dimension:12} learned top: {top:44} true top-2: {', '.join(truth[:2]):24} match: {hit}")


async def cmd_simulate(args: argparse.Namespace) -> int:
    sessionmaker = get_sessionmaker()
    keys = [k.strip() for k in args.personas.split(",") if k.strip()]
    unknown = [k for k in keys if k not in PERSONAS]
    if unknown:
        print(f"unknown persona(s): {', '.join(unknown)}; choose from {', '.join(PERSONAS)}", file=sys.stderr)
        return 2
    async with sessionmaker() as session:
        snapshot = await snapshot_population_stats(session)
    start = utcnow() - timedelta(days=args.days + 1)
    created: list[uuid.UUID] = []
    results: list[SimulationResult] = []
    began = time.monotonic()
    try:
        for index, key in enumerate(keys):
            persona = PERSONAS[key]
            policies = ["learning", "random"] if args.baseline else ["learning"]
            for policy in policies:
                async with sessionmaker() as session:
                    await restore_population_stats(session, snapshot)  # each run starts from the same prior
                user_id = await create_person(sessionmaker, persona, onboarded_at=start)
                created.append(user_id)
                results.append(
                    await simulate_person(
                        sessionmaker,
                        user_id,
                        persona,
                        start=start,
                        days=args.days,
                        seed=args.seed + index,  # same seed for both policies of a person
                        policy=policy,
                    )
                )
                print(f"  simulated {persona.display_name} ({policy}) in {time.monotonic() - began:.1f}s", flush=True)
    finally:
        if not args.keep:
            await delete_people(sessionmaker, created)
        async with sessionmaker() as session:
            await restore_population_stats(session, snapshot)
    print_report(results)
    return 0


async def _user_by_email(email: str) -> uuid.UUID | None:
    async with get_sessionmaker()() as session:
        row = await session.scalar(text("select id from auth.users where lower(email) = lower(:e)"), {"e": email})
        return uuid.UUID(str(row)) if row else None


async def cmd_seed(args: argparse.Namespace) -> int:
    persona = PERSONAS.get(args.persona)
    if persona is None:
        print(f"unknown persona {args.persona!r}; choose from {', '.join(PERSONAS)}", file=sys.stderr)
        return 2
    sessionmaker = get_sessionmaker()
    user_id = await _user_by_email(args.email)
    if user_id is None:
        if not args.create:
            print(
                f"No account for {args.email}. Sign in once in the app with that email (the code arrives in "
                "the local inbox at http://127.0.0.1:54324), then run this again. Or pass --create to make a "
                "bare test account (it can't sign in through Supabase Auth).",
                file=sys.stderr,
            )
            return 1
        start = utcnow() - timedelta(days=args.days)
        user_id = await create_person(sessionmaker, persona, email=args.email, onboarded_at=start, with_device=False)
    start = utcnow() - timedelta(days=args.days)
    await prepare_account(sessionmaker, user_id, persona, onboarded_at=start, timezone=args.timezone)

    # A stand-in phone for the simulated weeks; removed afterwards so live nudges go to real devices.
    async with sessionmaker() as session:
        session.add(
            Device(user_id=user_id, expo_push_token=f"{SIM_TOKEN_PREFIX}seed-{uuid.uuid4().hex[:8]}]", platform="ios")
        )
        await session.commit()
    copy_fn = generate_copy if args.llm else template_copy
    print(f"Simulating {args.days} days of {persona.display_name}'s history for {args.email} ...", flush=True)
    result = await simulate_person(
        sessionmaker,
        user_id,
        persona,
        start=start,
        days=args.days,
        seed=args.seed,
        copy_fn=copy_fn,
        finalize_tail=False,  # the real worker closes the last windows
    )
    async with sessionmaker() as session:
        await session.execute(
            update(Device)
            .where(Device.user_id == user_id, Device.expo_push_token.startswith(SIM_TOKEN_PREFIX))
            .values(enabled=False)
        )
        # Nothing simulated should still be waiting to go out.
        await session.execute(
            update(Nudge)
            .where(Nudge.user_id == user_id, Nudge.status == "planned", Nudge.scheduled_for < utcnow())
            .values(status="cancelled", error="simulation_ended")
        )
        existing = set(await session.scalars(select(Memory.content).where(Memory.user_id == user_id)))
        for fact in persona.facts:
            if fact not in existing:
                session.add(Memory(user_id=user_id, content=fact, source="user"))
        profile = await session.get(Profile, user_id)
        assert profile is not None
        await session.commit()
        insight = await run_reflection(session, profile)
        await session.commit()
    print(
        f"Done: {result.nudges} nudges ({result.engagement_rate:.0%} engaged), insights by {insight.model}.\n"
        f"Open the app signed in as {args.email}: Today, Goals and Insights now show this history."
    )
    return 0


async def cmd_nudge_now(args: argparse.Namespace) -> int:
    """A nudge right now, with the policy choosing goal and style (timing is forced, so the nudge is
    marked `source="agent"` and not learned from)."""
    user_id = await _user_by_email(args.email)
    if user_id is None:
        print(f"No account for {args.email}.", file=sys.stderr)
        return 1
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    now = utcnow()
    rng = np.random.default_rng()
    async with sessionmaker() as session:
        devices = list(await session.scalars(select(Device).where(Device.user_id == user_id, Device.enabled)))
        if not devices:
            print(
                "No push-enabled device for this account. Open the app (signed in) on the phone or Simulator "
                "first so it registers.",
                file=sys.stderr,
            )
            return 1
        profile = await session.get(Profile, user_id)
        assert profile is not None
        goals = list(
            await session.scalars(
                select(Goal).where(Goal.user_id == user_id, Goal.status == "active").order_by(Goal.created_at)
            )
        )
        if not goals:
            print("The account has no active goals yet.", file=sys.stderr)
            return 1
        progress = await progress_for_goals(session, goals, profile.timezone, now)
        goal = choose_goal(goals, progress, {}, now, rng)
        local = to_local(now, profile.timezone)
        ctx = decision_context(profile, goal, progress[goal.id], day=local.date(), now=now, ignored=0)
        choices, keys = await choose_arms(session, profile, ctx, windows=None, now=now, rng=rng, settings=settings)
        nudge = Nudge(
            user_id=user_id,
            goal_id=goal.id,
            source="agent",
            status="planned",
            policy_version=settings.policy_version,
            arms={d: c.arm for d, c in choices.items()},
            propensities={d: round(c.propensity, 5) for d, c in choices.items()},
            context={**ctx.as_dict(), "context_keys": keys, "forced": True},
            scheduled_for=now,
            expires_at=now + timedelta(hours=settings.nudge_attribution_hours),
        )
        session.add(nudge)
        await session.commit()
        nudge_id = nudge.id
    push = ExpoPushClient()
    try:
        outcome = await dispatch_due_nudges(
            sessionmaker, push, now=now, copy_fn=generate_copy if args.llm else template_copy, user_id=user_id
        )
    finally:
        await push.aclose()
    async with sessionmaker() as session:
        sent = await session.get(Nudge, nudge_id)
        assert sent is not None
        print(f"{sent.status}: {sent.title!r} / {sent.body!r}")
        print(f"style: {sent.arms}  (dispatch: {outcome})")
        for ticket in sent.push_tickets:
            print(f"  device {ticket.get('device_id')}: {ticket.get('status')} {ticket.get('error') or ''}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brian-dev", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sim = sub.add_parser("simulate", help="simulate synthetic people and report what the policy learned")
    sim.add_argument("--personas", default=",".join(PERSONAS), help=f"comma-separated: {', '.join(PERSONAS)}")
    sim.add_argument("--days", type=int, default=28)
    sim.add_argument("--seed", type=int, default=7)
    sim.add_argument("--no-baseline", dest="baseline", action="store_false", help="skip the random-policy runs")
    sim.add_argument("--keep", action="store_true", help="keep the synthetic accounts instead of deleting them")

    seed = sub.add_parser("seed", help="fill an account with simulated history")
    seed.add_argument("--email", required=True)
    seed.add_argument("--persona", default="maya", help=f"one of: {', '.join(PERSONAS)}")
    seed.add_argument("--days", type=int, default=21)
    seed.add_argument("--seed", type=int, default=11)
    seed.add_argument("--timezone", help="IANA zone for the account (default: the persona's)")
    seed.add_argument("--llm", action="store_true", help="write nudge copy with Claude (costs API credits)")
    seed.add_argument("--create", action="store_true", help="create a bare auth user if none exists")

    now = sub.add_parser("nudge-now", help="plan and send a nudge to an account immediately")
    now.add_argument("--email", required=True)
    now.add_argument("--llm", action="store_true", help="write the copy with Claude")
    return parser


async def _main(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    if get_settings().environment == "production":
        print("brian-dev refuses to run with ENVIRONMENT=production", file=sys.stderr)
        return 2
    handlers: dict[str, Any] = {"simulate": cmd_simulate, "seed": cmd_seed, "nudge-now": cmd_nudge_now}
    try:
        return int(await handlers[args.command](args))
    finally:
        await get_engine().dispose()


def run(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_main(argv)))


if __name__ == "__main__":
    run()
