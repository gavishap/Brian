"""Background worker: the proactive half of Brian. Run with `brian-worker` (or `uv run brian-worker`)."""

from __future__ import annotations

import asyncio
import logging
import signal

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
    scheduler.add_job(jobs.send_due_nudges, IntervalTrigger(minutes=1), id="send_due_nudges", **defaults)
    scheduler.add_job(jobs.plan_nudges, IntervalTrigger(minutes=5), id="plan_nudges", **defaults)
    scheduler.add_job(jobs.finalize_outcomes, IntervalTrigger(minutes=5), id="finalize_outcomes", **defaults)
    scheduler.add_job(jobs.check_push_receipts, IntervalTrigger(minutes=10), id="check_push_receipts", **defaults)
    scheduler.add_job(jobs.reflect, CronTrigger(hour=3, minute=17), id="reflect", **defaults)
    return scheduler


async def main() -> None:
    configure_logging(get_settings().log_level)
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
