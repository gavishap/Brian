"""Background worker: the proactive half of Brian. Run with `brian-worker` (or `uv run brian-worker`)."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from brian import jobs
from brian.config import get_settings
from brian.logs import configure_logging

log = logging.getLogger("brian.worker")


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    defaults = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 60}
    now = datetime.now(UTC)
    # Interval jobs also run shortly after start-up instead of waiting a full interval after a deploy.
    interval_jobs = [
        (jobs.finalize_outcomes, 5, "finalize_outcomes"),
        (jobs.plan_nudges, 5, "plan_nudges"),
        (jobs.send_due_nudges, 1, "send_due_nudges"),
        (jobs.check_push_receipts, 10, "check_push_receipts"),
    ]
    for offset, (func, minutes, job_id) in enumerate(interval_jobs):
        scheduler.add_job(
            func,
            IntervalTrigger(minutes=minutes),
            id=job_id,
            next_run_time=now + timedelta(seconds=2 + 3 * offset),
            **defaults,
        )
    scheduler.add_job(jobs.reflect, CronTrigger(hour=3, minute=17), id="reflect", **defaults)
    return scheduler


async def main() -> None:
    configure_logging(get_settings().log_level)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)  # one line per job run is noise
    scheduler = build_scheduler()
    scheduler.start()
    log.info("worker started with jobs: %s", [job.id for job in scheduler.get_jobs()])
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    scheduler.shutdown(wait=False)
    log.info("worker stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
