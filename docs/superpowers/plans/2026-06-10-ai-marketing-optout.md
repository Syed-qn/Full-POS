# AI Marketing Opt-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect natural-language opt-out phrases ("stop sending me marketing") in the WhatsApp conversation engine and call `record_opt_out()`, same as sending "STOP".

**Architecture:** Add `is_optout_intent(text)` phrase-matcher and `record_opt_in()` delete helper to `marketing/optout.py`. Patch engine.py to check both `is_stop_keyword` and `is_optout_intent` before dialogue routing.

**Tech Stack:** Python 3.12, SQLAlchemy async, pytest-asyncio, existing `marketing/optout.py` and `conversation/engine.py`.

---

## File Map

| Action | File |
|--------|------|
| Modify | `src/app/marketing/optout.py` — add `OPTOUT_PHRASES`, `is_optout_intent()`, `record_opt_in()` |
| Modify | `src/app/conversation/engine.py:1935-1951` — extend stop-keyword check |
| Create | `tests/marketing/test_optout_intent.py` — unit tests for new functions |
| Modify | `tests/conversation/test_engine.py` — integration test for natural-language opt-out |

---

### Task 1: `is_optout_intent()` and `record_opt_in()` in marketing/optout.py

**Files:**
- Modify: `src/app/marketing/optout.py`
- Test: `tests/marketing/test_optout_intent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/marketing/test_optout_intent.py`:

```python
import pytest
from app.marketing.optout import is_optout_intent, record_opt_in, is_opted_out, record_opt_out


def test_natural_phrase_triggers_optout():
    assert is_optout_intent("stop sending me marketing messages") is True


def test_dont_send_triggers_optout():
    assert is_optout_intent("don't send me any more messages") is True


def test_no_more_marketing_triggers_optout():
    assert is_optout_intent("no more marketing please") is True


def test_opt_out_phrase_triggers_optout():
    assert is_optout_intent("I want to opt out") is True


def test_ordering_message_not_optout():
    assert is_optout_intent("I want to order biryani") is False


def test_empty_string_not_optout():
    assert is_optout_intent("") is False


def test_case_insensitive():
    assert is_optout_intent("STOP SENDING ME MESSAGES") is True


def test_exact_stop_not_handled_here():
    # "stop" alone is handled by is_stop_keyword, not is_optout_intent
    # is_optout_intent only matches multi-word phrases
    assert is_optout_intent("stop") is False


async def test_record_opt_in_removes_optout_row(db_session, restaurant):
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone="+971501111111")
    await db_session.commit()
    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501111111")

    await record_opt_in(db_session, restaurant_id=restaurant.id, phone="+971501111111")
    await db_session.commit()
    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501111111")


async def test_record_opt_in_is_idempotent_when_no_row(db_session, restaurant):
    # calling record_opt_in when not opted out should not raise
    await record_opt_in(db_session, restaurant_id=restaurant.id, phone="+971509999999")
    await db_session.commit()
    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971509999999")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/pytest tests/marketing/test_optout_intent.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'is_optout_intent'`

- [ ] **Step 3: Add `OPTOUT_PHRASES`, `is_optout_intent()`, and `record_opt_in()` to `src/app/marketing/optout.py`**

Add these imports at the top of the file (after existing imports):

```python
from sqlalchemy import delete
```

Add after `_STOP_PREFIXES` definition (after line 29):

```python
# Multi-word natural-language opt-out phrases (substring match, lowercased).
# Exact single-word keywords are already covered by is_stop_keyword().
_OPTOUT_PHRASES: tuple[str, ...] = (
    "stop sending",
    "stop messaging",
    "don't send",
    "dont send",
    "no more messages",
    "no more marketing",
    "no more promotions",
    "opt out",
    "opt-out",
    "remove me",
    "don't message",
    "dont message",
    "stop marketing",
    "stop promotions",
    "no promotions",
    "unsubscribe me",
    "don't contact",
    "dont contact",
)


def is_optout_intent(text: str) -> bool:
    """True if ``text`` contains a natural-language marketing opt-out phrase.

    Complements ``is_stop_keyword`` which handles exact single-word keywords.
    This function only matches multi-word phrases so single-word 'stop' is not
    double-counted.
    """
    if not text:
        return False
    normalized = text.strip().lower()
    return any(phrase in normalized for phrase in _OPTOUT_PHRASES)
```

Add after `is_opted_out()` function (end of file):

```python
async def record_opt_in(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
) -> None:
    """Remove opt-out record if present. Idempotent — safe when no row exists."""
    await session.execute(
        delete(OptOut).where(
            OptOut.restaurant_id == restaurant_id,
            OptOut.phone == phone,
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/marketing/test_optout_intent.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/marketing/optout.py tests/marketing/test_optout_intent.py
git commit -m "feat: add is_optout_intent() and record_opt_in() to marketing/optout"
```

---

### Task 2: Wire opt-out intent into conversation engine

**Files:**
- Modify: `src/app/conversation/engine.py:1935-1951`
- Test: `tests/conversation/test_engine.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/conversation/test_engine.py`:

```python
async def test_natural_language_optout_records_optout(db_session, restaurant):
    """Natural-language phrase triggers opt-out same as STOP keyword."""
    from app.marketing.optout import is_opted_out

    inbound = InboundMessage(
        wa_message_id="nl-optout-1",
        from_phone="+971501234777",
        restaurant_phone=restaurant.phone,
        type=MessageType.TEXT,
        payload={"text": "stop sending me marketing messages"},
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()
    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501234777")


async def test_natural_language_optout_sends_confirmation(db_session, restaurant):
    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    inbound = InboundMessage(
        wa_message_id="nl-optout-2",
        from_phone="+971501234778",
        restaurant_phone=restaurant.phone,
        type=MessageType.TEXT,
        payload={"text": "don't send me any more messages please"},
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501234778")
    )).scalars().all()
    assert len(rows) == 1
    assert "unsubscribed" in rows[0].payload["body"].lower()


async def test_ordering_message_not_misclassified_as_optout(db_session, restaurant):
    from sqlalchemy import select
    from app.marketing.optout import is_opted_out

    await _seed_menu(db_session, restaurant.id)

    inbound = InboundMessage(
        wa_message_id="not-optout-1",
        from_phone="+971501234779",
        restaurant_phone=restaurant.phone,
        type=MessageType.TEXT,
        payload={"text": "I want to order 2 chicken biryani"},
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()
    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501234779")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/conversation/test_engine.py::test_natural_language_optout_records_optout -v
```

Expected: FAIL — opt-out not recorded (engine doesn't call `is_optout_intent` yet)

- [ ] **Step 3: Patch engine.py lines 1935-1951**

Open `src/app/conversation/engine.py`. Find the block starting at line 1935:

```python
    # STOP opt-out — must be checked before any dialogue processing
    from app.marketing.optout import is_stop_keyword, record_opt_out
    if is_stop_keyword(inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""):
        await record_opt_out(
```

Replace the entire block (lines 1935-1951) with:

```python
    # Opt-out — exact STOP keywords + natural-language phrases.
    # Checked before any dialogue processing so AI never sees opt-out messages.
    from app.marketing.optout import is_optout_intent, is_stop_keyword, record_opt_out
    _opt_text = inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""
    if is_stop_keyword(_opt_text) or is_optout_intent(_opt_text):
        await record_opt_out(
            session,
            restaurant_id=restaurant_id,
            phone=inbound.from_phone,
            source="stop_keyword" if is_stop_keyword(_opt_text) else "natural_language",
        )
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "You've been unsubscribed from marketing messages. Reply START to re-subscribe."},
            idempotency_key=f"stop-ack-{inbound.wa_message_id}",
        )
        return  # do not process further
```

- [ ] **Step 4: Run all three new tests**

```bash
.venv/bin/pytest tests/conversation/test_engine.py::test_natural_language_optout_records_optout tests/conversation/test_engine.py::test_natural_language_optout_sends_confirmation tests/conversation/test_engine.py::test_ordering_message_not_misclassified_as_optout -v
```

Expected: all 3 PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
.venv/bin/pytest tests/ -x -q 2>&1 | tail -20
```

Expected: all tests pass (same count as before + 13 new)

- [ ] **Step 6: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine.py
git commit -m "feat: detect natural-language marketing opt-out in conversation engine"
```
