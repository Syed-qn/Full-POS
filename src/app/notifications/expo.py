"""Expo Push API provider (production).

Sends a single push via https://exp.host/--/api/v2/push/send. Best-effort:
any failure (network, dead token, Expo error receipt) is logged and returns
False rather than raising — a failed push must never break the action that
triggered it (e.g. dispatch assignment).
"""
from __future__ import annotations

import logging

import httpx

from app.notifications.port import PushMessage

logger = logging.getLogger(__name__)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class ExpoPushProvider:
    async def send(self, message: PushMessage) -> bool:
        if not message.to_token:
            return False
        payload = {
            "to": message.to_token,
            "title": message.title,
            "body": message.body,
            "data": message.data,
            "sound": "default",
            "priority": "high",
            "channelId": "deliveries",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(_EXPO_PUSH_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            # Expo returns {"data": {"status": "ok"|"error", ...}}.
            status = (data.get("data") or {}).get("status")
            if status != "ok":
                logger.warning("Expo push not ok for token %s: %s", message.to_token, data)
                return False
            return True
        except Exception as exc:  # noqa: BLE001 - pushes are best-effort
            logger.warning("Expo push failed for token %s: %s", message.to_token, exc)
            return False
