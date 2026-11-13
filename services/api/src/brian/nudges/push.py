"""Expo push service client. One API for both platforms: Expo forwards to APNs (iOS) and FCM
(Android). Docs: https://docs.expo.dev/push-notifications/sending-notifications/

For local development on a Mac, devices registered by the app in the iOS Simulator (tokens starting
with `ExponentPushToken[simulator`) are delivered straight into the booted Simulator with
`xcrun simctl push`, using the payload shape Expo's service produces, so the whole loop (planning,
copy, action buttons, events, learning) can be exercised without a physical phone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from brian.config import Settings, get_settings

log = logging.getLogger(__name__)

SEND_BATCH = 100
RECEIPT_BATCH = 1000
SIMULATOR_TOKEN_PREFIX = "ExponentPushToken[simulator"  # noqa: S105 - registered by dev builds in the Simulator
LOCAL_TICKET_PREFIXES = ("dry-run-", "simulator-")


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
        """One ticket per message, in order."""
        tickets: list[PushTicket | None] = [None] * len(messages)
        remote: list[int] = []
        for index, message in enumerate(messages):
            if self._settings.push_dry_run:
                log.info("push dry run: %s", message.payload())
                tickets[index] = PushTicket("ok", f"dry-run-{uuid.uuid4()}", None, None)
            elif message.to.startswith(SIMULATOR_TOKEN_PREFIX):
                tickets[index] = await self._send_to_simulator(message)
            else:
                remote.append(index)
        for start in range(0, len(remote), SEND_BATCH):
            batch = remote[start : start + SEND_BATCH]
            response = await self._http.post(self._settings.expo_push_url, json=[messages[i].payload() for i in batch])
            response.raise_for_status()
            for index, item in zip(batch, response.json().get("data", []), strict=False):
                tickets[index] = PushTicket(
                    status=item.get("status", "error"),
                    id=item.get("id"),
                    error=(item.get("details") or {}).get("error"),
                    message=item.get("message"),
                )
        return [t or PushTicket("error", None, "MissingTicket", "no ticket returned") for t in tickets]

    async def _send_to_simulator(self, message: PushMessage) -> PushTicket:
        bundle_id = self._settings.push_simulator_bundle_id
        xcrun = shutil.which("xcrun")
        if self._settings.environment != "local" or not bundle_id:
            # A Simulator token can only be reached from a local backend on the same Mac.
            return PushTicket("error", None, "DeviceNotRegistered", "Simulator delivery is local-only")
        if xcrun is None:
            return PushTicket("error", None, "SimulatorUnavailable", "xcrun not found: needs macOS with Xcode")
        with tempfile.NamedTemporaryFile("w", suffix=".apns", delete=False) as handle:
            json.dump(simulator_payload(message, bundle_id), handle)
            path = handle.name
        try:
            process = await asyncio.create_subprocess_exec(
                xcrun,
                "simctl",
                "push",
                "booted",
                bundle_id,
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
        finally:
            os.unlink(path)
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()[:300]
            log.warning("simctl push failed: %s", detail)
            return PushTicket("error", None, "SimulatorPushFailed", detail)
        return PushTicket("ok", f"simulator-{uuid.uuid4()}", None, None)

    async def receipts(self, ticket_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Receipt per ticket id: {"status": "ok"} or {"status": "error", "details": {"error": ...}}."""
        results: dict[str, dict[str, Any]] = {}
        real_ids = [t for t in ticket_ids if not t.startswith(LOCAL_TICKET_PREFIXES)]
        results.update({t: {"status": "ok"} for t in ticket_ids if t.startswith(LOCAL_TICKET_PREFIXES)})
        for start in range(0, len(real_ids), RECEIPT_BATCH):
            batch = real_ids[start : start + RECEIPT_BATCH]
            response = await self._http.post(self._settings.expo_receipts_url, json={"ids": batch})
            response.raise_for_status()
            results.update(response.json().get("data", {}))
        return results


def simulator_payload(message: PushMessage, bundle_id: str) -> dict[str, Any]:
    """An APNs payload in the shape Expo's push service delivers: expo-notifications on iOS reads a
    remote notification's `data` from the top-level `body` key."""
    aps: dict[str, Any] = {"alert": {"title": message.title, "body": message.body}, "sound": "default"}
    if message.category_id:
        aps["category"] = message.category_id
    return {"Simulator Target Bundle": bundle_id, "aps": aps, "body": message.data}
