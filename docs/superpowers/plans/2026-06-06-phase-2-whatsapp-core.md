# Phase 2: WhatsApp Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WhatsApp adapter (Mock + Cloud API), idempotent webhook pipeline, transactional outbox with Celery delivery worker, conversation/messages tables with a greeting-state dialogue engine that renders the digital menu, and a zero-build-step web simulator to chat as a fake customer.

**Architecture:** Two new bounded contexts under `src/app/` — `whatsapp/` (adapter port + two providers + inbound normalization) and `conversation/` (models, state machine, engine service). A `POST /webhooks/whatsapp` endpoint normalizes inbound events → calls the conversation engine → engine writes outbox rows → Celery `outbox` worker delivers via the provider. MockProvider stores sends in-memory and exposes an inject endpoint; the web simulator calls that inject endpoint to create fake inbound messages and polls the MockProvider send-log to show outbound messages. CloudAPIProvider hits Meta Graph API v21 with `httpx` and verifies `X-Hub-Signature-256` on inbound.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy 2, Alembic, Celery + Redis, httpx (async), pydantic SecretStr, HMAC-SHA256 (stdlib `hmac`), single-file HTML simulator (no build step).

**Spec:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`

**Prerequisite:** Phase 0+1 plan fully executed (identity, menu, auth, riders all present). This plan builds on those tables and the `record_audit`, `get_session`, `current_restaurant`, `TimestampMixin`, and `Base` primitives.

---

## File structure (locked in)

```
src/app/
  config.py                          MODIFY: add WA settings fields
  main.py                            MODIFY: mount webhook + simulator routers
  whatsapp/
    __init__.py
    port.py                          OutboundMessage dataclass, InboundMessage dataclass, WhatsAppPort Protocol
    mock_provider.py                 MockProvider: in-memory send log, inject_inbound()
    cloud_provider.py                CloudAPIProvider: httpx → Meta Graph API v21, signature verify
    factory.py                       get_whatsapp_provider() FastAPI dependency
  conversation/
    __init__.py
    models.py                        Conversation, Message SQLAlchemy tables
    schemas.py                       Pydantic I/O for API responses
    engine.py                        handle_inbound(): state machine dispatch, greeting state
    service.py                       get_or_create_conversation(), record_message(), set_manual_takeover()
  outbox/
    __init__.py
    models.py                        OutboxMessage SQLAlchemy table
    service.py                       enqueue_message() writes row in same transaction
    worker.py                        Celery task: deliver_outbox_message()
  webhook/
    __init__.py
    models.py                        WebhookEvent SQLAlchemy table (idempotency)
    router.py                        GET verify handshake + POST inbound pipeline
    normalizer.py                    parse_cloud_payload() → InboundMessage

apps/workers/
  celery_app.py                      MODIFY: register outbox queue + task autodiscover

apps/simulator/
  __init__.py
  router.py                          FastAPI routes: POST /simulator/send, GET /simulator/messages
  static/
    index.html                       Single-file chat UI (inline CSS+JS, no build)

tests/
  conftest.py                        MODIFY: add model imports
  whatsapp/  __init__.py  test_mock_provider.py  test_cloud_provider.py  test_normalizer.py
  conversation/  __init__.py  test_engine.py  test_service.py
  outbox/  __init__.py  test_outbox_service.py  test_outbox_worker.py
  webhook/  __init__.py  test_webhook_router.py
  test_simulator.py
```

---

### Task 1: Settings additions

**Files:**
- Modify: `src/app/config.py`, `.env.example`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_config.py
def test_whatsapp_settings_defaults():
    s = Settings(_env_file=None)
    assert s.whatsapp_provider == "mock"
    assert s.wa_verify_token == "dev-verify-token"
    assert isinstance(s.wa_access_token, SecretStr)
    assert isinstance(s.wa_app_secret, SecretStr)


def test_whatsapp_provider_env_override(monkeypatch):
    monkeypatch.setenv("APP_WHATSAPP_PROVIDER", "cloud")
    monkeypatch.setenv("APP_WA_ACCESS_TOKEN", "tok123")
    s = Settings(_env_file=None)
    assert s.whatsapp_provider == "cloud"
    assert s.wa_access_token.get_secret_value() == "tok123"
```

Note: add `from pydantic import SecretStr` to the test file imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'whatsapp_provider'`

- [ ] **Step 3: Add fields to `src/app/config.py`** (keep existing fields; append after `upload_dir`):

```python
    # WhatsApp
    whatsapp_provider: str = "mock"  # mock | cloud
    wa_verify_token: str = "dev-verify-token"
    wa_access_token: SecretStr = SecretStr("")
    wa_phone_number_id: str = ""
    wa_app_secret: SecretStr = SecretStr("")
```

- [ ] **Step 4: Append to `.env.example`:**

```
APP_WHATSAPP_PROVIDER=mock
APP_WA_VERIFY_TOKEN=dev-verify-token
APP_WA_ACCESS_TOKEN=
APP_WA_PHONE_NUMBER_ID=
APP_WA_APP_SECRET=
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/config.py .env.example tests/test_config.py
git commit -m "feat: WhatsApp settings fields (provider, verify token, access token, app secret)"
```

---

### Task 2: WhatsApp port (protocol + message dataclasses)

**Files:**
- Create: `src/app/whatsapp/__init__.py`, `src/app/whatsapp/port.py`
- Create: `tests/whatsapp/__init__.py`
- Test: `tests/whatsapp/test_mock_provider.py` (port-shape tests first)

- [ ] **Step 1: Write the failing test**

```python
# tests/whatsapp/test_mock_provider.py
from app.whatsapp.port import (
    InboundMessage,
    MessageType,
    OutboundMessage,
    OutboundMessageType,
)


def test_outbound_message_text_shape():
    msg = OutboundMessage(
        to_phone="+971501234567",
        type=OutboundMessageType.TEXT,
        payload={"body": "Hello!"},
        idempotency_key="key-1",
    )
    assert msg.to_phone == "+971501234567"
    assert msg.payload["body"] == "Hello!"


def test_inbound_message_shape():
    msg = InboundMessage(
        wa_message_id="wamid.abc123",
        from_phone="+971509999999",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone="+97141234567",
    )
    assert msg.from_phone == "+971509999999"
    assert msg.type == MessageType.TEXT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/whatsapp/test_mock_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.whatsapp'`

- [ ] **Step 3: Write implementation**

```python
# src/app/whatsapp/__init__.py
```

```python
# src/app/whatsapp/port.py
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class OutboundMessageType(StrEnum):
    TEXT = "text"
    BUTTONS = "buttons"
    LIST = "list"
    LOCATION_REQUEST = "location_request"
    IMAGE = "image"
    TEMPLATE = "template"


class MessageType(StrEnum):
    TEXT = "text"
    BUTTON_REPLY = "button_reply"
    LIST_REPLY = "list_reply"
    LOCATION = "location"
    IMAGE = "image"
    UNKNOWN = "unknown"


@dataclass
class OutboundMessage:
    to_phone: str
    type: OutboundMessageType
    payload: dict
    idempotency_key: str
    # wa_message_id populated after successful send
    wa_message_id: str | None = None


@dataclass
class InboundMessage:
    wa_message_id: str
    from_phone: str
    type: MessageType
    payload: dict          # raw content; keys depend on type
    restaurant_phone: str  # the WABA number that received this
    timestamp: int = 0     # unix epoch from Meta payload


class WhatsAppPort(Protocol):
    async def send(self, msg: OutboundMessage) -> str:
        """Send message; return wa_message_id."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/whatsapp/test_mock_provider.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/whatsapp tests/whatsapp
git commit -m "feat: WhatsApp port dataclasses and protocol"
```

---

### Task 3: MockProvider

**Files:**
- Create: `src/app/whatsapp/mock_provider.py`
- Test: `tests/whatsapp/test_mock_provider.py` (append)

- [ ] **Step 1: Write the failing test** — append:

```python
# append to tests/whatsapp/test_mock_provider.py
from app.whatsapp.mock_provider import MockProvider


async def test_mock_send_records_and_returns_id():
    provider = MockProvider()
    msg = OutboundMessage(
        to_phone="+971501234567",
        type=OutboundMessageType.TEXT,
        payload={"body": "Hello!"},
        idempotency_key="k1",
    )
    wa_id = await provider.send(msg)
    assert wa_id.startswith("mock-wamid-")
    sent = provider.drain_sends()
    assert len(sent) == 1
    assert sent[0].wa_message_id == wa_id


async def test_mock_inject_inbound_queues_message():
    provider = MockProvider()
    inbound = InboundMessage(
        wa_message_id="wamid.test1",
        from_phone="+971509999999",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone="+97141234567",
    )
    provider.inject_inbound(inbound)
    queued = provider.drain_inbound()
    assert len(queued) == 1
    assert queued[0].wa_message_id == "wamid.test1"


async def test_mock_drain_clears_log():
    provider = MockProvider()
    msg = OutboundMessage(
        to_phone="+971501234567",
        type=OutboundMessageType.TEXT,
        payload={"body": "Hi"},
        idempotency_key="k2",
    )
    await provider.send(msg)
    provider.drain_sends()
    assert provider.drain_sends() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/whatsapp/test_mock_provider.py -v`
Expected: FAIL — `ImportError: cannot import name 'MockProvider'`

- [ ] **Step 3: Write implementation**

```python
# src/app/whatsapp/mock_provider.py
import uuid
from collections import deque

from app.whatsapp.port import InboundMessage, OutboundMessage


class MockProvider:
    """In-memory WhatsApp provider for tests and the web simulator.

    Thread-safety: not needed — event loop is single-threaded.
    """

    def __init__(self) -> None:
        self._sends: list[OutboundMessage] = []
        self._inbound: deque[InboundMessage] = deque()

    async def send(self, msg: OutboundMessage) -> str:
        wa_id = f"mock-wamid-{uuid.uuid4().hex[:12]}"
        msg.wa_message_id = wa_id
        self._sends.append(msg)
        return wa_id

    def inject_inbound(self, msg: InboundMessage) -> None:
        """Queue an inbound message to be processed by the webhook pipeline."""
        self._inbound.append(msg)

    def drain_sends(self) -> list[OutboundMessage]:
        """Return all recorded sends and clear the log."""
        result = list(self._sends)
        self._sends.clear()
        return result

    def drain_inbound(self) -> list[InboundMessage]:
        """Return all queued inbound messages and clear the queue."""
        result = list(self._inbound)
        self._inbound.clear()
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/whatsapp/test_mock_provider.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/whatsapp/mock_provider.py tests/whatsapp/test_mock_provider.py
git commit -m "feat: MockProvider with send log and inbound injection"
```

---

### Task 4: CloudAPIProvider + HMAC signature verification

**Files:**
- Create: `src/app/whatsapp/cloud_provider.py`
- Create: `tests/whatsapp/test_cloud_provider.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/whatsapp/test_cloud_provider.py
import hashlib
import hmac

import pytest

from app.whatsapp.cloud_provider import CloudAPIProvider, verify_signature


def test_verify_signature_valid():
    secret = "testsecret"
    body = b'{"object":"whatsapp_business_account"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Should not raise
    verify_signature(body, sig, secret)


def test_verify_signature_invalid_raises():
    with pytest.raises(ValueError, match="signature"):
        verify_signature(b"body", "sha256=badhex", "secret")


def test_verify_signature_missing_prefix_raises():
    with pytest.raises(ValueError, match="signature"):
        verify_signature(b"body", "badsig", "secret")


def test_cloud_provider_requires_config(monkeypatch):
    """CloudAPIProvider instantiates with settings; no network call in __init__."""
    from app.config import get_settings

    monkeypatch.setenv("APP_WA_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("APP_WA_PHONE_NUMBER_ID", "12345")
    monkeypatch.setenv("APP_WA_APP_SECRET", "appsecret")
    get_settings.cache_clear()
    try:
        provider = CloudAPIProvider()
        assert provider is not None
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/whatsapp/test_cloud_provider.py -v`
Expected: FAIL — `ImportError: cannot import name 'CloudAPIProvider'`

- [ ] **Step 3: Write implementation**

```python
# src/app/whatsapp/cloud_provider.py
import hashlib
import hmac as _hmac
from typing import Any

import httpx

from app.config import get_settings
from app.whatsapp.port import OutboundMessage, OutboundMessageType

_GRAPH_BASE = "https://graph.facebook.com/v21.0"


def verify_signature(body: bytes, header: str, secret: str) -> None:
    """Raise ValueError if X-Hub-Signature-256 header does not match body HMAC."""
    if not header.startswith("sha256="):
        raise ValueError("signature header missing sha256= prefix")
    expected = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = header[len("sha256="):]
    if not _hmac.compare_digest(expected, received):
        raise ValueError("signature mismatch — request not from Meta")


def _build_graph_payload(msg: OutboundMessage) -> dict[str, Any]:
    base: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": msg.to_phone,
    }
    if msg.type == OutboundMessageType.TEXT:
        base["type"] = "text"
        base["text"] = {"body": msg.payload["body"], "preview_url": False}

    elif msg.type == OutboundMessageType.BUTTONS:
        # payload: {"body": str, "buttons": [{"id": str, "title": str}]}
        base["type"] = "interactive"
        base["interactive"] = {
            "type": "button",
            "body": {"text": msg.payload["body"]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in msg.payload["buttons"]
                ]
            },
        }

    elif msg.type == OutboundMessageType.LIST:
        # payload: {"body": str, "button_label": str, "sections": [...]}
        base["type"] = "interactive"
        base["interactive"] = {
            "type": "list",
            "body": {"text": msg.payload["body"]},
            "action": {
                "button": msg.payload["button_label"],
                "sections": msg.payload["sections"],
            },
        }

    elif msg.type == OutboundMessageType.LOCATION_REQUEST:
        # payload: {"body": str}
        base["type"] = "interactive"
        base["interactive"] = {
            "type": "location_request_message",
            "body": {"text": msg.payload["body"]},
            "action": {"name": "send_location"},
        }

    elif msg.type == OutboundMessageType.IMAGE:
        # payload: {"url": str, "caption": str}
        base["type"] = "image"
        base["image"] = {"link": msg.payload["url"], "caption": msg.payload.get("caption", "")}

    elif msg.type == OutboundMessageType.TEMPLATE:
        # payload: {"name": str, "language": str, "components": list}
        base["type"] = "template"
        base["template"] = {
            "name": msg.payload["name"],
            "language": {"code": msg.payload.get("language", "en")},
            "components": msg.payload.get("components", []),
        }

    return base


class CloudAPIProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.wa_access_token.get_secret_value()
        self._phone_number_id = settings.wa_phone_number_id
        self._app_secret = settings.wa_app_secret.get_secret_value()

    async def send(self, msg: OutboundMessage) -> str:
        url = f"{_GRAPH_BASE}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        payload = _build_graph_payload(msg)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        wa_id: str = data["messages"][0]["id"]
        msg.wa_message_id = wa_id
        return wa_id

    def verify_inbound_signature(self, body: bytes, header: str) -> None:
        verify_signature(body, header, self._app_secret)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/whatsapp/test_cloud_provider.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/whatsapp/cloud_provider.py tests/whatsapp/test_cloud_provider.py
git commit -m "feat: CloudAPIProvider with Meta Graph API v21 and HMAC signature verification"
```

---

### Task 5: WhatsApp provider factory

**Files:**
- Create: `src/app/whatsapp/factory.py`

- [ ] **Step 1: Write implementation** (covered by integration tests later)

```python
# src/app/whatsapp/factory.py
from functools import lru_cache

from app.config import get_settings
from app.whatsapp.mock_provider import MockProvider


@lru_cache
def _get_mock_provider() -> MockProvider:
    """Singleton MockProvider shared across the process — enables simulator access."""
    return MockProvider()


def get_whatsapp_provider():
    """FastAPI dependency. Returns MockProvider (singleton) or CloudAPIProvider."""
    settings = get_settings()
    if settings.whatsapp_provider == "cloud":
        from app.whatsapp.cloud_provider import CloudAPIProvider

        return CloudAPIProvider()
    if settings.whatsapp_provider == "mock":
        return _get_mock_provider()
    raise ValueError(f"Unknown whatsapp_provider: {settings.whatsapp_provider!r}")


def get_mock_provider() -> MockProvider:
    """Direct access to MockProvider singleton — used by simulator router."""
    return _get_mock_provider()
```

- [ ] **Step 2: Commit**

```bash
git add src/app/whatsapp/factory.py
git commit -m "feat: WhatsApp provider factory (mock singleton, cloud on-demand)"
```

---

### Task 6: Payload normalizer (Cloud API → InboundMessage)

**Files:**
- Create: `src/app/webhook/__init__.py`, `src/app/webhook/normalizer.py`
- Create: `tests/whatsapp/test_normalizer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/whatsapp/test_normalizer.py
from app.webhook.normalizer import parse_cloud_payload
from app.whatsapp.port import MessageType

# Minimal real Meta payload structure (text message)
_TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
                        "messages": [
                            {
                                "id": "wamid.HBgL",
                                "from": "971509876543",
                                "timestamp": "1717660800",
                                "type": "text",
                                "text": {"body": "Hello, I want to order"},
                            }
                        ],
                    },
                    "field": "messages",
                }
            ]
        }
    ],
}

_BUTTON_REPLY_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
                        "messages": [
                            {
                                "id": "wamid.BTN1",
                                "from": "971509876543",
                                "timestamp": "1717660900",
                                "type": "interactive",
                                "interactive": {
                                    "type": "button_reply",
                                    "button_reply": {"id": "confirm", "title": "Yes"},
                                },
                            }
                        ],
                    },
                    "field": "messages",
                }
            ]
        }
    ],
}

_LOCATION_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
                        "messages": [
                            {
                                "id": "wamid.LOC1",
                                "from": "971509876543",
                                "timestamp": "1717661000",
                                "type": "location",
                                "location": {"latitude": 25.2048, "longitude": 55.2708},
                            }
                        ],
                    },
                    "field": "messages",
                }
            ]
        }
    ],
}


def test_parse_text_message():
    msgs = parse_cloud_payload(_TEXT_PAYLOAD)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.wa_message_id == "wamid.HBgL"
    assert m.from_phone == "+971509876543"
    assert m.type == MessageType.TEXT
    assert m.payload["text"] == "Hello, I want to order"
    assert m.restaurant_phone == "+97141234567"
    assert m.timestamp == 1717660800


def test_parse_button_reply():
    msgs = parse_cloud_payload(_BUTTON_REPLY_PAYLOAD)
    assert msgs[0].type == MessageType.BUTTON_REPLY
    assert msgs[0].payload["id"] == "confirm"
    assert msgs[0].payload["title"] == "Yes"


def test_parse_location():
    msgs = parse_cloud_payload(_LOCATION_PAYLOAD)
    assert msgs[0].type == MessageType.LOCATION
    assert msgs[0].payload["latitude"] == 25.2048
    assert msgs[0].payload["longitude"] == 55.2708


def test_parse_status_update_returns_empty():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
                            "statuses": [{"id": "wamid.abc", "status": "delivered"}],
                        },
                        "field": "messages",
                    }
                ]
            }
        ],
    }
    assert parse_cloud_payload(payload) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/whatsapp/test_normalizer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.webhook'`

- [ ] **Step 3: Write implementation**

```python
# src/app/webhook/__init__.py
```

```python
# src/app/webhook/normalizer.py
from app.whatsapp.port import InboundMessage, MessageType


def _normalize_phone(raw: str) -> str:
    """Ensure phone has + prefix (Meta sends without it)."""
    return raw if raw.startswith("+") else f"+{raw}"


def _parse_single_message(msg: dict, restaurant_phone: str) -> InboundMessage:
    msg_type = msg.get("type", "unknown")
    wa_id = msg["id"]
    from_phone = _normalize_phone(msg["from"])
    timestamp = int(msg.get("timestamp", 0))

    if msg_type == "text":
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.TEXT,
            payload={"text": msg["text"]["body"]},
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "interactive":
        interactive = msg["interactive"]
        itype = interactive.get("type")
        if itype == "button_reply":
            br = interactive["button_reply"]
            return InboundMessage(
                wa_message_id=wa_id,
                from_phone=from_phone,
                type=MessageType.BUTTON_REPLY,
                payload={"id": br["id"], "title": br["title"]},
                restaurant_phone=restaurant_phone,
                timestamp=timestamp,
            )
        if itype == "list_reply":
            lr = interactive["list_reply"]
            return InboundMessage(
                wa_message_id=wa_id,
                from_phone=from_phone,
                type=MessageType.LIST_REPLY,
                payload={"id": lr["id"], "title": lr["title"]},
                restaurant_phone=restaurant_phone,
                timestamp=timestamp,
            )

    if msg_type == "location":
        loc = msg["location"]
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.LOCATION,
            payload={"latitude": loc["latitude"], "longitude": loc["longitude"]},
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "image":
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.IMAGE,
            payload={
                "image_id": msg.get("image", {}).get("id"),
                "caption": msg.get("image", {}).get("caption"),
            },
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=from_phone,
        type=MessageType.UNKNOWN,
        payload={"raw_type": msg_type},
        restaurant_phone=restaurant_phone,
        timestamp=timestamp,
    )


def parse_cloud_payload(payload: dict) -> list[InboundMessage]:
    """Parse a Meta Cloud API webhook payload into a list of InboundMessages.

    Returns empty list for status updates and other non-message events.
    """
    results: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            restaurant_phone = value.get("metadata", {}).get("display_phone_number", "")
            for msg in value.get("messages", []):
                results.append(_parse_single_message(msg, restaurant_phone))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/whatsapp/test_normalizer.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/webhook tests/whatsapp/test_normalizer.py
git commit -m "feat: Cloud API payload normalizer to InboundMessage"
```

---

### Task 7: webhook_events + outbox_messages + conversations + messages tables

**Files:**
- Create: `src/app/webhook/models.py`, `src/app/outbox/__init__.py`, `src/app/outbox/models.py`, `src/app/conversation/__init__.py`, `src/app/conversation/models.py`
- Modify: `alembic/env.py`, `tests/conftest.py` (register modules)

- [ ] **Step 1: Write models**

```python
# src/app/webhook/models.py
from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class WebhookEvent(Base, TimestampMixin):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_event_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    processed_at: Mapped[str | None] = mapped_column(String(64))  # ISO timestamp or None
```

```python
# src/app/outbox/__init__.py
```

```python
# src/app/outbox/models.py
from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class OutboxMessage(Base, TimestampMixin):
    __tablename__ = "outbox_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    to_phone: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    # payload shape: {"type": OutboundMessageType, ...type-specific keys}
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending | sent | failed | dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    wa_message_id: Mapped[str | None] = mapped_column(String(256))
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
```

```python
# src/app/conversation/__init__.py
```

```python
# src/app/conversation/models.py
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    counterpart: Mapped[str] = mapped_column(String(16))  # customer | rider
    phone: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    # state["dialogue_state"] = "greeting" | "menu_sent" | ...
    manual_takeover: Mapped[bool] = mapped_column(Boolean, default=False)
    taken_over_by: Mapped[int | None] = mapped_column(BigInteger)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    direction: Mapped[str] = mapped_column(String(8))  # inbound | outbound
    wa_message_id: Mapped[str | None] = mapped_column(String(256), index=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB)
    ts: Mapped[int] = mapped_column(Integer, default=0)  # unix epoch
```

- [ ] **Step 2: Register modules** — add to both `alembic/env.py` and `tests/conftest.py` import blocks:

```python
import app.webhook.models   # noqa: F401
import app.outbox.models    # noqa: F401
import app.conversation.models  # noqa: F401
```

- [ ] **Step 3: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "webhook_outbox_conversation_messages"
.venv/bin/alembic upgrade head
docker compose exec db psql -U app -d restaurant -c "\dt"
```
Expected: `webhook_events`, `outbox_messages`, `conversations`, `messages` created.

- [ ] **Step 4: Commit**

```bash
git add src/app/webhook/models.py src/app/outbox src/app/conversation alembic/versions alembic/env.py tests/conftest.py
git commit -m "feat: webhook_events, outbox_messages, conversations, messages tables"
```

---

### Task 8: Outbox service (enqueue) + worker (deliver)

**Files:**
- Create: `src/app/outbox/service.py`, `src/app/outbox/worker.py`
- Modify: `apps/workers/celery_app.py`
- Create: `tests/outbox/__init__.py`, `tests/outbox/test_outbox_service.py`, `tests/outbox/test_outbox_worker.py`

- [ ] **Step 1: Write the failing service test**

```python
# tests/outbox/test_outbox_service.py
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.outbox.models import OutboxMessage
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType


async def test_enqueue_writes_pending_row(db_session):
    await enqueue_message(
        db_session,
        restaurant_id=1,
        to_phone="+971509876543",
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "Your order is confirmed."},
        idempotency_key="conv-1-greeting",
    )
    await db_session.commit()

    row = (await db_session.execute(select(OutboxMessage))).scalar_one()
    assert row.status == "pending"
    assert row.to_phone == "+971509876543"
    assert row.payload["body"] == "Your order is confirmed."
    assert row.idempotency_key == "conv-1-greeting"
    assert row.attempts == 0


async def test_enqueue_duplicate_idempotency_key_raises(db_session):
    """Second enqueue with same key hits the DB unique constraint."""
    await enqueue_message(
        db_session,
        restaurant_id=1,
        to_phone="+971509876543",
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "Hello"},
        idempotency_key="dup-key-1",
    )
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await enqueue_message(
            db_session,
            restaurant_id=1,
            to_phone="+971509876543",
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "Hello again"},
            idempotency_key="dup-key-1",
        )
        await db_session.commit()
```

NOTE: tests reference restaurant_id=1 — seed a restaurant row first if FK enforcement requires it (create via signup endpoint or direct insert in a fixture).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/outbox/test_outbox_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/app/outbox/service.py`**

```python
# src/app/outbox/service.py
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.models import OutboxMessage
from app.whatsapp.port import OutboundMessageType


async def enqueue_message(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    msg_type: OutboundMessageType,
    payload: dict,
    idempotency_key: str,
) -> OutboxMessage:
    """Write an outbox row in the caller's transaction. Commit is the caller's responsibility."""
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone=to_phone,
        payload={"type": str(msg_type), **payload},
        idempotency_key=idempotency_key,
    )
    session.add(row)
    return row
```

- [ ] **Step 4: Run service test to verify it passes**

Run: `.venv/bin/pytest tests/outbox/test_outbox_service.py -v`
Expected: 2 PASS

- [ ] **Step 5: Write the failing worker test**

```python
# tests/outbox/test_outbox_worker.py
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.port import OutboundMessageType


async def _seed_outbox(session, *, status="pending", attempts=0) -> OutboxMessage:
    row = OutboxMessage(
        restaurant_id=1,
        to_phone="+971509876543",
        payload={"type": str(OutboundMessageType.TEXT), "body": "Hello"},
        idempotency_key=f"worker-test-{status}-{attempts}",
        status=status,
        attempts=attempts,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def test_deliver_one_sends_and_marks_sent(engine, db_session):
    row = await _seed_outbox(db_session)
    provider = MockProvider()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    await _deliver_one(row.id, provider=provider, session_factory=factory)

    sends = provider.drain_sends()
    assert len(sends) == 1
    assert sends[0].to_phone == "+971509876543"

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "sent"
    assert updated.attempts == 1
    assert updated.wa_message_id is not None


async def test_deliver_one_marks_failed_on_send_error(engine, db_session):
    row = await _seed_outbox(db_session)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    failing_provider = MockProvider()

    async def _bad_send(msg):
        raise RuntimeError("network error")

    failing_provider.send = _bad_send

    await _deliver_one(row.id, provider=failing_provider, session_factory=factory)

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "failed"
    assert updated.attempts == 1


async def test_deliver_one_marks_dead_after_3_failures(engine, db_session):
    row = await _seed_outbox(db_session, status="failed", attempts=2)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    failing_provider = MockProvider()

    async def _bad_send(msg):
        raise RuntimeError("still broken")

    failing_provider.send = _bad_send

    await _deliver_one(row.id, provider=failing_provider, session_factory=factory)

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "dead"
```

- [ ] **Step 6: Run worker test to verify it fails**

Run: `.venv/bin/pytest tests/outbox/test_outbox_worker.py -v`
Expected: FAIL — `ImportError: cannot import name '_deliver_one'`

- [ ] **Step 7: Write `src/app/outbox/worker.py`**

```python
# src/app/outbox/worker.py
import asyncio
import logging

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.outbox.models import OutboxMessage
from app.whatsapp.port import OutboundMessage, OutboundMessageType, WhatsAppPort

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3


def _outbox_row_to_outbound(row: OutboxMessage) -> OutboundMessage:
    payload = dict(row.payload)
    msg_type = OutboundMessageType(payload.pop("type"))
    return OutboundMessage(
        to_phone=row.to_phone,
        type=msg_type,
        payload=payload,
        idempotency_key=row.idempotency_key,
    )


async def _deliver_one(
    outbox_id: int,
    *,
    provider: WhatsAppPort,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        row = await session.get(OutboxMessage, outbox_id)
        if row is None or row.status in ("sent", "dead"):
            return
        msg = _outbox_row_to_outbound(row)
        try:
            wa_id = await provider.send(msg)
            row.status = "sent"
            row.wa_message_id = wa_id
            row.attempts += 1
        except Exception as exc:
            row.attempts += 1
            logger.warning("outbox delivery failed for id=%s: %s", outbox_id, exc)
            row.status = "dead" if row.attempts >= _MAX_ATTEMPTS else "failed"
        await session.commit()


@shared_task(name="outbox.deliver", bind=True, max_retries=0)
def deliver_outbox_message(self, outbox_id: int) -> None:
    """Celery task: deliver one outbox message via the configured provider."""
    from app.db import async_session_factory
    from app.whatsapp.factory import get_whatsapp_provider

    provider = get_whatsapp_provider()
    asyncio.run(
        _deliver_one(outbox_id, provider=provider, session_factory=async_session_factory)
    )
```

- [ ] **Step 8: Update `apps/workers/celery_app.py`** — add outbox queue + autodiscover:

```python
# apps/workers/celery_app.py
from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery(
    "restaurant",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_default_queue="default",
    timezone="Asia/Dubai",
    task_routes={
        "outbox.deliver": {"queue": "outbox"},
    },
)
celery_app.autodiscover_tasks(["app.outbox"], related_name="worker")
```

- [ ] **Step 9: Run worker tests**

Run: `.venv/bin/pytest tests/outbox/ -v`
Expected: 5 PASS

- [ ] **Step 10: Commit**

```bash
git add src/app/outbox tests/outbox apps/workers/celery_app.py
git commit -m "feat: transactional outbox service + Celery delivery worker with retry/dead-letter"
```

---

### Task 9: Conversation service

**Files:**
- Create: `src/app/conversation/service.py`, `src/app/conversation/schemas.py`
- Create: `tests/conversation/__init__.py`, `tests/conversation/test_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/conversation/test_service.py
from sqlalchemy import select

from app.conversation.models import Message
from app.conversation.service import (
    get_or_create_conversation,
    record_message,
    set_manual_takeover,
)


async def test_get_or_create_creates_new_conversation(db_session):
    conv = await get_or_create_conversation(
        db_session,
        restaurant_id=1,
        phone="+971509876543",
        counterpart="customer",
    )
    assert conv.id is not None
    assert conv.state == {}
    assert conv.manual_takeover is False


async def test_get_or_create_returns_existing(db_session):
    conv1 = await get_or_create_conversation(
        db_session, restaurant_id=1, phone="+971509876543", counterpart="customer"
    )
    await db_session.commit()
    conv2 = await get_or_create_conversation(
        db_session, restaurant_id=1, phone="+971509876543", counterpart="customer"
    )
    assert conv1.id == conv2.id


async def test_record_inbound_message(db_session):
    conv = await get_or_create_conversation(
        db_session, restaurant_id=1, phone="+971509876543", counterpart="customer"
    )
    await db_session.commit()

    await record_message(
        db_session,
        conversation_id=conv.id,
        direction="inbound",
        wa_message_id="wamid.test1",
        msg_type="text",
        payload={"text": "hi"},
        ts=1717660800,
    )
    await db_session.commit()

    row = (await db_session.execute(select(Message))).scalar_one()
    assert row.direction == "inbound"
    assert row.payload["text"] == "hi"


async def test_set_manual_takeover(db_session):
    conv = await get_or_create_conversation(
        db_session, restaurant_id=1, phone="+971509876543", counterpart="customer"
    )
    await db_session.commit()

    await set_manual_takeover(db_session, conversation_id=conv.id, taken_over_by=42)
    await db_session.commit()

    await db_session.refresh(conv)
    assert conv.manual_takeover is True
    assert conv.taken_over_by == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/app/conversation/service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.models import Conversation, Message


async def get_or_create_conversation(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
    counterpart: str,
) -> Conversation:
    existing = await session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant_id,
            Conversation.phone == phone,
        )
    )
    if existing is not None:
        return existing
    conv = Conversation(
        restaurant_id=restaurant_id,
        phone=phone,
        counterpart=counterpart,
        state={},
    )
    session.add(conv)
    await session.flush()
    return conv


async def record_message(
    session: AsyncSession,
    *,
    conversation_id: int,
    direction: str,
    wa_message_id: str | None,
    msg_type: str,
    payload: dict,
    ts: int = 0,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        direction=direction,
        wa_message_id=wa_message_id,
        type=msg_type,
        payload=payload,
        ts=ts,
    )
    session.add(msg)
    return msg


async def set_manual_takeover(
    session: AsyncSession,
    *,
    conversation_id: int,
    taken_over_by: int,
) -> None:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise ValueError(f"conversation {conversation_id} not found")
    conv.manual_takeover = True
    conv.taken_over_by = taken_over_by
```

```python
# src/app/conversation/schemas.py
from pydantic import BaseModel, ConfigDict


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    phone: str
    counterpart: str
    state: dict
    manual_takeover: bool
    taken_over_by: int | None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    direction: str
    wa_message_id: str | None
    type: str
    payload: dict
    ts: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/conversation/test_service.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/conversation tests/conversation
git commit -m "feat: conversation service — get-or-create, record message, manual takeover"
```

---

### Task 10: Conversation engine — greeting state (menu render)

**Files:**
- Create: `src/app/conversation/engine.py`
- Create: `tests/conversation/test_engine.py`

Greeting state: any message when `dialogue_state` absent/`greeting` → fetch active menu, render `is_available=True` dishes as `"{dish_number}. {name} — AED {price}"` grouped by category, enqueue text via outbox, advance to `"menu_sent"`. If `manual_takeover` → engine records the message but sends nothing.

- [ ] **Step 1: Write the failing test**

```python
# tests/conversation/test_engine.py
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.conversation.service import get_or_create_conversation, set_manual_takeover
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _make_inbound(wa_id="wamid.test-engine-1", text="hi") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971509876543",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def _seed_menu(db_session, restaurant_id=1):
    """Active menu: two available dishes + one unavailable."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
                        name="Chicken Biryani", price_aed=Decimal("22.00"),
                        category="Rice", is_available=True))
    db_session.add(Dish(menu_id=menu.id, restaurant_id=restaurant_id, dish_number=201,
                        name="Mutton Karahi", price_aed=Decimal("35.00"),
                        category="Curries", is_available=True))
    db_session.add(Dish(menu_id=menu.id, restaurant_id=restaurant_id, dish_number=301,
                        name="Falooda", price_aed=Decimal("12.00"),
                        category="Desserts", is_available=False))
    await db_session.commit()
    return menu


async def test_greeting_sends_menu_to_outbox(db_session):
    await _seed_menu(db_session, restaurant_id=1)

    await handle_inbound(db_session, _make_inbound(), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    body: str = rows[0].payload["body"]
    assert "110. Chicken Biryani — AED 22" in body
    assert "201. Mutton Karahi — AED 35" in body
    assert "Falooda" not in body  # unavailable


async def test_greeting_advances_state_to_menu_sent(db_session):
    await _seed_menu(db_session, restaurant_id=1)
    await handle_inbound(db_session, _make_inbound(), restaurant_id=1)
    await db_session.commit()

    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.phone == "+971509876543")
        )
    ).scalar_one()
    assert conv.state["dialogue_state"] == "menu_sent"


async def test_manual_takeover_short_circuits_bot(db_session):
    await _seed_menu(db_session, restaurant_id=1)

    conv = await get_or_create_conversation(
        db_session, restaurant_id=1, phone="+971509876543", counterpart="customer"
    )
    await db_session.commit()
    await set_manual_takeover(db_session, conversation_id=conv.id, taken_over_by=99)
    await db_session.commit()

    await handle_inbound(db_session, _make_inbound(), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert rows == []  # bot sent nothing


async def test_second_message_after_menu_sent_does_not_resend_menu(db_session):
    await _seed_menu(db_session, restaurant_id=1)

    await handle_inbound(db_session, _make_inbound(), restaurant_id=1)
    await db_session.commit()

    await handle_inbound(
        db_session, _make_inbound(wa_id="wamid.test-engine-2", text="I want biryani"),
        restaurant_id=1,
    )
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1  # only greeting menu; second message is pass-through for now
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.conversation.engine'`

- [ ] **Step 3: Write implementation**

```python
# src/app/conversation/engine.py
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.conversation.models import Conversation
from app.conversation.service import get_or_create_conversation, record_message
from app.outbox.service import enqueue_message
from app.whatsapp.port import InboundMessage, OutboundMessageType


async def _render_menu(session: AsyncSession, restaurant_id: int) -> str:
    """Render active menu as categorized text."""
    from app.menu.models import Dish, Menu

    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if menu is None:
        return "Our menu is currently unavailable. Please try again later."

    dishes = await session.scalars(
        select(Dish)
        .where(Dish.menu_id == menu.id, Dish.is_available == True)  # noqa: E712
        .order_by(Dish.category, Dish.dish_number)
    )
    dish_list = list(dishes)
    if not dish_list:
        return "Our menu is currently unavailable. Please try again later."

    lines: list[str] = ["Welcome! Here is our menu:\n"]
    current_category: str | None = None
    for dish in dish_list:
        if dish.category != current_category:
            current_category = dish.category
            if current_category:
                lines.append(f"\n*{current_category}*")
        price = Decimal(dish.price_aed).normalize()
        lines.append(f"{dish.dish_number}. {dish.name} — AED {price}")

    return "\n".join(lines)


async def _handle_greeting(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Send the digital menu and advance state to menu_sent."""
    menu_text = await _render_menu(session, restaurant_id)
    key = f"greeting-{conv.id}-{inbound.wa_message_id}"
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": menu_text},
        idempotency_key=key,
    )
    conv.state = {**conv.state, "dialogue_state": "menu_sent"}
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="conversation",
        entity_id=str(conv.id),
        action="state_transition",
        before={"dialogue_state": "greeting"},
        after={"dialogue_state": "menu_sent"},
    )


async def handle_inbound(
    session: AsyncSession,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Main entry point: load conversation → record message → dispatch state handler."""
    conv = await get_or_create_conversation(
        session,
        restaurant_id=restaurant_id,
        phone=inbound.from_phone,
        counterpart="customer",
    )

    await record_message(
        session,
        conversation_id=conv.id,
        direction="inbound",
        wa_message_id=inbound.wa_message_id,
        msg_type=str(inbound.type),
        payload=inbound.payload,
        ts=inbound.timestamp,
    )

    # Manual takeover: bot is silent, human handles it
    if conv.manual_takeover:
        return

    dialogue_state = conv.state.get("dialogue_state", "greeting")

    if dialogue_state == "greeting":
        await _handle_greeting(session, conv, inbound, restaurant_id)
    # Future states (collecting_items, address_capture, ...) arrive in Phase 3
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/conversation/test_engine.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine.py
git commit -m "feat: conversation engine greeting state with menu render and takeover short-circuit"
```

---

### Task 11: Webhook router (GET verify + signed POST pipeline)

**Files:**
- Create: `src/app/webhook/router.py`
- Modify: `src/app/main.py`
- Create: `tests/webhook/__init__.py`, `tests/webhook/test_webhook_router.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/webhook/test_webhook_router.py
import hashlib
import hmac
import json
from decimal import Decimal


async def _seed_restaurant_and_menu(client, db_session):
    from app.menu.models import Dish, Menu

    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test Restaurant",
            "phone": "+97141234567",
            "password": "hunter2!",
            "lat": 25.2048,
            "lng": 55.2708,
        },
    )
    assert signup_resp.status_code == 201
    restaurant_id = signup_resp.json()["id"]
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(
        Dish(
            menu_id=menu.id,
            restaurant_id=restaurant_id,
            dish_number=110,
            name="Chicken Biryani",
            price_aed=Decimal("22.00"),
            category="Rice",
            is_available=True,
        )
    )
    await db_session.commit()
    return restaurant_id


def _signed_body(payload: dict, secret: str = "") -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


_TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "metadata": {
                            "display_phone_number": "+97141234567",
                            "phone_number_id": "111",
                        },
                        "messages": [
                            {
                                "id": "wamid.unique-e2e-001",
                                "from": "971509876543",
                                "timestamp": "1717660800",
                                "type": "text",
                                "text": {"body": "Hello"},
                            }
                        ],
                    },
                    "field": "messages",
                }
            ]
        }
    ],
}


async def test_get_verify_handshake_valid(client):
    resp = await client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "dev-verify-token",
            "hub.challenge": "1158201444",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "1158201444"


async def test_get_verify_handshake_wrong_token(client):
    resp = await client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "1158201444",
        },
    )
    assert resp.status_code == 403


async def test_post_webhook_processes_message_and_queues_outbox(client, db_session):
    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    await _seed_restaurant_and_menu(client, db_session)

    body, sig = _signed_body(_TEXT_PAYLOAD)
    resp = await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert resp.status_code == 200

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    assert "110. Chicken Biryani" in rows[0].payload["body"]


async def test_post_webhook_duplicate_event_is_ignored(client, db_session):
    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    await _seed_restaurant_and_menu(client, db_session)

    body, sig = _signed_body(_TEXT_PAYLOAD)
    await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    resp2 = await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert resp2.status_code == 200

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1  # not doubled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/webhook/ -v`
Expected: FAIL — 404 (routes missing)

- [ ] **Step 3: Write `src/app/webhook/router.py`**

```python
# src/app/webhook/router.py
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.conversation.engine import handle_inbound
from app.db import get_session
from app.identity.models import Restaurant
from app.webhook.models import WebhookEvent
from app.webhook.normalizer import parse_cloud_payload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])


@router.get("/webhooks/whatsapp")
async def verify_webhook(request: Request) -> Response:
    """Meta webhook verification handshake."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    settings = get_settings()
    if mode == "subscribe" and token == settings.wa_verify_token:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid verify token")


@router.post("/webhooks/whatsapp")
async def receive_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Receive inbound WhatsApp events from Meta (or simulator)."""
    body_bytes = await request.body()
    payload = await request.json()
    settings = get_settings()

    # Signature verification — enforced in cloud mode only (mock has no app secret)
    if settings.whatsapp_provider == "cloud":
        from app.whatsapp.cloud_provider import verify_signature

        sig_header = request.headers.get("X-Hub-Signature-256", "")
        try:
            verify_signature(
                body_bytes, sig_header, settings.wa_app_secret.get_secret_value()
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))

    inbound_messages = parse_cloud_payload(payload)

    for inbound in inbound_messages:
        # Idempotency check
        existing = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == inbound.wa_message_id
            )
        )
        if existing is not None:
            logger.info("duplicate webhook event %s — skipping", inbound.wa_message_id)
            continue

        session.add(
            WebhookEvent(
                provider_event_id=inbound.wa_message_id,
                payload=payload,
                processed_at=datetime.now(timezone.utc).isoformat(),
            )
        )

        restaurant = await session.scalar(
            select(Restaurant).where(Restaurant.phone == inbound.restaurant_phone)
        )
        if restaurant is None:
            logger.warning(
                "webhook for unknown restaurant phone %s — skipping",
                inbound.restaurant_phone,
            )
            continue

        try:
            await handle_inbound(session, inbound, restaurant_id=restaurant.id)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.warning(
                "integrity error processing event %s — idempotency collision",
                inbound.wa_message_id,
            )

    return {"status": "ok"}
```

- [ ] **Step 4: Mount in `src/app/main.py`:**

```python
from app.webhook.router import router as webhook_router
# inside create_app():
    app.include_router(webhook_router)
```

- [ ] **Step 5: Run webhook tests**

Run: `.venv/bin/pytest tests/webhook/ -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/webhook/router.py src/app/main.py tests/webhook
git commit -m "feat: webhook endpoint — verify handshake + signed inbound pipeline with idempotency"
```

---

### Task 12: Dispatch Celery outbox task after webhook commit

**Files:**
- Modify: `src/app/webhook/router.py`
- Test: `tests/webhook/test_webhook_router.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/webhook/test_webhook_router.py
async def test_post_webhook_dispatches_celery_task(client, db_session):
    """After successful webhook processing, outbox.deliver must be dispatched."""
    from unittest.mock import patch
    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    await _seed_restaurant_and_menu(client, db_session)

    dispatched_ids: list[int] = []

    def fake_apply_async(args, kwargs=None, queue=None, **kw):
        dispatched_ids.append(args[0])

    body, sig = _signed_body(_TEXT_PAYLOAD)
    with patch(
        "app.webhook.router.deliver_outbox_message.apply_async",
        side_effect=fake_apply_async,
    ):
        resp = await client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 200

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id in dispatched_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/webhook/test_webhook_router.py::test_post_webhook_dispatches_celery_task -v`
Expected: FAIL — patch target missing / dispatched_ids empty

- [ ] **Step 3: Update router** — add top-level import in `src/app/webhook/router.py`:

```python
from app.outbox.models import OutboxMessage
from app.outbox.worker import deliver_outbox_message
```

and replace the `try` block body with:

```python
        try:
            await handle_inbound(session, inbound, restaurant_id=restaurant.id)
            await session.commit()

            pending_rows = (
                await session.execute(
                    select(OutboxMessage).where(
                        OutboxMessage.status == "pending",
                        OutboxMessage.to_phone == inbound.from_phone,
                        OutboxMessage.restaurant_id == restaurant.id,
                    )
                )
            ).scalars().all()
            for outbox_row in pending_rows:
                deliver_outbox_message.apply_async(args=[outbox_row.id], queue="outbox")

        except IntegrityError:
            await session.rollback()
            logger.warning(
                "integrity error processing event %s — idempotency collision",
                inbound.wa_message_id,
            )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/webhook/ -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/webhook/router.py tests/webhook/test_webhook_router.py
git commit -m "feat: dispatch Celery outbox.deliver task after webhook commit"
```

---

### Task 13: Web simulator (FastAPI routes + single-page HTML)

**Files:**
- Create: `apps/simulator/__init__.py`, `apps/simulator/router.py`, `apps/simulator/static/index.html`
- Modify: `src/app/main.py` (mount simulator only in mock mode)
- Test: `tests/test_simulator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulator.py
async def test_simulator_index_returns_html(client):
    resp = await client.get("/simulator/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_simulator_send_queues_inbound_and_returns_ok(client):
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test Restaurant",
            "phone": "+97141234567",
            "password": "hunter2!",
            "lat": 25.2048,
            "lng": 55.2708,
        },
    )
    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509876543",
            "restaurant_phone": "+97141234567",
            "text": "Hi, I want to order",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_simulator_messages_returns_list(client):
    resp = await client.get("/simulator/messages")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_simulator.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Write `apps/simulator/router.py`**

```python
# apps/simulator/router.py
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.engine import handle_inbound
from app.db import get_session
from app.identity.models import Restaurant
from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one
from app.webhook.models import WebhookEvent
from app.whatsapp.factory import get_mock_provider
from app.whatsapp.port import InboundMessage, MessageType

router = APIRouter(prefix="/simulator", tags=["simulator"])

_HTML_PATH = Path(__file__).parent / "static" / "index.html"


@router.get("/", response_class=HTMLResponse)
async def simulator_index() -> str:
    return _HTML_PATH.read_text()


class SimulatorSendIn(BaseModel):
    from_phone: str
    restaurant_phone: str
    text: str


@router.post("/send")
async def simulator_send(
    body: SimulatorSendIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Inject a fake inbound text message through the full pipeline."""
    restaurant = await session.scalar(
        select(Restaurant).where(Restaurant.phone == body.restaurant_phone)
    )
    if restaurant is None:
        raise HTTPException(404, f"no restaurant with phone {body.restaurant_phone}")

    wa_id = f"sim-wamid-{uuid.uuid4().hex[:12]}"
    session.add(
        WebhookEvent(
            provider_event_id=wa_id,
            payload={"simulator": True, "text": body.text},
            processed_at=None,
        )
    )

    inbound = InboundMessage(
        wa_message_id=wa_id,
        from_phone=body.from_phone,
        type=MessageType.TEXT,
        payload={"text": body.text},
        restaurant_phone=body.restaurant_phone,
        timestamp=0,
    )
    await handle_inbound(session, inbound, restaurant_id=restaurant.id)
    await session.commit()

    # Synchronous delivery via MockProvider (simulator = immediate)
    pending = (
        await session.execute(
            select(OutboxMessage).where(
                OutboxMessage.status == "pending",
                OutboxMessage.to_phone == body.from_phone,
                OutboxMessage.restaurant_id == restaurant.id,
            )
        )
    ).scalars().all()

    provider = get_mock_provider()
    from app.db import async_session_factory

    for row in pending:
        await _deliver_one(row.id, provider=provider, session_factory=async_session_factory)

    return {"status": "ok", "wa_message_id": wa_id}


@router.get("/messages")
async def simulator_messages() -> list[dict]:
    """Return and clear the MockProvider send log for the simulator UI."""
    provider = get_mock_provider()
    sends = provider.drain_sends()
    return [
        {
            "to": s.to_phone,
            "type": str(s.type),
            "payload": s.payload,
            "wa_message_id": s.wa_message_id,
        }
        for s in sends
    ]
```

NOTE for tests: `_deliver_one` uses `async_session_factory` bound to the dev DB; in the test client the session override points at the test DB. The simulator send test only asserts `{"status": "ok"}` — delivery against dev DB rows is a no-op because the outbox row exists in the test DB only (delivery finds no row and returns silently). Manual smoke testing with uvicorn exercises true delivery.

- [ ] **Step 4: Write `apps/simulator/static/index.html`** — single-page WhatsApp-style chat UI (inline CSS+JS): header bar, config row (your phone / restaurant phone inputs), scrollable message area (inbound right-aligned green bubbles, outbound white), textarea + send button, `POST /simulator/send` on send, poll `GET /simulator/messages` every 3s plus 300ms/1200ms after each send, errors shown in a status strip. No build step, no external assets.

(Implementer: write reasonable clean HTML/CSS/JS matching this description, ~120 lines.)

- [ ] **Step 5: Create `apps/simulator/__init__.py`** (empty) and mount in `src/app/main.py`:

```python
from app.config import get_settings
# inside create_app(), after other routers:
    settings = get_settings()
    if settings.whatsapp_provider == "mock":
        from apps.simulator.router import router as simulator_router

        app.include_router(simulator_router)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests/test_simulator.py -v`
Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add apps/simulator tests/test_simulator.py src/app/main.py
git commit -m "feat: web simulator — chat UI driving the full pipeline via MockProvider"
```

---

### Task 14: Full suite + smoke test

- [ ] **Step 1: Run full suite**

Run: `.venv/bin/pytest -v`
Expected: all PASS

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check src apps tests`
Expected: clean

- [ ] **Step 3: Boot server smoke test**

```bash
.venv/bin/uvicorn app.main:app --port 8000 &
sleep 2
curl -s http://localhost:8000/health
curl -s "http://localhost:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=dev-verify-token&hub.challenge=TESTCHALLENGE"
kill %1
```
Expected: `{"status":"ok"}` then `TESTCHALLENGE`

- [ ] **Step 4: Manual simulator smoke** — `uvicorn app.main:app --port 8000`, open http://localhost:8000/simulator/, send "hi" → bot replies with menu.

- [ ] **Step 5: Commit any lint fixes**

```bash
git add -A && git commit -m "chore: Phase 2 lint fixes and smoke test" || echo "nothing to fix"
```

---

## Open design notes (controller review before execution)

1. **MockProvider singleton across processes** — `@lru_cache` singleton works within one uvicorn process only; run dev server single-worker.
2. **Celery async bridging** — `deliver_outbox_message` uses `asyncio.run`; fine for sync Celery worker, revisit if moving to async pool.
3. **Restaurant lookup by WABA phone** — requires restaurants to sign up with the WABA number Meta reports in metadata.display_phone_number. Consistent with spec.
4. **Engine imports menu models lazily** inside `_render_menu` — avoids circular imports; Phase 0+1 must be complete first.
5. **Simulator delivery in tests** is a no-op (dev-DB session factory vs test DB) — asserted via status only; true delivery verified by manual smoke + outbox worker unit tests.

## Post-phase

Phase 2 done = WhatsApp fully wired: inbound → signature check (cloud) → idempotency gate → conversation engine → outbox → Celery delivery → Mock/Cloud provider. Greeting renders the live digital menu. Manual takeover silences bot. Simulator = chat without a phone.

Next plan: **Phase 3 — Ordering** (fuzzy dish matching, dialogue through order confirmation, address capture/confirm/store, order FSM, modification, cancellation/resale).
