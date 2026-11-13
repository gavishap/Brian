from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from brian.auth import CurrentProfile, DbSession
from brian.models import Device
from brian.schemas import DeviceOut, DeviceRegister
from brian.timeutils import is_valid_timezone, utcnow

router = APIRouter(prefix="/v1/devices", tags=["devices"])


@router.post("", response_model=DeviceOut)
async def register_device(body: DeviceRegister, profile: CurrentProfile, session: DbSession) -> Device:
    """Register (or refresh) this device's Expo push token. A token that belonged to another
    account on the same phone moves to the signed-in user."""
    now = utcnow()
    values = {
        "user_id": profile.id,
        "platform": body.platform,
        "device_name": body.device_name,
        "app_version": body.app_version,
        "enabled": True,
        "last_seen_at": now,
    }
    await session.execute(
        insert(Device)
        .values(expo_push_token=body.expo_push_token, **values)
        .on_conflict_do_update(index_elements=[Device.expo_push_token], set_=values)
    )
    if body.timezone and is_valid_timezone(body.timezone) and body.timezone != profile.timezone:
        profile.timezone = body.timezone
    await session.commit()
    device = await session.scalar(select(Device).where(Device.expo_push_token == body.expo_push_token))
    assert device is not None
    return device


@router.delete("/{expo_push_token}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(expo_push_token: str, profile: CurrentProfile, session: DbSession) -> None:
    """Stop pushing to this device (call on sign-out)."""
    await session.execute(
        update(Device)
        .where(Device.expo_push_token == expo_push_token, Device.user_id == profile.id)
        .values(enabled=False)
    )
    await session.commit()
