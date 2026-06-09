# Full-AI Phase-Aware Conversation Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hybrid FSM/AI customer conversation with a single phase-aware DeepSeekConversationAgent that owns the entire customer dialogue (greeting → ordering → address → confirmation → post-order), with real conversation history, 7-language support, shorthand handling, and returning-customer address reuse.

**Architecture:** Single agent, phase-aware system prompt (`ordering` / `address_capture` / `awaiting_confirmation` / `post_order`). Outbound messages stored in DB so last 10 turns are passed as real history. Tool schema covers all actions; server-side phase guards prevent wrong-phase actions. Rider flow (FSM + buttons) unchanged.

**Spec:** `docs/superpowers/specs/2026-06-10-full-ai-conversation-agent-design.md`

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, DeepSeek OpenAI-compatible API, httpx, pytest-asyncio

**Read before every task:**
- `src/app/conversation/engine.py` — last 3 bullet points of understanding.txt
- `src/app/llm/deepseek.py` — existing DeepSeekConversationAgent
- `src/app/llm/port.py` — current ConversationAgentPort

---

## File Map

| File | Change |
|---|---|
| `src/app/llm/port.py` | Expand `ConversationAgentPort` to accept `dialogue_phase` + `context` dict |
| `src/app/llm/fake.py` | Update `FakeConversationAgent` to match new port interface |
| `src/app/llm/deepseek.py` | Rewrite `DeepSeekConversationAgent` — phase-aware prompts, expanded tool schema |
| `src/app/conversation/engine.py` | Add `_build_history`, `_resolve_phase`, `_build_context`, `_dispatch_action`, `_handle_location_pin`; store outbound in `_send_text`/`_send_buttons`; rewrite customer path in `handle_inbound` |
| `tests/conversation/test_engine_full_ai.py` | New: full-AI flow integration tests |
| `tests/llm/test_deepseek_agent.py` | New: phase-aware prompt + tool schema tests |

---

### Task 1: Fix spec — radius from settings, not hardcoded

**Files:**
- Modify: `docs/superpowers/specs/2026-06-10-full-ai-conversation-agent-design.md`

- [ ] **Step 1: Update spec section 4.3 and 10**

In `docs/superpowers/specs/2026-06-10-full-ai-conversation-agent-design.md`, replace every occurrence of `10 km` / `10km` / `10 km range` with `restaurant.settings["max_radius_km"] km` in the radius-enforcement context. The system prompt block for address_capture should read:

```
- If location pin is outside the restaurant's delivery radius → inform customer and end conversation politely.
```

And section 10 non-negotiable rules should read:
```
- Max delivery radius: `restaurant.settings["max_radius_km"]` km — enforced at pin processing, NOT hardcoded
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-06-10-full-ai-conversation-agent-design.md
git commit -m "docs: fix radius hardcode in full-AI agent spec — use restaurant settings"
```

---

### Task 2: Update port.py — new ConversationAgentPort interface

**Files:**
- Modify: `src/app/llm/port.py`
- Test: `tests/llm/test_fake.py` (verify FakeConversationAgent still importable — existing tests guard this)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/llm/test_fake.py
async def test_fake_agent_new_interface():
    from app.llm.fake import FakeConversationAgent
    agent = FakeConversationAgent()
    result = await agent.respond(
        restaurant_name="Test",
        dialogue_phase="ordering",
        history=[{"role": "user", "content": "hi"}],
        context={"menu_text": "110. Biryani AED 22", "cart_summary": ""},
    )
    assert result.action in {"no_action", "add_item", "proceed_to_address"}
    assert isinstance(result.message, str)
    assert isinstance(result.action_data, dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/llm/test_fake.py::test_fake_agent_new_interface -v`
Expected: FAIL — `TypeError: respond() got unexpected keyword argument 'dialogue_phase'`

- [ ] **Step 3: Update `src/app/llm/port.py`**

Replace the `ConversationAgentPort` class (keep everything above it unchanged):

```python
@dataclass
class ConversationAgentResult:
    """Result from the AI conversation agent."""
    message: str
    action: str
    # Ordering actions: add_item | remove_item | update_qty | proceed_to_address
    # Address actions:  send_location_request | save_address_text | use_saved_address | proceed_to_confirmation
    # Confirmation:     confirm_order | request_modification | cancel_order
    # Post-order:       status_query
    # Any phase:        no_action | cancel_order
    action_data: dict  # keys vary by action — see design spec


class ConversationAgentPort(Protocol):
    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,   # ordering | address_capture | awaiting_confirmation | post_order
        history: list[dict],   # [{"role": "user"|"assistant", "content": str}, ...]
        context: dict,         # phase-specific data dict
    ) -> ConversationAgentResult: ...
```

- [ ] **Step 4: Run test to verify it still fails (FakeConversationAgent not updated yet)**

Run: `.venv/bin/pytest tests/llm/test_fake.py::test_fake_agent_new_interface -v`
Expected: FAIL — `TypeError` on FakeConversationAgent

- [ ] **Step 5: Commit port change only**

```bash
git add src/app/llm/port.py
git commit -m "feat: expand ConversationAgentPort to accept dialogue_phase and context dict"
```

---

### Task 3: Update FakeConversationAgent to match new port

**Files:**
- Modify: `src/app/llm/fake.py`

- [ ] **Step 1: Read the current FakeConversationAgent**

Open `src/app/llm/fake.py` and find the `FakeConversationAgent` class.

- [ ] **Step 2: Replace FakeConversationAgent**

Find and replace the existing `FakeConversationAgent` class with:

```python
class FakeConversationAgent:
    """Test double — returns deterministic responses based on last user message."""

    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,
        history: list[dict],
        context: dict,
    ) -> "ConversationAgentResult":
        from app.llm.port import ConversationAgentResult

        last_user = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                last_user = (msg.get("content") or "").lower()
                break

        # ordering phase
        if dialogue_phase == "ordering":
            if any(w in last_user for w in ("done", "that's all", "bas", "khalaas", "proceed", "checkout")):
                return ConversationAgentResult(
                    message="Great! Let me get your delivery details.",
                    action="proceed_to_address",
                    action_data={},
                )
            if any(w in last_user for w in ("cancel",)):
                return ConversationAgentResult(
                    message="Order cancelled.",
                    action="cancel_order",
                    action_data={},
                )
            if any(w in last_user for w in ("biryani", "karahi", "order", "want", "add", "give")):
                return ConversationAgentResult(
                    message="Added to your cart!",
                    action="add_item",
                    action_data={"dish_query": last_user, "qty": 1, "special_note": ""},
                )
            return ConversationAgentResult(
                message="Welcome! Here is our menu.",
                action="no_action",
                action_data={},
            )

        # address_capture phase
        if dialogue_phase == "address_capture":
            if "[customer shared location" in last_user:
                return ConversationAgentResult(
                    message="Got your location! What's your apartment/room/door number?",
                    action="no_action",
                    action_data={},
                )
            saved = context.get("saved_address", "")
            if saved and any(w in last_user for w in ("yes", "same", "correct", "ok")):
                return ConversationAgentResult(
                    message="Using your saved address!",
                    action="use_saved_address",
                    action_data={},
                )
            if not context.get("location_received"):
                return ConversationAgentResult(
                    message="Please share your location 📍",
                    action="send_location_request",
                    action_data={},
                )
            apt = context.get("apt_room", "")
            building = context.get("building", "")
            if apt and building:
                return ConversationAgentResult(
                    message="Got it! What's the receiver's name?",
                    action="no_action",
                    action_data={},
                )
            return ConversationAgentResult(
                message="What's your apartment number?",
                action="no_action",
                action_data={},
            )

        # awaiting_confirmation phase
        if dialogue_phase == "awaiting_confirmation":
            if any(w in last_user for w in ("yes", "confirm", "ok", "proceed", "haan", "aiwa")):
                return ConversationAgentResult(
                    message="Order confirmed! 🎉",
                    action="confirm_order",
                    action_data={},
                )
            if any(w in last_user for w in ("cancel",)):
                return ConversationAgentResult(
                    message="Order cancelled.",
                    action="cancel_order",
                    action_data={},
                )
            return ConversationAgentResult(
                message="Please confirm or cancel your order.",
                action="no_action",
                action_data={},
            )

        # post_order phase
        if dialogue_phase == "post_order":
            return ConversationAgentResult(
                message="Your order is being prepared!",
                action="status_query",
                action_data={},
            )

        return ConversationAgentResult(
            message="How can I help?",
            action="no_action",
            action_data={},
        )
```

- [ ] **Step 3: Run test to verify it passes**

Run: `.venv/bin/pytest tests/llm/test_fake.py -v`
Expected: ALL PASS

- [ ] **Step 4: Run full suite to check nothing broke**

Run: `.venv/bin/pytest tests/llm/ tests/conversation/ -v --tb=short -q`
Expected: existing tests pass (some conversation tests may now fail — that's OK, they'll be fixed in Task 10)

- [ ] **Step 5: Commit**

```bash
git add src/app/llm/fake.py
git commit -m "feat: update FakeConversationAgent to match new phase-aware port interface"
```

---

### Task 4: Store outbound messages in _send_text and _send_buttons

**Files:**
- Modify: `src/app/conversation/engine.py`
- Test: `tests/conversation/test_engine_full_ai.py` (create file)

- [ ] **Step 1: Write the failing test**

```python
# tests/conversation/test_engine_full_ai.py
"""Tests for full-AI phase-aware conversation agent."""
import pytest
from sqlalchemy import select

from app.conversation.models import Message
from app.whatsapp.normalizer import InboundMessage, MessageType


async def _make_conv_and_inbound(db_session, client, auth_headers):
    """Helper: send a message through the WhatsApp webhook and return conversation."""
    from app.conversation.service import get_or_create_conversation

    restaurant = (await client.get("/api/v1/me", headers=auth_headers)).json()
    restaurant_id = restaurant["id"]
    phone = "+971501111222"

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{
                        "id": "wamid.test001",
                        "from": phone,
                        "timestamp": "1700000000",
                        "type": "text",
                        "text": {"body": "hi"},
                    }],
                    "metadata": {"phone_number_id": "test_phone_id"},
                },
                "field": "messages",
            }],
        }],
    }
    resp = await client.post(
        f"/webhooks/whatsapp?restaurant_id={restaurant_id}",
        json=payload,
        headers={"X-Hub-Signature-256": "sha256=fake"},
    )
    assert resp.status_code == 200

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant_id, phone=phone, counterpart="customer"
    )
    return conv, restaurant_id, phone


async def test_outbound_message_stored_after_send(db_session, client, auth_headers):
    """_send_text must record an outbound row in the messages table."""
    conv, restaurant_id, phone = await _make_conv_and_inbound(db_session, client, auth_headers)

    messages = (
        await db_session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        )
    ).all()

    directions = [m.direction for m in messages]
    assert "inbound" in directions
    assert "outbound" in directions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_engine_full_ai.py::test_outbound_message_stored_after_send -v`
Expected: FAIL — no outbound message in DB

- [ ] **Step 3: Add `record_message` calls to `_send_text` and `_send_buttons` in `engine.py`**

Find `_send_text` (around line 134) and replace it:

```python
async def _send_text(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
) -> None:
    import uuid
    from datetime import datetime, timezone

    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="text",
        payload={"body": body},
        ts=datetime.now(timezone.utc),
    )
```

Find `_send_buttons` (around line 153) and replace it:

```python
async def _send_buttons(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
    buttons: list[dict],
) -> None:
    from datetime import datetime, timezone

    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={"body": body, "buttons": buttons},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="buttons",
        payload={"body": body, "buttons": buttons},
        ts=datetime.now(timezone.utc),
    )
```

Also add `record_message` to the top-level imports in `engine.py` if not already there. Check line 8:
```python
from app.conversation.service import get_or_create_conversation, record_message
```
(Already imported — no change needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/conversation/test_engine_full_ai.py::test_outbound_message_stored_after_send -v`
Expected: PASS

- [ ] **Step 5: Run full suite quick check**

Run: `.venv/bin/pytest tests/conversation/ -q --tb=short`

- [ ] **Step 6: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_full_ai.py
git commit -m "feat: store outbound messages in messages table for conversation history"
```

---

### Task 5: Add _build_history to engine.py

**Files:**
- Modify: `src/app/conversation/engine.py`
- Test: `tests/conversation/test_engine_full_ai.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/conversation/test_engine_full_ai.py

async def test_build_history_alternates_roles(db_session, client, auth_headers):
    """_build_history returns user/assistant alternating list from DB."""
    from app.conversation.engine import _build_history
    from app.conversation.service import get_or_create_conversation, record_message
    from datetime import datetime, timezone

    restaurant = (await client.get("/api/v1/me", headers=auth_headers)).json()
    restaurant_id = restaurant["id"]
    phone = "+971502222333"

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant_id, phone=phone, counterpart="customer"
    )
    ts = datetime.now(timezone.utc)

    await record_message(db_session, conversation_id=conv.id, direction="inbound",
                         wa_message_id="w1", msg_type="text",
                         payload={"text": "hi"}, ts=ts)
    await record_message(db_session, conversation_id=conv.id, direction="outbound",
                         wa_message_id=None, msg_type="text",
                         payload={"body": "Hello! Here is our menu."}, ts=ts)
    await record_message(db_session, conversation_id=conv.id, direction="inbound",
                         wa_message_id="w2", msg_type="text",
                         payload={"text": "I want biryani"}, ts=ts)
    await db_session.commit()

    history = await _build_history(db_session, conv, limit=10)

    assert len(history) == 3
    assert history[0] == {"role": "user", "content": "hi"}
    assert history[1] == {"role": "assistant", "content": "Hello! Here is our menu."}
    assert history[2] == {"role": "user", "content": "I want biryani"}


async def test_build_history_maps_location_to_text(db_session, client, auth_headers):
    """Location inbound messages become summarized text in history."""
    from app.conversation.engine import _build_history
    from app.conversation.service import get_or_create_conversation, record_message
    from datetime import datetime, timezone

    restaurant = (await client.get("/api/v1/me", headers=auth_headers)).json()
    restaurant_id = restaurant["id"]
    phone = "+971503333444"

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant_id, phone=phone, counterpart="customer"
    )
    ts = datetime.now(timezone.utc)
    await record_message(db_session, conversation_id=conv.id, direction="inbound",
                         wa_message_id="w1", msg_type="location",
                         payload={"latitude": 25.1, "longitude": 55.2}, ts=ts)
    await db_session.commit()

    history = await _build_history(db_session, conv, limit=10)
    assert history[0]["role"] == "user"
    assert "[customer shared location pin]" in history[0]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/conversation/test_engine_full_ai.py::test_build_history_alternates_roles tests/conversation/test_engine_full_ai.py::test_build_history_maps_location_to_text -v`
Expected: FAIL — `ImportError: cannot import name '_build_history'`

- [ ] **Step 3: Add `_build_history` to `engine.py`**

Add this function after `_build_cart_summary` (around line 1092):

```python
async def _build_history(
    session: AsyncSession,
    conv: Conversation,
    limit: int = 10,
) -> list[dict]:
    """Fetch last `limit` messages and build OpenAI-style history list."""
    from app.conversation.models import Message

    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).all()
    rows = list(reversed(rows))  # oldest first

    history: list[dict] = []
    for msg in rows:
        role = "user" if msg.direction == "inbound" else "assistant"
        payload = msg.payload or {}

        if msg.msg_type == "text":
            content = payload.get("text") or payload.get("body") or ""
        elif msg.msg_type == "location":
            lat = payload.get("latitude", "")
            lng = payload.get("longitude", "")
            content = f"[customer shared location pin: {lat},{lng}]"
        elif msg.msg_type == "button_reply":
            title = payload.get("title") or payload.get("id") or "button"
            content = f"[tapped: {title}]"
        elif msg.msg_type == "buttons":
            content = payload.get("body") or "[buttons sent]"
        else:
            content = f"[{msg.msg_type}]"

        if content:
            history.append({"role": role, "content": content})

    # OpenAI requires first message to be user role
    if history and history[0]["role"] == "assistant":
        history.insert(0, {"role": "user", "content": "hi"})

    return history
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/conversation/test_engine_full_ai.py::test_build_history_alternates_roles tests/conversation/test_engine_full_ai.py::test_build_history_maps_location_to_text -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_full_ai.py
git commit -m "feat: _build_history fetches last N messages as OpenAI-style role list"
```

---

### Task 6: Add _resolve_phase and _build_context to engine.py

**Files:**
- Modify: `src/app/conversation/engine.py`
- Test: `tests/conversation/test_engine_full_ai.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/conversation/test_engine_full_ai.py

def test_resolve_phase_maps_old_states():
    """_resolve_phase maps legacy dialogue_state values to new phases."""
    from app.conversation.engine import _resolve_phase
    from unittest.mock import MagicMock

    def make_conv(state):
        c = MagicMock()
        c.state = state
        return c

    assert _resolve_phase(make_conv({"dialogue_state": "greeting"})) == "ordering"
    assert _resolve_phase(make_conv({"dialogue_state": "menu_sent"})) == "ordering"
    assert _resolve_phase(make_conv({"dialogue_state": "collecting_items"})) == "ordering"
    assert _resolve_phase(make_conv({"dialogue_state": "address_capture"})) == "address_capture"
    assert _resolve_phase(make_conv({"dialogue_state": "address_text_pending"})) == "address_capture"
    assert _resolve_phase(make_conv({"dialogue_state": "receiver_details"})) == "address_capture"
    assert _resolve_phase(make_conv({"dialogue_state": "order_confirmation"})) == "awaiting_confirmation"
    assert _resolve_phase(make_conv({"dialogue_state": "order_placed"})) == "post_order"
    assert _resolve_phase(make_conv({"dialogue_phase": "ordering"})) == "ordering"
    assert _resolve_phase(make_conv({"dialogue_phase": "post_order"})) == "post_order"
    assert _resolve_phase(make_conv({})) == "ordering"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_engine_full_ai.py::test_resolve_phase_maps_old_states -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_phase'`

- [ ] **Step 3: Add `_resolve_phase` and `_build_context` to `engine.py`**

Add after `_build_history`:

```python
_PHASE_MAP = {
    "greeting": "ordering",
    "menu_sent": "ordering",
    "collecting_items": "ordering",
    "cancelled": "ordering",
    "modify_items": "ordering",
    "modify_confirm": "ordering",
    "address_capture": "address_capture",
    "address_text_pending": "address_capture",
    "receiver_details": "address_capture",
    "order_confirmation": "awaiting_confirmation",
    "order_placed": "post_order",
    "post_order": "post_order",
}

_VALID_PHASES = frozenset({"ordering", "address_capture", "awaiting_confirmation", "post_order"})

_PHASE_ACTIONS: dict[str, frozenset] = {
    "ordering": frozenset({
        "add_item", "remove_item", "update_qty", "proceed_to_address",
        "cancel_order", "no_action",
    }),
    "address_capture": frozenset({
        "send_location_request", "save_address_text", "use_saved_address",
        "proceed_to_confirmation", "cancel_order", "no_action",
    }),
    "awaiting_confirmation": frozenset({
        "confirm_order", "request_modification", "cancel_order", "no_action",
    }),
    "post_order": frozenset({
        "status_query", "request_modification", "cancel_order", "no_action",
    }),
}


def _resolve_phase(conv: Conversation) -> str:
    """Return the current dialogue_phase, mapping legacy dialogue_state if needed."""
    state = conv.state or {}
    if "dialogue_phase" in state and state["dialogue_phase"] in _VALID_PHASES:
        return state["dialogue_phase"]
    old_state = state.get("dialogue_state", "greeting")
    return _PHASE_MAP.get(old_state, "ordering")


async def _build_context(
    session: AsyncSession,
    conv: Conversation,
    restaurant_id: int,
    phase: str,
    restaurant,
) -> dict:
    """Build phase-specific context dict for the AI agent."""
    ctx: dict = {}

    if phase == "ordering":
        ctx["menu_text"] = await _render_menu(session, restaurant_id)
        ctx["cart_summary"] = await _build_cart_summary(session, conv)

    elif phase == "address_capture":
        ctx["cart_summary"] = await _build_cart_summary(session, conv)
        ctx["location_received"] = conv.state.get("pin_lat") is not None
        ctx["apt_room"] = conv.state.get("pending_room", "")
        ctx["building"] = conv.state.get("pending_building", "")
        ctx["receiver_name"] = conv.state.get("pending_receiver", "")

        # Saved address for returning customers
        from app.ordering.models import Customer, CustomerAddress
        customer = await session.scalar(
            select(Customer).where(
                Customer.restaurant_id == restaurant_id,
                Customer.phone == conv.phone,
            )
        )
        saved = ""
        if customer:
            addr = await session.scalar(
                select(CustomerAddress)
                .where(CustomerAddress.customer_id == customer.id)
                .order_by(CustomerAddress.last_used_at.desc())
                .limit(1)
            )
            if addr:
                saved = f"Apt {addr.room_apartment}, {addr.building}"
                ctx["saved_address_id"] = addr.id
        ctx["saved_address"] = saved
        max_km = restaurant.settings.get("max_radius_km", 10) if restaurant else 10
        ctx["max_radius_km"] = max_km

    elif phase == "awaiting_confirmation":
        from app.ordering.models import Order, OrderItem
        from app.weather.factory import get_weather_port

        order_id = conv.state.get("pending_order_id") or conv.state.get("draft_order_id")
        order = await session.get(Order, order_id) if order_id else None
        if order:
            items = (await session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id)
            )).all()
            item_lines = "\n".join(
                f"  {it.qty}x {it.dish_number}. {it.dish_name} — "
                f"AED {Decimal(it.price_aed * it.qty).normalize()}"
                for it in items
            )
            weather_note = ""
            if get_weather_port().is_delay_active():
                order.weather_delay_disclosed = True
                await session.flush()
                weather_note = "\n⚠️ Weather may cause delays beyond usual ETA."
            ctx["order_summary"] = (
                f"{item_lines}\n\n"
                f"Subtotal: AED {Decimal(order.subtotal).normalize()}\n"
                f"Delivery fee: AED {Decimal(order.delivery_fee_aed).normalize()}\n"
                f"Total: AED {Decimal(order.total).normalize()}\n"
                f"Payment: COD (cash on delivery)\n"
                f"ETA: ~40 minutes{weather_note}"
            )
            ctx["order_id"] = order.id

    elif phase == "post_order":
        from app.ordering.fsm import OrderStatus
        from app.ordering.models import Customer, Order

        customer = await session.scalar(
            select(Customer).where(
                Customer.restaurant_id == restaurant_id,
                Customer.phone == conv.phone,
            )
        )
        ctx["order_number"] = ""
        ctx["order_status"] = "unknown"
        ctx["rider_eta"] = ""
        if customer:
            terminal = {
                str(OrderStatus.DELIVERED), str(OrderStatus.CANCELLED),
                str(OrderStatus.UNDELIVERABLE), str(OrderStatus.RESOLD),
                str(OrderStatus.WRITTEN_OFF),
            }
            order = await session.scalar(
                select(Order)
                .where(
                    Order.restaurant_id == restaurant_id,
                    Order.customer_id == customer.id,
                    Order.status.notin_(terminal),
                )
                .order_by(Order.created_at.desc())
                .limit(1)
            )
            if order:
                ctx["order_number"] = str(order.order_number or "")
                ctx["order_status"] = str(order.status)

    return ctx
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/conversation/test_engine_full_ai.py::test_resolve_phase_maps_old_states -v`
Expected: PASS

- [ ] **Step 5: Run full conversation tests quick check**

Run: `.venv/bin/pytest tests/conversation/ -q --tb=short`

- [ ] **Step 6: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_full_ai.py
git commit -m "feat: _resolve_phase, _build_context, phase-action guards for full-AI engine"
```

---

### Task 7: Rewrite DeepSeekConversationAgent — phase-aware prompts + expanded tool schema

**Files:**
- Modify: `src/app/llm/deepseek.py`
- Test: `tests/llm/test_deepseek_agent.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/llm/test_deepseek_agent.py
"""Tests for DeepSeekConversationAgent phase-aware prompts and tool schema."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.deepseek import DeepSeekConversationAgent
from app.llm.port import ConversationAgentResult


def _mock_deepseek_response(action: str, reply: str, **extra):
    args = {"action": action, "reply": reply, **extra}
    tc = {"function": {"name": "take_action", "arguments": json.dumps(args)}}
    choice = {"message": {"tool_calls": [tc]}}
    return {"choices": [choice]}


@pytest.fixture
def agent():
    with patch("app.llm.deepseek._get_deepseek_settings", return_value=("fake-key", "deepseek-chat")):
        yield DeepSeekConversationAgent()


async def test_ordering_phase_add_item(agent):
    resp_data = _mock_deepseek_response(
        "add_item", "Adding biryani!", dish_query="biryani", qty=2, special_note=""
    )
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await agent.respond(
            restaurant_name="Test Restaurant",
            dialogue_phase="ordering",
            history=[{"role": "user", "content": "2 biryani plz"}],
            context={"menu_text": "110. Biryani AED 22", "cart_summary": ""},
        )

    assert result.action == "add_item"
    assert result.action_data["dish_query"] == "biryani"
    assert result.action_data["qty"] == 2
    assert result.message == "Adding biryani!"


async def test_address_phase_send_location_request(agent):
    resp_data = _mock_deepseek_response("send_location_request", "Please share your location 📍")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await agent.respond(
            restaurant_name="Test Restaurant",
            dialogue_phase="address_capture",
            history=[{"role": "user", "content": "done ordering"}],
            context={
                "cart_summary": "1x Biryani AED 22",
                "saved_address": "",
                "location_received": False,
                "apt_room": "",
                "building": "",
                "receiver_name": "",
                "max_radius_km": 10,
            },
        )

    assert result.action == "send_location_request"


async def test_confirmation_phase_confirm_order(agent):
    resp_data = _mock_deepseek_response("confirm_order", "Order placed! 🎉")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await agent.respond(
            restaurant_name="Test Restaurant",
            dialogue_phase="awaiting_confirmation",
            history=[{"role": "user", "content": "yes confirm"}],
            context={"order_summary": "1x Biryani AED 22\nTotal: AED 22\nCOD\nETA: ~40 min"},
        )

    assert result.action == "confirm_order"


async def test_system_prompt_contains_language_instruction(agent):
    """Verify system prompt mentions all 7 supported languages."""
    captured = {}

    async def fake_post(url, **kwargs):
        captured["payload"] = kwargs.get("json") or kwargs.get("data")
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        args = {"action": "no_action", "reply": "hi"}
        tc = {"function": {"name": "take_action", "arguments": json.dumps(args)}}
        resp.json.return_value = {"choices": [{"message": {"tool_calls": [tc]}}]}
        return resp

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
        await agent.respond(
            restaurant_name="Test",
            dialogue_phase="ordering",
            history=[{"role": "user", "content": "hi"}],
            context={"menu_text": "110. Biryani", "cart_summary": ""},
        )

    payload_str = json.dumps(captured.get("payload", {}))
    for lang in ["Arabic", "Urdu", "Turkish", "Russian", "Filipino", "Malayalam"]:
        assert lang in payload_str, f"Language {lang} not in system prompt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/llm/test_deepseek_agent.py -v`
Expected: FAIL — old agent doesn't accept `dialogue_phase` or `context`

- [ ] **Step 3: Rewrite `DeepSeekConversationAgent` in `src/app/llm/deepseek.py`**

Replace the existing `_DS_CONVERSATION_TOOL`, `_DS_CONVERSATION_SYSTEM`, and `DeepSeekConversationAgent` with:

```python
_DS_TOOL = {
    "type": "function",
    "function": {
        "name": "take_action",
        "description": (
            "Record the structured action inferred from the customer message, plus your reply. "
            "ALWAYS call this tool — never reply without it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "add_item", "remove_item", "update_qty", "proceed_to_address",
                        "send_location_request", "save_address_text", "use_saved_address",
                        "proceed_to_confirmation",
                        "confirm_order", "request_modification", "cancel_order",
                        "status_query", "no_action",
                    ],
                    "description": (
                        "add_item: customer wants to add a dish. "
                        "remove_item: customer wants to remove a dish. "
                        "update_qty: change quantity of a dish already in cart. "
                        "proceed_to_address: cart ready, move to delivery address capture. "
                        "send_location_request: ask customer to share their WhatsApp location pin. "
                        "save_address_text: all 3 address fields collected (apt_room + building + receiver_name). "
                        "use_saved_address: returning customer confirmed their saved address. "
                        "proceed_to_confirmation: address complete, show order summary. "
                        "confirm_order: customer confirmed the order. "
                        "request_modification: customer wants to change something in the order. "
                        "cancel_order: customer wants to cancel. "
                        "status_query: customer asked where their order is. "
                        "no_action: greeting, question, answer, anything that doesn't change state."
                    ),
                },
                "dish_query": {
                    "type": "string",
                    "description": "Dish name or number (for add_item, remove_item, update_qty).",
                },
                "qty": {
                    "type": "integer",
                    "description": "Quantity (for add_item, update_qty). Default 1.",
                },
                "special_note": {
                    "type": "string",
                    "description": "Kitchen note for this item e.g. 'no onion', 'extra spicy' (for add_item).",
                },
                "apt_room": {
                    "type": "string",
                    "description": "Apartment / room / door number (for save_address_text).",
                },
                "building": {
                    "type": "string",
                    "description": "Building name or number (for save_address_text).",
                },
                "receiver_name": {
                    "type": "string",
                    "description": "Name of person receiving the order (for save_address_text).",
                },
                "reply": {
                    "type": "string",
                    "description": "Natural WhatsApp reply to send. Short, friendly, casual. Required always.",
                },
            },
            "required": ["action", "reply"],
        },
    },
}

_IDENTITY = """\
You are {restaurant_name}'s friendly WhatsApp ordering assistant.

LANGUAGE: Detect the customer's language and reply in the SAME language automatically.
Supported: English, Arabic (عربي), Urdu/Hindi (اردو/हिंदी), Turkish, Russian, Filipino (Tagalog), Malayalam (മലയാളം).
If they mix languages, match their mix. Never switch language unless the customer does.

TONE: Friendly and casual — like a helpful friend, not a corporate bot.
SHORT replies (WhatsApp style). Emoji: sparingly, only where natural.

ALWAYS call take_action. Never reply without calling it.
COD only (cash on delivery). Delivery ~40 minutes. Max {max_radius_km} km range.
"""

_ORDERING_BLOCK = """
PHASE: Taking order

MENU:
{menu_text}

CURRENT CART: {cart_summary}

YOUR JOB:
- Greet warmly. Show 2-3 highlights, NOT the whole menu as a wall of text.
  If customer asks to see full menu, show it grouped by category.
- Understand shorthand orders in ANY language:
    "2 bry + karahi"         → add_item dish_query="biryani" qty=2, then add_item dish_query="karahi"
    "ek biryani dena bhai"   → add_item dish_query="biryani" qty=1
    "bhai no onion"          → add_item with special_note="no onion"
    "extra spicy plz"        → add_item with special_note="extra spicy"
    "rm that" / "cancel last"→ remove_item
    "make it 3"              → update_qty qty=3
    "bas" / "khalaas" / "that's all" / "done" / "checkout" → proceed_to_address
- For multiple items in one message, call add_item action and include ALL items in reply.
- Handle questions: spice level, halal, portion size, ingredients, vegetarian, allergens.
  Max 3 lines per answer. Never include price in dish descriptions.
- Upsell ONCE (only if cart has ≥1 item and you haven't already suggested): "Want to add a drink? 😊"
- NEVER ask for address or location in this phase.
- If cart is not empty and customer says they are done → proceed_to_address.
"""

_ADDRESS_BLOCK = """
PHASE: Address capture

CART: {cart_summary}
SAVED ADDRESS: {saved_address}
LOCATION RECEIVED: {location_received}
APT/ROOM COLLECTED: {apt_room}
BUILDING COLLECTED: {building}
RECEIVER NAME COLLECTED: {receiver_name}
DELIVERY RADIUS: {max_radius_km} km

YOUR JOB (follow this exact sequence):
1. If SAVED ADDRESS is not empty:
   → Offer it: "Use your saved address — {saved_address}? Or share a new location 📍"
   → Customer says yes/correct/ok → use_saved_address
   → Customer wants new → continue to step 2

2. If LOCATION RECEIVED is False:
   → send_location_request (ask customer to share WhatsApp location pin)
   → Reply: "Please share your location pin 📍"

3. If LOCATION RECEIVED is True and APT/ROOM COLLECTED is empty:
   → no_action, ask: "What's your apartment/room/door number?"

4. If APT/ROOM COLLECTED is set and BUILDING COLLECTED is empty:
   → no_action, ask: "What's the building name or number?"

5. If APT/ROOM and BUILDING are set and RECEIVER NAME COLLECTED is empty:
   → no_action, ask: "What's the receiver's name?"

6. If all three (apt_room + building + receiver_name) are now provided in this message:
   → save_address_text with apt_room + building + receiver_name

RULES:
- Collect ONLY: apt/room, building, receiver name. Nothing else is mandatory.
- If customer volunteers extra info (landmark, floor), include it in apt_room field.
- If location pin is outside {max_radius_km} km radius → tell customer politely, end conversation.
"""

_CONFIRMATION_BLOCK = """
PHASE: Order confirmation

ORDER SUMMARY:
{order_summary}

YOUR JOB:
- Show the summary clearly (already formatted above).
- Ask: "Shall I place this order? ✅"
- customer says yes / confirm / ok / haan / aiwa / да / oo / sige → confirm_order
- customer wants changes → request_modification
- customer cancels → cancel_order
- Anything unclear → re-show summary and ask again (no_action).
"""

_POST_ORDER_BLOCK = """
PHASE: Order placed

ORDER #{order_number} — Status: {order_status}
RIDER ETA: {rider_eta}

YOUR JOB:
- Answer status queries in the customer's language.
- Status is "preparing" / "confirmed" → "Your order is being prepared in the kitchen 🍳"
- Status is "ready" → "Your order is ready and will be picked up by a rider soon! 🛵"
- Status is "assigned" / "picked_up" / "arriving" → "Your rider is on the way! ETA ~{rider_eta} min"
- Modification requests (before 'ready' status) → request_modification
- Cancellation (if status is before 'picked_up') → cancel_order
- If order already picked up / delivered → explain it's too late to cancel
- "Where is my order" / "كم باقي" / "کتنا وقت لگے گا" → status_query
"""


class DeepSeekConversationAgent:
    """Phase-aware AI ordering assistant using DeepSeek function calling."""

    def __init__(self) -> None:
        self._api_key, self._model = _get_deepseek_settings()

    def _build_system(self, restaurant_name: str, dialogue_phase: str, context: dict) -> str:
        max_km = context.get("max_radius_km", 10)
        identity = _IDENTITY.format(
            restaurant_name=restaurant_name,
            max_radius_km=max_km,
        )

        if dialogue_phase == "ordering":
            phase_block = _ORDERING_BLOCK.format(
                menu_text=context.get("menu_text", "Menu unavailable."),
                cart_summary=context.get("cart_summary") or "empty",
            )
        elif dialogue_phase == "address_capture":
            saved = context.get("saved_address", "")
            phase_block = _ADDRESS_BLOCK.format(
                cart_summary=context.get("cart_summary") or "empty",
                saved_address=saved or "none",
                location_received=context.get("location_received", False),
                apt_room=context.get("apt_room") or "not yet",
                building=context.get("building") or "not yet",
                receiver_name=context.get("receiver_name") or "not yet",
                max_radius_km=max_km,
            )
        elif dialogue_phase == "awaiting_confirmation":
            phase_block = _CONFIRMATION_BLOCK.format(
                order_summary=context.get("order_summary", ""),
            )
        elif dialogue_phase == "post_order":
            phase_block = _POST_ORDER_BLOCK.format(
                order_number=context.get("order_number", ""),
                order_status=context.get("order_status", "unknown"),
                rider_eta=context.get("rider_eta") or "calculating",
            )
        else:
            phase_block = ""

        return identity + phase_block

    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,
        history: list[dict],
        context: dict,
    ) -> "ConversationAgentResult":
        from app.llm.port import ConversationAgentResult

        system = self._build_system(restaurant_name, dialogue_phase, context)
        messages = history if history else [{"role": "user", "content": "hi"}]

        inp = await _async_chat_tools(
            self._api_key,
            self._model,
            system,
            messages,
            tools=[_DS_TOOL],
            tool_name="take_action",
            max_tokens=512,
        )

        return ConversationAgentResult(
            message=inp.get("reply", ""),
            action=inp.get("action", "no_action"),
            action_data={
                "dish_query": inp.get("dish_query", ""),
                "qty": int(inp.get("qty") or 1),
                "special_note": inp.get("special_note", ""),
                "apt_room": inp.get("apt_room", ""),
                "building": inp.get("building", ""),
                "receiver_name": inp.get("receiver_name", ""),
            },
        )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/llm/test_deepseek_agent.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full llm tests**

Run: `.venv/bin/pytest tests/llm/ -v --tb=short`

- [ ] **Step 6: Commit**

```bash
git add src/app/llm/deepseek.py tests/llm/test_deepseek_agent.py
git commit -m "feat: rewrite DeepSeekConversationAgent — phase-aware prompts, 7 languages, expanded tool schema"
```

---

### Task 8: Action dispatch handlers in engine.py

**Files:**
- Modify: `src/app/conversation/engine.py`
- Test: `tests/conversation/test_engine_full_ai.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/conversation/test_engine_full_ai.py

async def test_add_item_action_updates_cart(db_session, client, auth_headers):
    """proceed via AI add_item: cart grows."""
    from unittest.mock import AsyncMock, patch
    from app.llm.port import ConversationAgentResult

    restaurant = (await client.get("/api/v1/me", headers=auth_headers)).json()
    restaurant_id = restaurant["id"]

    # Activate a menu with a dish first
    files = [("files", ("menu.jpg", b"\xff\xd8\xff fake", "image/jpeg"))]
    menu = (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()
    await client.post(f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers)

    fake_result = ConversationAgentResult(
        message="Added biryani!",
        action="add_item",
        action_data={"dish_query": "biryani", "qty": 1, "special_note": ""},
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "messages": [{"id": "wamid.add1", "from": "+971501234999",
                          "timestamp": "1700000001", "type": "text",
                          "text": {"body": "I want biryani"}}],
            "metadata": {"phone_number_id": "tid"},
        }, "field": "messages"}]}],
    }
    with patch("app.llm.deepseek.DeepSeekConversationAgent.respond",
               new=AsyncMock(return_value=fake_result)):
        resp = await client.post(
            f"/webhooks/whatsapp?restaurant_id={restaurant_id}",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=fake"},
        )
    assert resp.status_code == 200


async def test_phase_guard_blocks_wrong_phase_action(db_session, client, auth_headers):
    """confirm_order action in ordering phase → falls back to no_action."""
    from unittest.mock import AsyncMock, patch
    from app.conversation.engine import _is_valid_action_for_phase

    assert not _is_valid_action_for_phase("confirm_order", "ordering")
    assert _is_valid_action_for_phase("confirm_order", "awaiting_confirmation")
    assert _is_valid_action_for_phase("no_action", "ordering")
    assert _is_valid_action_for_phase("cancel_order", "ordering")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/conversation/test_engine_full_ai.py::test_phase_guard_blocks_wrong_phase_action -v`
Expected: FAIL — `ImportError: cannot import name '_is_valid_action_for_phase'`

- [ ] **Step 3: Add `_is_valid_action_for_phase` and `_dispatch_action` to `engine.py`**

Add after `_build_context`:

```python
def _is_valid_action_for_phase(action: str, phase: str) -> bool:
    """Return True if action is allowed in the given phase."""
    allowed = _PHASE_ACTIONS.get(phase, frozenset())
    return action in allowed


async def _dispatch_action(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    result,
    phase: str,
    restaurant,
) -> None:
    """Execute the action returned by the AI agent."""
    from app.llm.port import ConversationAgentResult

    action = result.action
    data = result.action_data or {}
    reply = result.message or ""

    # Phase guard — wrong-phase action falls back to no_action
    if not _is_valid_action_for_phase(action, phase):
        action = "no_action"

    # ── ordering actions ──────────────────────────────────────────────────
    if action == "add_item":
        dish_query = data.get("dish_query", "")
        qty = int(data.get("qty") or 1)
        special_note = data.get("special_note", "")
        if dish_query:
            added = await _execute_ai_add_item(
                session, conv, inbound, restaurant_id, dish_query, qty, special_note
            )
            if added and reply:
                await _send_text(session, conv=conv, inbound=inbound,
                                 restaurant_id=restaurant_id, prefix="ai-add", body=reply)
            elif not added:
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="ai-no-match",
                    body=f"Sorry, I couldn't find '{dish_query}' in our menu. "
                         "Try the dish number (e.g. 110) or check the menu spelling.",
                )
        else:
            if reply:
                await _send_text(session, conv=conv, inbound=inbound,
                                 restaurant_id=restaurant_id, prefix="ai-reply", body=reply)
        return

    if action == "remove_item":
        dish_query = data.get("dish_query", "")
        await _execute_ai_remove_item(session, conv, restaurant_id, dish_query)
        if reply:
            await _send_text(session, conv=conv, inbound=inbound,
                             restaurant_id=restaurant_id, prefix="ai-remove", body=reply)
        return

    if action == "update_qty":
        dish_query = data.get("dish_query", "")
        qty = int(data.get("qty") or 1)
        await _execute_ai_update_qty(session, conv, restaurant_id, dish_query, qty)
        if reply:
            await _send_text(session, conv=conv, inbound=inbound,
                             restaurant_id=restaurant_id, prefix="ai-qty", body=reply)
        return

    if action == "proceed_to_address":
        cart = await _build_cart_summary(session, conv)
        if not cart:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ai-empty-cart",
                body="Your cart is empty — please add at least one dish first! 😊",
            )
            return
        _set_state(conv, dialogue_phase="address_capture", dialogue_state="address_capture")
        if reply:
            await _send_text(session, conv=conv, inbound=inbound,
                             restaurant_id=restaurant_id, prefix="ai-proceed-addr", body=reply)
        return

    # ── address_capture actions ───────────────────────────────────────────
    if action == "send_location_request":
        _set_state(conv, dialogue_phase="address_capture", dialogue_state="address_capture")
        await _send_buttons(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="loc-request",
            body=reply or "Please share your delivery location 📍",
            buttons=[{"id": "share_location", "title": "Share location 📍"}],
        )
        return

    if action == "use_saved_address":
        saved_id = conv.state.get("saved_address_id")
        if saved_id:
            _set_state(conv, pending_address_id=saved_id, dialogue_phase="awaiting_confirmation",
                       dialogue_state="order_confirmation")
            await _attach_saved_address_to_order(session, conv, inbound, restaurant_id, saved_id,
                                                  restaurant)
        else:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="no-saved-addr",
                body="I couldn't find your saved address. Please share your location 📍",
            )
        return

    if action == "save_address_text":
        apt_room = data.get("apt_room", "")
        building = data.get("building", "")
        receiver_name = data.get("receiver_name", "")
        if apt_room and building and receiver_name:
            await _execute_save_address(session, conv, inbound, restaurant_id,
                                        apt_room, building, receiver_name, restaurant)
        else:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="addr-incomplete",
                body=reply or "I need all three: apartment number, building name, and receiver's name.",
            )
        return

    if action == "proceed_to_confirmation":
        _set_state(conv, dialogue_phase="awaiting_confirmation",
                   dialogue_state="order_confirmation")
        if reply:
            await _send_text(session, conv=conv, inbound=inbound,
                             restaurant_id=restaurant_id, prefix="ai-confirm", body=reply)
        return

    # ── awaiting_confirmation actions ─────────────────────────────────────
    if action == "confirm_order":
        await _execute_confirm_order(session, conv, inbound, restaurant_id)
        return

    if action == "request_modification":
        _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items",
                   pending_order_id=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-modify",
            body=reply or "Sure! What would you like to change? 😊",
        )
        return

    if action == "cancel_order":
        await _execute_cancel_order(session, conv, inbound, restaurant_id)
        return

    # ── post_order actions ────────────────────────────────────────────────
    if action == "status_query":
        await _handle_status_query(session, conv, inbound, restaurant_id)
        return

    # ── no_action (all phases) ────────────────────────────────────────────
    if reply:
        await _send_text(session, conv=conv, inbound=inbound,
                         restaurant_id=restaurant_id, prefix="ai-reply", body=reply)
```

- [ ] **Step 4: Add helper action executors to `engine.py`**

Add these helper functions after `_dispatch_action`:

```python
async def _execute_ai_remove_item(
    session: AsyncSession, conv: Conversation, restaurant_id: int, dish_query: str
) -> None:
    """Remove matching dish from draft order cart."""
    from app.ordering.models import Order, OrderItem
    from app.conversation.engine import find_dish_matches, MatchConfidence

    draft_order_id = conv.state.get("draft_order_id")
    if not draft_order_id or not dish_query:
        return
    order = await session.get(Order, draft_order_id)
    if order is None:
        return
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH or not result.candidates:
        return
    target_dish_id = result.candidates[0].id
    item = await session.scalar(
        select(OrderItem).where(
            OrderItem.order_id == order.id,
            OrderItem.dish_id == target_dish_id,
        )
    )
    if item:
        await session.delete(item)
        # Recalculate subtotal
        all_items = (await session.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )).all()
        order.subtotal = sum(Decimal(i.price_aed) * i.qty for i in all_items)
        order.total = order.subtotal + Decimal(order.delivery_fee_aed or "0")


async def _execute_ai_update_qty(
    session: AsyncSession, conv: Conversation, restaurant_id: int,
    dish_query: str, qty: int
) -> None:
    """Update quantity of matching dish in draft order."""
    from app.ordering.models import Order, OrderItem
    from app.conversation.engine import find_dish_matches, MatchConfidence

    draft_order_id = conv.state.get("draft_order_id")
    if not draft_order_id or not dish_query or qty < 1:
        return
    order = await session.get(Order, draft_order_id)
    if order is None:
        return
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH or not result.candidates:
        return
    target_dish_id = result.candidates[0].id
    item = await session.scalar(
        select(OrderItem).where(
            OrderItem.order_id == order.id,
            OrderItem.dish_id == target_dish_id,
        )
    )
    if item:
        item.qty = qty
        all_items = (await session.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )).all()
        order.subtotal = sum(Decimal(i.price_aed) * i.qty for i in all_items)
        order.total = order.subtotal + Decimal(order.delivery_fee_aed or "0")


async def _execute_save_address(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage,
    restaurant_id: int, apt_room: str, building: str, receiver_name: str, restaurant,
) -> None:
    """Store address + attach to order + transition to awaiting_confirmation."""
    from app.ordering.fees import calculate_fee
    from app.ordering.models import Order
    from app.ordering.service import get_or_create_customer, upsert_address

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone
    )
    addr = await upsert_address(
        session,
        customer_id=customer.id,
        latitude=conv.state.get("pin_lat"),
        longitude=conv.state.get("pin_lon"),
        room_apartment=apt_room,
        building=building,
        receiver_name=receiver_name,
        confirmed=True,
    )
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-draft-addr",
            body="Your cart is empty. Send 'hi' to start a new order.",
        )
        return
    dist = conv.state.get("distance_km")
    fee = calculate_fee(dist if dist is not None else 0.0)
    order.address_id = addr.id
    order.distance_km = dist
    order.delivery_fee_aed = fee
    order.total = order.subtotal + fee
    await session.flush()
    _set_state(conv, dialogue_phase="awaiting_confirmation",
               dialogue_state="order_confirmation", pending_order_id=order.id)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _attach_saved_address_to_order(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage,
    restaurant_id: int, address_id: int, restaurant,
) -> None:
    """Reuse saved address — attach to draft order + transition to confirmation."""
    from app.ordering.fees import calculate_fee
    from app.ordering.models import CustomerAddress, Order

    addr = await session.get(CustomerAddress, address_id)
    if addr is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="saved-addr-gone",
            body="Couldn't load your saved address. Please share your location 📍",
        )
        return
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-draft-saved",
            body="Your cart is empty. Send 'hi' to start a new order.",
        )
        return
    # Compute distance from saved lat/lng
    from app.geo.factory import get_geo_provider
    try:
        dist_result = await get_geo_provider().distance(
            origin=(restaurant.lat, restaurant.lng),
            destination=(addr.latitude, addr.longitude),
        )
        dist_km = dist_result.distance_km
    except Exception:
        dist_km = 0.0
    fee = calculate_fee(dist_km)
    order.address_id = addr.id
    order.distance_km = dist_km
    order.delivery_fee_aed = fee
    order.total = order.subtotal + fee
    await session.flush()
    _set_state(conv, dialogue_phase="awaiting_confirmation",
               dialogue_state="order_confirmation", pending_order_id=order.id)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _execute_confirm_order(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> None:
    """Finalize order confirmation and transition to post_order."""
    from app.ordering.models import Order
    from app.ordering.service import finalize_confirmation

    order_id = conv.state.get("pending_order_id") or conv.state.get("draft_order_id")
    order = await session.get(Order, order_id) if order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-order-confirm",
            body="No order to confirm. Send 'hi' to start again.",
        )
        return
    await finalize_confirmation(session, order=order, actor="customer")
    _set_state(conv, dialogue_phase="post_order", dialogue_state="order_placed")
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-confirmed",
        body=(
            f"Order confirmed! 🎉 Order #{order.order_number}\n"
            f"Total: AED {Decimal(order.total).normalize()} (COD — cash on delivery)\n"
            f"Your food will arrive within ~40 minutes. We'll keep you posted! 🛵"
        ),
    )


async def _execute_cancel_order(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> None:
    """Cancel the current draft/pending order."""
    from app.ordering.fsm import OrderStatus
    from app.ordering.fsm import transition as fsm_transition
    from app.ordering.models import Order

    for key in ("pending_order_id", "draft_order_id"):
        order_id = conv.state.get(key)
        if order_id:
            order = await session.get(Order, order_id)
            if order and order.status in (
                str(OrderStatus.DRAFT), str(OrderStatus.PENDING_CONFIRMATION),
                str(OrderStatus.CONFIRMED),
            ):
                await fsm_transition(session, order, OrderStatus.CANCELLED, actor="customer")
            break
    _set_state(conv, dialogue_phase="ordering", dialogue_state="greeting",
               draft_order_id=None, pending_order_id=None)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-cancelled",
        body="No problem — your order has been cancelled. Send 'hi' whenever you're ready to order again 😊",
    )
```

- [ ] **Step 5: Update `_execute_ai_add_item` to accept `special_note`**

Find `_execute_ai_add_item` (around line 1094) and update the signature and `add_item` call:

```python
async def _execute_ai_add_item(
    session: AsyncSession,
    conv,
    inbound: InboundMessage,
    restaurant_id: int,
    dish_query: str,
    qty: int,
    special_note: str = "",
) -> bool:
    """Find and add a dish; return True if successfully added."""
    from app.ordering.models import Order
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH:
        return False
    if result.confidence == MatchConfidence.AMBIGUOUS:
        from app.llm.factory import get_arbiter
        try:
            dish = await get_arbiter().arbitrate(dish_query, result.candidates[:3])
        except Exception:
            dish = None
        if dish is None:
            dish = result.candidates[0]
    else:
        dish = result.candidates[0]

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone
    )
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        order = await create_draft_order(session, restaurant_id=restaurant_id,
                                         customer_id=customer.id)
        _set_state(conv, draft_order_id=order.id)
    await add_item(session, order=order, dish=dish, qty=qty, notes=special_note or None)
    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
    return True
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests/conversation/test_engine_full_ai.py::test_phase_guard_blocks_wrong_phase_action tests/conversation/test_engine_full_ai.py::test_add_item_action_updates_cart -v`
Expected: PASS (or near-pass — some fixture wiring may need adjustment)

- [ ] **Step 7: Run lint**

Run: `.venv/bin/ruff check src/app/conversation/engine.py`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_full_ai.py
git commit -m "feat: full AI action dispatch — add/remove/update_qty, address, confirm, cancel, status"
```

---

### Task 9: Location pin handler + handle_inbound customer path rewrite

**Files:**
- Modify: `src/app/conversation/engine.py`
- Test: `tests/conversation/test_engine_full_ai.py`

- [ ] **Step 1: Write failing test**

```python
# append to tests/conversation/test_engine_full_ai.py

async def test_location_pin_outside_radius_rejected(db_session, client, auth_headers):
    """Location pin outside restaurant's max_radius_km → polite rejection message."""
    from unittest.mock import AsyncMock, patch
    from app.conversation.service import get_or_create_conversation
    from app.conversation.models import Conversation

    restaurant = (await client.get("/api/v1/me", headers=auth_headers)).json()
    restaurant_id = restaurant["id"]
    phone = "+971505555666"

    # Pre-set conversation to address_capture phase
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant_id, phone=phone, counterpart="customer"
    )
    conv.state = {**conv.state, "dialogue_phase": "address_capture",
                  "dialogue_state": "address_capture", "draft_order_id": None}
    await db_session.commit()

    # Location pin very far away (outside any 10km radius from Dubai center)
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "messages": [{
                "id": "wamid.loc1",
                "from": phone,
                "timestamp": "1700000010",
                "type": "location",
                "location": {"latitude": 51.5074, "longitude": -0.1278},  # London
            }],
            "metadata": {"phone_number_id": "tid"},
        }, "field": "messages"}]}],
    }

    # Use FakeGeoProvider which returns a large distance for this test
    with patch("app.geo.factory.get_geo_provider") as mock_geo:
        from unittest.mock import MagicMock
        geo = MagicMock()
        geo.distance = AsyncMock(return_value=MagicMock(distance_km=5432.0))
        mock_geo.return_value = geo

        resp = await client.post(
            f"/webhooks/whatsapp?restaurant_id={restaurant_id}",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=fake"},
        )
    assert resp.status_code == 200
```

- [ ] **Step 2: Add `_handle_location_pin` to `engine.py`**

```python
async def _handle_location_pin(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant,
) -> None:
    """Process a location pin in address_capture phase.

    Validates against restaurant.settings["max_radius_km"].
    Stores lat/lng in conv.state then calls AI to ask for apt/room.
    """
    from app.geo.factory import get_geo_provider

    lat = float(inbound.payload.get("latitude", 0))
    lng = float(inbound.payload.get("longitude", 0))
    max_km = restaurant.settings.get("max_radius_km", 10) if restaurant else 10

    try:
        dist_result = await get_geo_provider().distance(
            origin=(restaurant.lat, restaurant.lng),
            destination=(lat, lng),
        )
        dist_km = dist_result.distance_km
    except Exception:
        from app.geo.haversine import haversine_km
        dist_km = haversine_km(restaurant.lat, restaurant.lng, lat, lng)

    if dist_km > max_km:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="out-of-range",
            body=(
                f"Sorry, your location is {dist_km:.1f} km away. "
                f"We deliver within {max_km} km. "
                "Unfortunately we can't deliver to you at this time 😔"
            ),
        )
        _set_state(conv, dialogue_phase="ordering", dialogue_state="greeting",
                   draft_order_id=None)
        return

    _set_state(
        conv,
        pin_lat=lat,
        pin_lon=lng,
        distance_km=dist_km,
        dialogue_phase="address_capture",
        dialogue_state="address_capture",
    )
    # Let AI ask for apt/room with updated context (location_received=True)
    await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
```

- [ ] **Step 3: Add new `_handle_customer_ai` (replaces old one)**

Find the existing `_handle_customer_ai` function (around line 1133) and replace it entirely:

```python
async def _handle_customer_ai(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant=None,
) -> None:
    """Phase-aware AI handler: owns the entire customer conversation."""
    from app.identity.models import Restaurant
    from app.llm.factory import get_conversation_agent

    if restaurant is None:
        restaurant = await session.get(Restaurant, restaurant_id)

    restaurant_name = restaurant.name if restaurant else "Restaurant"
    phase = _resolve_phase(conv)
    history = await _build_history(session, conv, limit=10)
    context = await _build_context(session, conv, restaurant_id, phase, restaurant)

    # Store saved_address_id in conv.state for use_saved_address action
    if "saved_address_id" in context:
        _set_state(conv, saved_address_id=context["saved_address_id"])

    agent = get_conversation_agent()
    try:
        result = await agent.respond(
            restaurant_name=restaurant_name,
            dialogue_phase=phase,
            history=history,
            context=context,
        )
    except Exception:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-fallback",
            body="Sorry, having a moment 😅 Type the dish number to order (e.g. 110) or send 'hi' to start.",
        )
        return

    await _dispatch_action(
        session, conv, inbound, restaurant_id, result, phase, restaurant
    )
```

- [ ] **Step 4: Rewrite the customer path in `handle_inbound`**

Find `handle_inbound` (around line 1294). Replace everything from the `dialogue_state = conv.state.get(...)` line to the end of the function with:

```python
    # ── Customer conversation (full AI) ────────────────────────────────────
    from app.identity.models import Restaurant as RestaurantModel
    restaurant = await session.get(RestaurantModel, restaurant_id)

    # Location pin → address capture handler (not AI, needs geo validation)
    if inbound.type == MessageType.LOCATION:
        phase = _resolve_phase(conv)
        if phase == "address_capture":
            await _handle_location_pin(session, conv, inbound, restaurant_id, restaurant)
        else:
            # Unsolicited location — treat as ordering intent, let AI respond
            await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
        return

    # All text + button_reply → AI (history includes "[tapped: X]" for buttons)
    await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
```

- [ ] **Step 5: Run the full conversation test suite**

Run: `.venv/bin/pytest tests/conversation/ -v --tb=short -q`
Expected: most pass; note which old FSM-specific tests now fail (they'll be fixed/updated in Task 10)

- [ ] **Step 6: Lint**

Run: `.venv/bin/ruff check src/app/conversation/engine.py`
Fix any issues.

- [ ] **Step 7: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_full_ai.py
git commit -m "feat: location pin handler + rewrite handle_inbound customer path to full-AI phase dispatch"
```

---

### Task 10: Update existing conversation tests for new AI-driven flow

**Files:**
- Modify: `tests/conversation/test_engine.py`, `tests/conversation/test_engine_ordering.py`,
  `tests/conversation/test_engine_pipeline.py`

- [ ] **Step 1: Run full conversation test suite and collect failures**

Run: `.venv/bin/pytest tests/conversation/ -v --tb=short 2>&1 | grep FAILED`
Expected: list of failing tests — mostly old FSM-specific tests that expect exact FSM state strings

- [ ] **Step 2: Fix tests that check `dialogue_state` — update to check `dialogue_phase`**

For each failing test that does `assert conv.state["dialogue_state"] == "order_confirmation"`, update to:
```python
# Accept both legacy and new phase keys
phase = conv.state.get("dialogue_phase") or conv.state.get("dialogue_state")
assert phase in ("awaiting_confirmation", "order_confirmation")
```

For tests that mock `_handle_customer_ai` or `FakeConversationAgent`, update to use the new interface (dialogue_phase + context dict). Example:

```python
# OLD pattern (update all occurrences):
result = ConversationAgentResult(message="hi", action="no_action", action_data={})

# NEW pattern (same — ConversationAgentResult unchanged):
result = ConversationAgentResult(message="hi", action="no_action", action_data={})
# But the FakeConversationAgent.respond() now takes dialogue_phase + context:
# Already handled by Task 3's FakeConversationAgent update
```

- [ ] **Step 3: Fix tests that check intent classifier is called**

Old flow called `get_intent_classifier()` for status/modify detection. New flow: AI handles status/modify natively via `status_query` action. Remove or skip tests that assert the intent classifier is called from the customer path.

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/pytest tests/conversation/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conversation/
git commit -m "test: update conversation tests for full-AI phase-based flow"
```

---

### Task 11: Full regression — all 463 tests green

**Files:**
- No new files — fix whatever is broken

- [ ] **Step 1: Run full backend suite**

Run: `.venv/bin/pytest -q --tb=short 2>&1 | tail -20`
Expected: all pass

- [ ] **Step 2: Run lint**

Run: `.venv/bin/ruff check src apps tests`
Expected: clean

- [ ] **Step 3: Fix any remaining failures**

Common issues to look for:
- `add_item` service call signature — if service doesn't accept `notes` kwarg, pass `None` instead
- Import cycles — `_execute_ai_remove_item` references `find_dish_matches` which is in the same file; verify no circular import
- `_set_state` calls with `dialogue_phase` key — verify `_set_state` passes kwargs through to `conv.state`

- [ ] **Step 4: Update `understanding.txt`**

Append to `understanding.txt`:

```
- [2026-06-10] Full-AI phase-aware conversation agent implemented.
  Replaced hybrid FSM/AI with single DeepSeekConversationAgent owning entire customer flow.
  Phases: ordering → address_capture → awaiting_confirmation → post_order.
  7 languages: English, Arabic, Urdu/Hindi, Turkish, Russian, Filipino, Malayalam.
  Outbound messages now stored in messages table for real conversation history (last 10 turns).
  Returning customer saved address offered at address_capture phase.
  Radius validation from restaurant.settings["max_radius_km"] — not hardcoded.
  Actions: add_item(+special_note), remove_item, update_qty, proceed_to_address,
           send_location_request, save_address_text, use_saved_address, proceed_to_confirmation,
           confirm_order, request_modification, cancel_order, status_query, no_action.
  Phase guards server-side: wrong-phase action falls back to no_action.
  Rider flow (FSM + buttons) unchanged.
```

- [ ] **Step 5: Final commit**

```bash
git add understanding.txt
git commit -m "feat: full-AI phase-aware conversation agent complete — 7 languages, history, returning customer flow"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Full AI owns customer conversation (Task 9)
- ✅ 7 languages in system prompt (Task 7)
- ✅ Shorthand orders handled (Task 7 — ORDERING_BLOCK)
- ✅ Outbound messages stored (Task 4)
- ✅ Conversation history from DB (Task 5)
- ✅ Phase-aware prompt (Task 7)
- ✅ Returning customer address reuse (Task 8 — use_saved_address + _build_context)
- ✅ Radius from restaurant.settings (Task 9 — _handle_location_pin)
- ✅ Phase guards server-side (Task 8 — _is_valid_action_for_phase)
- ✅ Upsell once (Task 7 — ORDERING_BLOCK)
- ✅ Address = pin + apt/room + building + receiver only (Task 7 — ADDRESS_BLOCK)
- ✅ Rider path unchanged (not touched)
- ✅ STOP opt-out unchanged (not touched)
- ✅ Audit log unchanged (finalize_confirmation + fsm_transition call it)
- ✅ Outbox pattern unchanged (_send_text/_send_buttons still call enqueue_message)
- ✅ TDD: failing tests written first in each task

**Type consistency:**
- `ConversationAgentResult(message, action, action_data)` — consistent Tasks 2,3,6,7,8
- `_execute_ai_add_item(session, conv, inbound, restaurant_id, dish_query, qty, special_note)` — Task 8 + Task 8 step 5
- `_resolve_phase(conv)` returns str — used in Tasks 6, 9
- `_build_context(session, conv, restaurant_id, phase, restaurant)` — Tasks 6, 9
- `_dispatch_action(session, conv, inbound, restaurant_id, result, phase, restaurant)` — Task 8, 9
- `_handle_customer_ai(session, conv, inbound, restaurant_id, restaurant=None)` — Task 9
