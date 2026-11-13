"""Expo push service client. One API for both platforms: Expo forwards to APNs (iOS) and FCM
(Android). Docs: https://docs.expo.dev/push-notifications/sending-notifications/"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from brian.config import Settings, get_settings

log = logging.getLogger(__name__)

SEND_BATCH = 100
RECEIPT_BATCH = 1000


@dataclass(frozen=True)
class PushMessage:
    to: str
    title: str
    body: str
    data: dict[str, Any]
    category_id: str | None = None
    ttl_seconds: int | None = None

    def payload(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "to": self.to,
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "sound": "default",
            "priority": "high",
            "channelId": "nudges",  # Android notification channel created by the app
        }
        if self.category_id:
            message["categoryId"] = self.category_id  # action buttons registered by the app
        if self.ttl_seconds:
            message["ttl"] = self.ttl_seconds
        return message


@dataclass(frozen=True)
class PushTicket:
    status: str  # "ok" | "error"
    id: str | None
    error: str | None
    message: str | None


class ExpoPushClient:
    def __init__(self, settings: Settings | None = None, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        headers = {"Accept": "application/json", "Accept-Encoding": "gzip, deflate"}
        if self._settings.expo_access_token:
            headers["Authorization"] = f"Bearer {self._settings.expo_access_token.get_secret_value()}"
        self._http = http or httpx.AsyncClient(timeout=20.0, headers=headers)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def send(self, messages: list[PushMessage]) -> list[PushTicket]:
        tickets: list[PushTicket] = []
        for start in range(0, len(messages), SEND_BATCH):
            batch = messages[start : start + SEND_BATCH]
            if self._settings.push_dry_run:
                log.info("push dry run: %s", [m.payload() for m in batch])
                tickets += [PushTicket("ok", f"dry-run-{uuid.uuid4()}", None, None) for _ in batch]
                continue
            response = await self._http.post(self._settings.expo_push_url, json=[m.payload() for m in batch])
            response.raise_for_status()
            for item in response.json().get("data", []):
                tickets.append(
                    PushTicket(
                        status=item.get("status", "error"),
                        id=item.get("id"),
                        error=(item.get("details") or {}).get("error"),
                        message=item.get("message"),
                    )
                )
        return tickets

    async def receipts(self, ticket_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Receipt per ticket id: {"status": "ok"} or {"status": "error", "details": {"error": ...}}."""
        results: dict[str, dict[str, Any]] = {}
        real_ids = [t for t in ticket_ids if not t.startswith("dry-run-")]
        results.update({t: {"status": "ok"} for t in ticket_ids if t.startswith("dry-run-")})
        for start in range(0, len(real_ids), RECEIPT_BATCH):
            batch = real_ids[start : start + RECEIPT_BATCH]
            response = await self._http.post(self._settings.expo_receipts_url, json={"ids": batch})
            response.raise_for_status()
            results.update(response.json().get("data", {}))
        return results
