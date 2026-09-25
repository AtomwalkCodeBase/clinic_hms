"""
core/push.py
------------
Thin wrapper around Expo's push notification service. Used so far only by
apps/registry/tasks.py to notify a patient when a background bulk
extraction batch finishes — no other feature sends push yet.

No SDK needed: Expo's push API is a plain HTTPS POST
(https://docs.expo.dev/push-notifications/sending-notifications/#http2-api),
and `requests` is already a project dependency.
"""

import logging

import requests

logger = logging.getLogger(__name__)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_TIMEOUT = 10


def send_push(tokens: "list[str]", title: str, body: str, data: dict | None = None) -> None:
    """
    Best-effort — a push failure (bad token, Expo outage) never raises;
    the in-app status the patient sees when they reopen the app is the
    source of truth regardless of whether the OS notification landed.
    """
    tokens = [t for t in tokens if t]
    if not tokens:
        return
    messages = [{"to": t, "title": title, "body": body, "data": data or {}} for t in tokens]
    try:
        requests.post(
            _EXPO_PUSH_URL,
            json=messages,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
    except Exception:
        logger.warning("push: failed to reach Expo push service", exc_info=True)
