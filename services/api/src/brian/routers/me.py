from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete

from brian.auth import CurrentProfile, DbSession
from brian.config import get_settings
from brian.models import (
    ChatMessage,
    CheckIn,
    Conversation,
    Device,
    Goal,
    Insight,
    Memory,
    Milestone,
    Nudge,
    NudgeEvent,
    PolicyStat,
    Profile,
)
from brian.schemas import ProfileOut, ProfileUpdate
from brian.timeutils import is_valid_timezone, utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/me", tags=["me"])


@router.get("", response_model=ProfileOut)
async def get_me(profile: CurrentProfile) -> Profile:
    return profile


@router.patch("", response_model=ProfileOut)
async def update_me(body: ProfileUpdate, profile: CurrentProfile, session: DbSession) -> Profile:
    changes = body.model_dump(exclude_unset=True)
    if "timezone" in changes and changes["timezone"] and not is_valid_timezone(changes["timezone"]):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown time zone")
    onboarded = changes.pop("onboarded", None)
    for key, value in changes.items():
        if value is not None or key in ("nudges_paused_until", "display_name"):
            setattr(profile, key, value)
    if onboarded and profile.onboarded_at is None:
        profile.onboarded_at = utcnow()
    await session.commit()
    await session.refresh(profile)
    return profile


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(profile: CurrentProfile, session: DbSession) -> None:
    """Delete the account and all its data (required by the App Store and Google Play)."""
    user_id = profile.id
    for model in (ChatMessage, Conversation, NudgeEvent, CheckIn, Milestone, Nudge, Goal, Device, Memory, Insight):
        await session.execute(delete(model).where(model.user_id == user_id))
    await session.execute(delete(PolicyStat).where(PolicyStat.user_id == user_id))
    await session.execute(delete(Profile).where(Profile.id == user_id))
    await session.commit()

    settings = get_settings()
    if settings.supabase_service_role_key:
        key = settings.supabase_service_role_key.get_secret_value()
        async with httpx.AsyncClient(timeout=15.0) as http:
            response = await http.delete(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
        if response.status_code >= 400:
            log.error("failed to delete auth user %s: %s", user_id, response.text)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Data deleted, but sign-in removal failed")
