from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import text

from brian import jobs
from brian.auth import DbSession
from brian.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: DbSession) -> dict[str, str]:
    await session.execute(text("select 1"))
    return {"status": "ready"}


@router.post("/internal/tick", include_in_schema=False)
async def tick(x_internal_key: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """Run one round of the background jobs. For hosts that use an external scheduler (Supabase
    Cron, Cloud Scheduler, GitHub Actions) instead of the worker process."""
    expected = get_settings().internal_api_key
    if (
        expected is None
        or x_internal_key is None
        or not hmac.compare_digest(x_internal_key, expected.get_secret_value())
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return await jobs.tick()
