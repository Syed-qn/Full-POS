# W7 — History / DB Faithfulness for the LLM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Every task is a strict TDD cycle: write a failing test → run it RED → implement → run it GREEN → commit. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the DB the faithful, complete record of what actually happened in a conversation, and make the model read exactly that. After W7: a catalogue ORDER turn renders in history as a readable basket (resolved dish names + qty + notes), not `[order]`; the interpreter receives a **structured** cart array (not only a prose string) and is told the DB cart wins over history prose; there is **one** `_build_history` with a branch for every `Message.type`; every customer-facing outbound (catalog cards, STT-fail, error apology, keyword-catalog) is recorded in `messages`; outbound rows carry the Meta `wa_message_id` and are coupled to their `outbox_messages` delivery status; the catalogue handler normalises phone into the single conversation thread; and each turn persists the AI decision + state snapshot for support replay.

**Closes (root-cause IDs):** R-027, R-029, R-030, R-037, R-060, R-072, R-073, R-074, R-076, R-077–R-084, R-DB-01–R-DB-30, F55, F56, F57, F62, F63, F65, F66, F67, F69, F71, DB-H1–DB-H15.

## Architecture

The conversation pipeline is: `webhook/router.receive_webhook` → (ORDER → `catalog.service.handle_catalog_order`; catalog-keyword → `catalog.service.send_catalog`; else → `engine.handle_inbound`) → `engine._handle_customer_ai` → `_build_history` + `_build_context` → `agent.respond(...)` → `_dispatch_action`. Outbounds are dual-written today: `enqueue_message` (→ `outbox_messages`, delivered by `outbox.worker._deliver_one`) **and** `record_message` (→ `messages`) — but the two rows are not linked, several outbound paths skip `record_message` entirely, and the inbound ORDER turn is stored as an opaque `{"product_items":[...]}` blob.

W7 changes four coherent surfaces:

1. **History rendering** (`engine._build_history`): a single builder with a branch for every `Message.type`, consecutive-same-role merge, configurable window, body normalised to the delivered form, and the catalogue ORDER turn rendered from a `cart_snapshot`/`display_text` persisted at record time. Delete the dead `_fetch_conversation_history`.
2. **Structured context** (`engine._build_cart_state` + `_build_context`): the cart is also passed as `context["cart_state"]` — an array of `{cart_item_id, dish, variant, note, qty, price}` — and the agent is instructed that this DB cart is authoritative over any history prose. `FakeConversationAgent` consumes `cart_state` so the eval harness drives the correction deterministically.
3. **Outbound + transcript completeness** (`conversation.service`, `catalog.service`, `webhook/router`): one shared `record_outbound` helper records *every* customer-facing send — catalog `product_list`, STT-fail apology, webhook error apology, keyword-catalog — and normalises the stored body to the delivered (`to_whatsapp_text`) body.
4. **Delivery coupling + per-turn persistence** (migration on `messages`, `outbox.worker`, `engine`): `messages` gains `outbox_id`, `delivery_status`, `ai_decision` (JSONB), `state_snapshot` (JSONB); the outbox worker backfills `wa_message_id` + `delivery_status` onto the coupled message; the inbound record and `_dispatch_action` persist the AI decision + the state snapshot at that turn; cart-mutation audit rows carry the source message id.

### W7a / W7b split — RECOMMENDED

W7 is large; **split it into two shippable sub-workstreams** that share this one plan and one branch series. Each sub-workstream ends green and graduates its evals.

- **W7a — Faithful history + structured context (LLM-facing correctness).** Tasks 1–7. Flips **basket-visible-in-history** and **structured-cart-driven-correction**. This is the load-bearing repair for the biryani incident (F63 + F64 + F66) and gates nothing downstream beyond itself.
- **W7b — Transcript completeness, delivery truth & replay (storage/ops).** Tasks 8–13. Flips **all-outbounds-recorded** and adds `wa_message_id` backfill, `messages`↔`outbox` coupling, and per-turn AI-decision/state-snapshot persistence. Pure storage/observability; no change to model-visible behaviour, so it can land after W7a without re-gating W7a's evals.

Both sub-workstreams keep the W0 regression suite green on every commit. If executed as one workstream, run the tasks in the given order; the final task (Task 13) flips all three xfail markers together.

## Tech Stack

Python 3.12, async SQLAlchemy 2, Alembic, FastAPI, pytest + pytest-asyncio, `FakeConversationAgent`/`FakeExtractor` ports, Docker Postgres+PostGIS (`:5433`), `restaurant_test` DB. Outbox delivery is synchronous in tests/Render (`APP_OUTBOX_SYNC_DELIVERY`) and Celery in worker mode.

## Global Constraints

- **Multi-tenant:** every query filters by `restaurant_id` (or by a `conversation_id` already scoped to one tenant); never read or write across tenants. The catalogue handler must land on the SAME `conversations` row the text path uses (F71).
- **Multi-language:** no hardcoded English phrase tables added to live paths. History rendering must not assume English content.
- **LLM authorship:** the model never authors money, menu, totals, or order numbers. `cart_state` is built from the DB, never from model output.
- **Money:** `Numeric(8,2)` / `Decimal`, AED. DB stores UTC.
- **Tests:** use the `restaurant_test` Docker DB; schema is recreated per test via `tests/conftest.py` (`Base.metadata.create_all`). Bring DBs to head with `scripts/dev_db_bootstrap.sh` (from W0) before running.
- **Migrations:** W7 adds **columns to the existing `messages` table only** (no new model module), so no new `alembic/env.py` / `tests/conftest.py` import is required (`app.conversation.models` is already registered in both). BUT the `messages` table currently has **no** `BEFORE UPDATE` `trg_messages_updated_at` trigger (verified: zero migrations create it) — because W7b now UPDATEs message rows (backfill), the migration MUST add `trg_messages_updated_at BEFORE UPDATE ... EXECUTE FUNCTION set_updated_at()` so `updated_at` stays truthful. The `set_updated_at()` function already exists (from `f6764ecf8b8d`).
- **Commits:** Conventional Commits, one per task, on a remediation branch (never directly on `main`). Every commit message ends with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **After completion:** full test matrix + `.venv/bin/ruff check src apps tests` + `/graphify . --update` + append `understanding.txt`.
- **Source of truth:** `docs/superpowers/specs/2026-06-30-whatsapp-ordering-remediation-design.md` (§ "W7") and `…-biryani-correction-flow-root-cause.md` (R-077–R-084, R-DB-01–30, DB-H1–H15, F55–F72).

## Real signatures this plan builds on (verified at HEAD)

- `engine._build_history(session, conv, limit=10) -> list[dict]` — `src/app/conversation/engine.py:3181`. Sorts `created_at desc, id desc`; branches text/audio/location/button_reply/buttons, else `f"[{msg.type}]"`; no merge; prepends `{"role":"user","content":"hi"}` if first is assistant.
- `engine._fetch_conversation_history(session, conversation_id, limit=20)` — `engine.py:3010` — **dead** (zero call sites; merges + `id desc`). Delete (F67/F69/R-083).
- `engine._build_cart_summary(session, conv) -> str` — `engine.py:3115` — joins `OrderItem`, renders prose. Keep; add `_build_cart_state` next to it.
- `engine._build_context(session, conv, restaurant_id, phase, restaurant) -> dict` — `engine.py:3279` — sets `ctx["cart_summary"]` in ordering/address phases.
- `engine._handle_customer_ai(...)` — `engine.py:4937`; calls `history = await _build_history(session, conv, limit=10)` at `:4953`, then `agent.respond(restaurant_name, dialogue_phase, history, context)`.
- `engine._send_text/_send_buttons/_send_cta_url/_send_location_request` — `engine.py:1156/1186/1217/1254` — each `enqueue_message(...)` then `record_message(..., wa_message_id=None)`. No outbox_id capture.
- `conversation.service.record_message(session, *, conversation_id, direction, wa_message_id, msg_type, payload, ts=0, media_data=None, media_mime=None) -> Message` — `service.py:153`.
- `conversation.service.message_display_text(payload) -> str|None` — `service.py:20`.
- `conversation.service.get_or_create_conversation(session, *, restaurant_id, phone, counterpart) -> Conversation` — `service.py:127`.
- `catalog.service.handle_catalog_order(session, inbound, *, restaurant_id)` — `catalog/service.py:205`; records `msg_type="order", payload={"product_items": product_items}` at `:237`; uses `inbound.from_phone` **un-normalised** (F71) at `:235`.
- `catalog.service.send_catalog(session, *, restaurant_id, to_phone, idempotency_key)` — `catalog/service.py:69`; only `enqueue_message` (no `record_message`) (DB-H4).
- `outbox.service.enqueue_message(session, *, restaurant_id, to_phone, msg_type, payload, idempotency_key, mirror_rider_conversation=True) -> OutboxMessage` — `outbox/service.py:81`; applies `to_whatsapp_text(payload["body"])` at `:92-94`.
- `outbox.worker._deliver_one(outbox_id, *, provider, session_factory)` — `outbox/worker.py:75`; on success sets `row.status="sent"; row.wa_message_id=wa_id` (`:88-89`).
- `Message` — `conversation/models.py:18` — has `wa_message_id` (nullable), `payload` JSONB, `ts` BigInteger, TimestampMixin. **No** `outbox_id`/`delivery_status` yet.
- `webhook/router.py:114-130` routing; `_send_error_apology` at `:201` (no `record_message`).
- Harness: `tests/harness/replay.drive_turns(session, *, restaurant_id, phone, turns)` → `TranscriptResult`; `res.final_cart()`, `turn.cart_rows`, `turn.outbounds[*].body/.msg_type`, `turn.phase`, `turn.state`. Eval suite: `tests/evals/test_response_accuracy_suite.py`. Fixtures: `restaurant`, `seed_biryani_menu`, `db_session` (conftest). Seeded biryani retailer id is `ju9f8jfy90` (see existing eval at suite L55).

## Task index

| # | W7a/b | Title | Closes |
|---|-------|-------|--------|
| 1 | — | Create the W7 branch | — |
| 2 | W7a | Add the 3 W7 capability evals (xfail-strict) | acceptance gates |
| 3 | W7a | Persist `display_text` + `cart_snapshot` on the ORDER record | R-077, R-082, F63, DB-H8 |
| 4 | W7a | Single `_build_history`; per-type branches; merge; window; delete dead builder | R-078/79/80/83/84, F55/56/57/62/67/69, DB-H7/12/13 |
| 5 | W7a | Structured `cart_state` + DB-precedence; Fake agent consumes it | R-072/73/74/76, R-060 |
| 6 | W7a | Normalise phone in catalogue handler → single thread | F71, R-027 |
| 7 | W7a | Graduate basket-visible + structured-correction (flip 2 xfails) | R-029/30 |
| 8 | W7b | Migration: `messages.outbox_id/delivery_status/ai_decision/state_snapshot` + trigger | DB-H9/10/15 schema |
| 9 | W7b | One `record_outbound` helper; record ALL outbounds; normalise body | DB-H2/3/4/5 |
| 10 | W7b | Couple `messages`↔`outbox`; backfill `wa_message_id` + delivery status | DB-H1, DB-H15 |
| 11 | W7b | Per-turn AI decision + state snapshot; link audit | DB-H9/10/11, R-037 |
| 12 | W7b | Graduate all-outbounds-recorded (flip 3rd xfail) | DB-H3/4/5 |
| 13 | — | Self-review, full matrix, ruff, graphify, understanding.txt | — |

---

### Task 1: Create the W7 remediation branch

**Files:** none (git only)

**Interfaces:** Produces branch `remediation/w7-history-db-faithfulness` from the up-to-date base (W4 + the parallel W5/W6 if already merged; else from `main`).

- [ ] **Step 1: Confirm base and clean tree**
  Run: `git status --short && git branch --show-current`
  Expected: on the integration base; note any in-flight files. Do not commit unrelated changes.

- [ ] **Step 2: Create the branch**
  Run: `git checkout -b remediation/w7-history-db-faithfulness`
  Expected: `Switched to a new branch 'remediation/w7-history-db-faithfulness'`.

- [ ] **Step 3: Bring DBs to head**
  Run: `bash scripts/dev_db_bootstrap.sh`
  Expected: `restaurant @ head`. (Provides `restaurant` + `restaurant_test`.)

---

### Task 2: Add the three W7 capability evals as xfail-strict (RED-as-xfail)

These three evals are the W7 acceptance gates. They are added now as `@pytest.mark.xfail(strict=True)` so they reproduce the incident today; later tasks flip them to PASS and Tasks 7 & 12 remove the markers. This mirrors the W0 suite pattern (`tests/evals/test_response_accuracy_suite.py`).

**Files:**
- Modify: `tests/evals/test_response_accuracy_suite.py` (append three evals in the XFAIL block)
- Reference: `tests/harness/replay.py`, `tests/harness/graders.py`

**Interfaces:**
- Consumes: `drive_turns`, `res.final_cart()`, `turn.cart_rows`, `turn.outbounds`, fixtures `restaurant`, `seed_biryani_menu`, `db_session`.
- Produces: 3 xfail-strict tests reproducing R-029/R-030/R-072/DB-H3-5.

- [ ] **Step 1 (failing test → xfail): add the three evals**
  Append to the XFAIL section of `tests/evals/test_response_accuracy_suite.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# W7 capability evals (xfail-strict until W7a/W7b land)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="W7a basket-visible-in-history: catalogue ORDER turn must render as a "
           "readable basket (dish names + qty) in _build_history, not '[order]'",
)
async def test_basket_visible_in_history(db_session, restaurant, seed_biryani_menu):
    """After a catalogue basket, _build_history must show the resolved dish names
    for that turn (e.g. 'Chicken Biryani'), not the opaque placeholder '[order]'
    (R-029/R-077/F63/DB-H8)."""
    from app.conversation.engine import _build_history
    from tests.harness.replay import _conv_for

    await drive_turns(
        db_session, restaurant_id=restaurant.id, phone="+971500000060",
        turns=[
            {"type": "order", "product_items": [
                {"product_retailer_id": "ju9f8jfy90", "quantity": 2,
                 "item_price": 20, "currency": "AED"},
            ]},
            {"type": "text", "text": "anything else?"},
        ],
    )
    conv = await _conv_for(db_session, restaurant.id, "+971500000060")
    history = await _build_history(db_session, conv, limit=10)
    blob = " ".join(h["content"] for h in history).lower()
    assert "[order]" not in blob, f"history still shows opaque [order]: {history}"
    assert "biryani" in blob, f"basket dish name missing from history: {history}"
    assert "2" in blob, f"basket qty missing from history: {history}"


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="W7a structured-cart-driven correction: 'only 1 chicken biryani' after a "
           "2x basket must set qty to 1 using the structured DB cart, not re-add",
)
async def test_structured_cart_drives_correction(db_session, restaurant, seed_biryani_menu):
    """The interpreter receives context['cart_state'] (a structured array) and is
    told the DB cart wins over history prose. A correction sets the existing line's
    qty rather than appending a duplicate (R-072/R-074/R-060)."""
    res = await drive_turns(
        db_session, restaurant_id=restaurant.id, phone="+971500000061",
        turns=[
            {"type": "order", "product_items": [
                {"product_retailer_id": "ju9f8jfy90", "quantity": 2,
                 "item_price": 20, "currency": "AED"},
            ]},
            {"type": "text", "text": "only 1 chicken biryani"},
        ],
    )
    biryani = [r for r in res.final_cart() if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1, f"expected 1 biryani line, got {biryani}"
    assert biryani[0]["qty"] == 1, f"expected qty 1 after correction, got {biryani[0]['qty']}"


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="W7b all-outbounds-recorded: catalog cards, STT-fail and error apology "
           "must each create a Message row, not live only in the outbox",
)
async def test_all_customer_outbounds_recorded(db_session, restaurant, seed_biryani_menu):
    """Every customer-facing outbound is recorded in `messages` (DB-H3/4/5).
    Drive a keyword-catalog send and an STT-fail; assert both produced an outbound
    Message row (product_list and text)."""
    from sqlalchemy import select
    from app.conversation.models import Conversation, Message

    # (a) keyword catalog → product_list card send must be recorded
    await drive_turns(
        db_session, restaurant_id=restaurant.id, phone="+971500000062",
        turns=[{"type": "text", "text": "menu"}],
    )
    # (b) STT failure (audio with no audio_id) → apology must be recorded
    await drive_turns(
        db_session, restaurant_id=restaurant.id, phone="+971500000062",
        turns=[{"type": "audio", "audio_id": None, "text": ""}],
    )
    conv = await db_session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant.id,
            Conversation.phone == "971500000062",
        )
    )
    assert conv is not None, "catalogue keyword path must land on a conversation thread"
    out = (await db_session.scalars(
        select(Message).where(
            Message.conversation_id == conv.id, Message.direction == "outbound"
        )
    )).all()
    types = {m.type for m in out}
    assert "product_list" in types, f"catalog cards not recorded; types={types}"
    bodies = " ".join((m.payload or {}).get("body", "") for m in out).lower()
    assert "catch that" in bodies or "type it" in bodies, (
        f"STT-fail apology not recorded in messages; bodies={bodies!r}"
    )
```

- [ ] **Step 2 (RED-as-xfail): run them**
  Run: `.venv/bin/pytest tests/evals/test_response_accuracy_suite.py -k "basket_visible or structured_cart or all_customer_outbounds" -v`
  Expected: all three report **XFAIL** (strict). If any XPASS, the behaviour already works — stop and re-scope that task.

- [ ] **Step 3: commit**
```bash
git add tests/evals/test_response_accuracy_suite.py
git commit -m "test(evals): add W7 capability evals — basket-in-history, structured-cart correction, all-outbounds-recorded (xfail strict)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Persist `display_text` + `cart_snapshot` at ORDER record time (R-077, R-082, F63, DB-H8)

The catalogue handler records `payload={"product_items": product_items}` — opaque to history. Resolve dish names/qty/notes **at write time** and store a human `display_text` and a structured `cart_snapshot` inside the same JSONB payload (no migration needed — `payload` is JSONB). `_build_history` (Task 4) renders from these.

**Files:**
- Modify: `src/app/catalog/service.py` (`handle_catalog_order`)
- Create: `tests/catalog/test_order_record_snapshot.py`

**Interfaces:**
- Consumes: resolved `Dish` per `retailer_id` (already looked up in the add loop), the post-add cart via `_build_cart_state` (Task 5 provides it — for Task 3 use a local inline snapshot builder that reads `OrderItem`).
- Produces: ORDER `Message.payload` gains `display_text: str` and `cart_snapshot: list[dict]` (`{cart_item_id, dish, variant, note, qty, price}`), plus the original `product_items`.

> Sequencing note: Task 3 records the snapshot **after** items are added so it reflects the resulting cart (the basket as the customer will see it), matching DB-H8 "post-add cart snapshot". Build the snapshot from `OrderItem` rows on `order.id`.

- [ ] **Step 1 (failing test): assert the ORDER row carries a snapshot**
  Create `tests/catalog/test_order_record_snapshot.py`:

```python
import pytest
from sqlalchemy import select

from app.catalog.service import handle_catalog_order
from app.conversation.models import Conversation, Message
from app.whatsapp.port import InboundMessage, MessageType


def _order_inbound(phone, restaurant_phone):
    return InboundMessage(
        wa_message_id=f"wamid-{phone}",
        from_phone=phone,
        type=MessageType.ORDER,
        payload={"product_items": [
            {"product_retailer_id": "ju9f8jfy90", "quantity": 2,
             "item_price": 20, "currency": "AED"},
        ]},
        restaurant_phone=restaurant_phone,
        timestamp=1_700_000_000,
    )


@pytest.mark.asyncio
async def test_order_record_has_display_text_and_snapshot(
    db_session, restaurant, seed_biryani_menu
):
    inbound = _order_inbound("+971500000070", restaurant.phone)
    await handle_catalog_order(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.flush()

    conv = await db_session.scalar(
        select(Conversation).where(Conversation.restaurant_id == restaurant.id)
    )
    order_msg = await db_session.scalar(
        select(Message).where(
            Message.conversation_id == conv.id, Message.type == "order"
        )
    )
    assert order_msg is not None
    payload = order_msg.payload
    # original product_items preserved
    assert payload.get("product_items"), "raw product_items must be preserved"
    # human display text resolves the dish name + qty
    assert "display_text" in payload
    assert "biryani" in payload["display_text"].lower()
    assert "2" in payload["display_text"]
    # structured snapshot of the resulting cart
    snap = payload.get("cart_snapshot")
    assert isinstance(snap, list) and snap, "cart_snapshot must be a non-empty list"
    line = snap[0]
    assert {"cart_item_id", "dish", "qty", "price"} <= set(line)
    assert line["qty"] == 2
    assert "biryani" in line["dish"].lower()
```

  Run: `.venv/bin/pytest tests/catalog/test_order_record_snapshot.py -v` → **RED** (`display_text`/`cart_snapshot` absent).

- [ ] **Step 2 (implement): build + persist the snapshot in `handle_catalog_order`**
  In `src/app/catalog/service.py`, add a module-level helper and update the record. Add near the other imports a reuse of `_aed` (already in the module). Insert after the add loop completes (after `_set_state(...)`, before/around the existing `_build_cart_summary` call at ~L309). Replace the early `record_message(...)` (currently at L237) with a deferred record so the snapshot reflects the final cart — record the ORDER message AFTER items are added:

```python
async def _order_cart_snapshot(session, order_id: int) -> tuple[str, list[dict]]:
    """Resolve the resulting draft cart into (display_text, structured snapshot).

    display_text is a human basket line ('2x Chicken Biryani') used by the LLM
    history; the snapshot is the structured per-line array the interpreter reads.
    """
    from app.ordering.models import OrderItem

    items = list((await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id)
    )).all())
    snapshot: list[dict] = []
    parts: list[str] = []
    for it in items:
        snapshot.append({
            "cart_item_id": it.id,
            "dish": it.dish_name,
            "variant": it.variant_name,
            "note": it.notes,
            "qty": it.qty,
            "price": str(it.price_aed),
        })
        label = f"{it.qty}x {it.dish_name}"
        if it.variant_name:
            label += f" ({it.variant_name})"
        if it.notes:
            label += f" — {it.notes}"
        parts.append(label)
    return "; ".join(parts), snapshot
```

  Then restructure `handle_catalog_order`: keep `get_or_create_conversation` and the customer/order resolution + add loop, but **move** the ORDER `record_message` to after the loop, recording the snapshot. Concretely, delete the existing record block at L237-242 and, just before the final `_send_text("catalog-cart", ...)`, insert:

```python
    # Faithful ORDER record: persist a readable basket + structured snapshot so the
    # LLM history (engine._build_history) renders dish names, not "[order]" (DB-H8).
    _display_text, _cart_snapshot = await _order_cart_snapshot(session, order.id)
    await record_message(
        session, conversation_id=conv.id, direction="inbound",
        wa_message_id=inbound.wa_message_id, msg_type="order",
        payload={
            "product_items": product_items,
            "display_text": _display_text,
            "cart_snapshot": _cart_snapshot,
        },
        ts=inbound.timestamp or int(time.time()),
    )
```

  For the no-mappable-items branch (`if not added:`), still record the ORDER with `display_text=""`, `cart_snapshot=[]` BEFORE the early `return`, so the inbound turn is never missing:

```python
    if not added:
        await record_message(
            session, conversation_id=conv.id, direction="inbound",
            wa_message_id=inbound.wa_message_id, msg_type="order",
            payload={"product_items": product_items, "display_text": "", "cart_snapshot": []},
            ts=inbound.timestamp or int(time.time()),
        )
        await _send_text(... "catalog-empty" ...)  # unchanged
        return
```

- [ ] **Step 3 (GREEN):** `.venv/bin/pytest tests/catalog/test_order_record_snapshot.py -v` → PASS.
- [ ] **Step 4: no regression:** `.venv/bin/pytest tests/catalog -v` → PASS.
- [ ] **Step 5: commit**
```bash
git add src/app/catalog/service.py tests/catalog/test_order_record_snapshot.py
git commit -m "feat(catalog): persist display_text + cart_snapshot on ORDER record (R-077/R-082/F63/DB-H8)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Single `_build_history` — per-type branches, merge, configurable window; delete the dead builder

Rewrite `_build_history` so it (a) renders **every** `Message.type` (ORDER → readable basket from `cart_snapshot`/`display_text`; `list_reply` → `[selected: title]`; `button_reply` → `[tapped: title (id)]`; `buttons` → body + `[options: t1 | t2]`; `cta_url`, `location`, `text`/`audio`); (b) merges consecutive same-role turns (R-079); (c) reads a **configurable** window from settings (R-080/F55); (d) normalises stored body to the delivered form (DB-H2); (e) orders by `(ts, id)` canonically (DB-H7). Delete `_fetch_conversation_history` (F67/F69/R-083).

**Files:**
- Modify: `src/app/config.py` (add `conversation_history_limit: int = 20`)
- Modify: `src/app/conversation/engine.py` (`_build_history`; delete `_fetch_conversation_history`; update the call site at `:4953`)
- Create: `tests/conversation/test_build_history.py`

**Interfaces:**
- `_build_history(session, conv, limit: int | None = None) -> list[dict]` — `limit=None` ⇒ `get_settings().conversation_history_limit`.
- Consumes `Message.payload` keys: `display_text`/`cart_snapshot` (order), `title`/`id` (replies), `body`/`buttons` (interactive), `text` (text/audio), `latitude`/`longitude` (location).

- [ ] **Step 1 (failing tests): write the per-branch + merge + window suite**
  Create `tests/conversation/test_build_history.py`:

```python
import pytest

from app.conversation.engine import _build_history
from app.conversation.models import Conversation, Message
from app.conversation.service import record_message


async def _conv(session, restaurant):
    conv = Conversation(restaurant_id=restaurant.id, phone="971500000080",
                        counterpart="customer", state={})
    session.add(conv)
    await session.flush()
    return conv


@pytest.mark.asyncio
async def test_order_turn_renders_basket_not_placeholder(db_session, restaurant):
    conv = await _conv(db_session, restaurant)
    await record_message(
        db_session, conversation_id=conv.id, direction="inbound",
        wa_message_id="o1", msg_type="order",
        payload={"product_items": [{"product_retailer_id": "x", "quantity": 2}],
                 "display_text": "2x Chicken Biryani",
                 "cart_snapshot": [{"cart_item_id": 1, "dish": "Chicken Biryani",
                                    "variant": None, "note": None, "qty": 2, "price": "20"}]},
        ts=10,
    )
    await db_session.flush()
    hist = await _build_history(db_session, conv)
    assert hist and "[order]" not in hist[0]["content"]
    assert "Chicken Biryani" in hist[0]["content"]
    assert hist[0]["role"] == "user"


@pytest.mark.asyncio
async def test_list_reply_and_buttons_and_cta_rendered(db_session, restaurant):
    conv = await _conv(db_session, restaurant)
    await record_message(db_session, conversation_id=conv.id, direction="inbound",
        wa_message_id="l1", msg_type="list_reply",
        payload={"id": "dish_42", "title": "Chicken Biryani"}, ts=10)
    await record_message(db_session, conversation_id=conv.id, direction="outbound",
        wa_message_id=None, msg_type="buttons",
        payload={"body": "Confirm your order?",
                 "buttons": [{"id": "confirm_order", "title": "Confirm"},
                             {"id": "cancel_order", "title": "Cancel"}]}, ts=11)
    await record_message(db_session, conversation_id=conv.id, direction="outbound",
        wa_message_id=None, msg_type="cta_url",
        payload={"body": "Track your order", "button_label": "Track", "url": "http://x"}, ts=12)
    await db_session.flush()
    hist = await _build_history(db_session, conv)
    blob = " ".join(h["content"] for h in hist)
    assert "[list_reply]" not in blob and "[buttons" not in blob and "[cta_url]" not in blob
    assert "Chicken Biryani" in blob          # list_reply title
    assert "Confirm" in blob and "Cancel" in blob  # button options visible (DB-H12)
    assert "Track your order" in blob


@pytest.mark.asyncio
async def test_consecutive_same_role_merged(db_session, restaurant):
    conv = await _conv(db_session, restaurant)
    for i, t in enumerate(["1 chicken biryani", "make it 2", "double masala"]):
        await record_message(db_session, conversation_id=conv.id, direction="inbound",
            wa_message_id=f"t{i}", msg_type="text", payload={"text": t}, ts=10 + i)
    await db_session.flush()
    hist = await _build_history(db_session, conv)
    user_turns = [h for h in hist if h["role"] == "user"]
    assert len(user_turns) == 1, f"consecutive user turns not merged: {hist}"
    assert "make it 2" in user_turns[0]["content"] and "double masala" in user_turns[0]["content"]


@pytest.mark.asyncio
async def test_window_is_configurable(db_session, restaurant, monkeypatch):
    conv = await _conv(db_session, restaurant)
    for i in range(8):
        await record_message(db_session, conversation_id=conv.id,
            direction="inbound" if i % 2 == 0 else "outbound",
            wa_message_id=f"w{i}", msg_type="text", payload={"text": f"m{i}"}, ts=100 + i)
    await db_session.flush()
    hist_default = await _build_history(db_session, conv)        # default 20 → all 8
    assert sum(len(h["content"].split()) for h in hist_default) >= 8
    hist_small = await _build_history(db_session, conv, limit=2)  # only last 2 rows
    assert "m0" not in " ".join(h["content"] for h in hist_small)


@pytest.mark.asyncio
async def test_body_normalised_to_delivered_form(db_session, restaurant):
    conv = await _conv(db_session, restaurant)
    await record_message(db_session, conversation_id=conv.id, direction="outbound",
        wa_message_id=None, msg_type="text", payload={"body": "**Menu** ready"}, ts=10)
    await db_session.flush()
    hist = await _build_history(db_session, conv)
    # Markdown ** must be rendered as the WhatsApp-delivered *bold* (DB-H2).
    assert "**" not in hist[-1]["content"]
    assert "*Menu*" in hist[-1]["content"]


@pytest.mark.asyncio
async def test_dead_fetch_builder_removed():
    import app.conversation.engine as engine
    assert not hasattr(engine, "_fetch_conversation_history"), (
        "dead _fetch_conversation_history must be deleted (F67/F69/R-083)"
    )
```

  Run: `.venv/bin/pytest tests/conversation/test_build_history.py -v` → **RED**.

- [ ] **Step 2 (implement): add the settings field**
  In `src/app/config.py`, near the other ints, add:
```python
    conversation_history_limit: int = 20  # R-080/F55: LLM history window (turns)
```

- [ ] **Step 3 (implement): rewrite `_build_history` and delete the dead builder**
  In `src/app/conversation/engine.py`, **delete** `_fetch_conversation_history` (currently `:3010-3045`) entirely. Replace `_build_history` (`:3181-3226`) with:

```python
def _render_history_content(msg) -> str:
    """Render one stored Message into LLM-readable content. Covers every
    Message.type so nothing falls through to an opaque '[type]' (R-078/82/84,
    DB-H8/12/13). Body is normalised to the delivered WhatsApp form (DB-H2)."""
    from app.outbox.service import to_whatsapp_text

    payload = msg.payload or {}
    mtype = msg.type

    if mtype == "order":
        # Catalogue basket → readable basket from the snapshot persisted at record
        # time (R-077/F63). Fall back to product_items count if older row.
        dt = (payload.get("display_text") or "").strip()
        if dt:
            return f"[sent catalogue basket: {dt}]"
        snap = payload.get("cart_snapshot") or []
        if snap:
            parts = [f"{l.get('qty', 1)}x {l.get('dish', 'item')}" for l in snap]
            return f"[sent catalogue basket: {'; '.join(parts)}]"
        n = len(payload.get("product_items") or [])
        return f"[sent catalogue basket: {n} item(s)]"

    if mtype in ("text", "audio"):
        # Voice notes (type 'audio') carry their transcript under 'text'.
        return to_whatsapp_text(payload.get("text") or payload.get("body") or "")

    if mtype == "location":
        lat = payload.get("latitude", "")
        lng = payload.get("longitude", "")
        return f"[customer shared location pin: {lat},{lng}]"

    if mtype == "button_reply":
        title = payload.get("title") or payload.get("id") or "button"
        bid = payload.get("id")
        return f"[tapped: {title}" + (f" ({bid})]" if bid else "]")

    if mtype == "list_reply":
        title = payload.get("title") or payload.get("id") or "item"
        return f"[selected: {title}]"

    if mtype == "buttons":
        body = to_whatsapp_text(payload.get("body") or "")
        titles = [b.get("title", "") for b in (payload.get("buttons") or []) if b.get("title")]
        opts = f" [options: {' | '.join(titles)}]" if titles else ""
        return (body + opts).strip() or "[buttons sent]"

    if mtype in ("cta_url", "location_request"):
        body = to_whatsapp_text(payload.get("body") or "")
        label = payload.get("button_label")
        return (body + (f" [button: {label}]" if label else "")).strip() or f"[{mtype}]"

    if mtype == "product_list":
        return "[sent menu / product cards]"

    # Any other type still gets its best human text, never a bare placeholder.
    text = payload.get("text") or payload.get("body") or payload.get("caption")
    return to_whatsapp_text(text) if text else f"[{mtype}]"


async def _build_history(
    session: AsyncSession,
    conv: Conversation,
    limit: int | None = None,
) -> list[dict]:
    """Single source of truth for LLM conversation history.

    Orders by canonical (ts, id) (DB-H7), renders every Message.type via
    _render_history_content, merges consecutive same-role turns (R-079), and uses
    a configurable window (R-080/F55). Returns OpenAI-style [{role, content}].
    """
    from app.config import get_settings
    from app.conversation.models import Message

    if limit is None:
        limit = get_settings().conversation_history_limit

    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.ts.desc(), Message.id.desc())
            .limit(limit)
        )
    ).all()
    rows = list(reversed(rows))  # oldest first, canonical (ts, id)

    raw: list[dict] = []
    for msg in rows:
        content = _render_history_content(msg)
        if not content:
            continue
        role = "user" if msg.direction == "inbound" else "assistant"
        raw.append({"role": role, "content": content})

    # Merge consecutive same-role turns so the model never sees user,user,user
    # (R-079) — rapid mixed inbound types (order + text + audio) collapse to one.
    merged: list[dict] = []
    for item in raw:
        if merged and merged[-1]["role"] == item["role"]:
            merged[-1]["content"] += "\n" + item["content"]
        else:
            merged.append({"role": item["role"], "content": item["content"]})

    # OpenAI/most providers require the first turn to be 'user'.
    if merged and merged[0]["role"] == "assistant":
        merged.insert(0, {"role": "user", "content": "hi"})
    return merged
```

  Update the call site at `engine.py:4953` to drop the hardcoded `limit=10`:
```python
    history = await _build_history(session, conv)
```

- [ ] **Step 4 (GREEN):** `.venv/bin/pytest tests/conversation/test_build_history.py -v` → PASS.
- [ ] **Step 5: regression — anything importing the dead builder must be gone:**
  Run: `grep -rn "_fetch_conversation_history" src tests` → expect **no matches**.
  Run: `.venv/bin/pytest tests/conversation -v` → PASS.
- [ ] **Step 6: commit**
```bash
git add src/app/config.py src/app/conversation/engine.py tests/conversation/test_build_history.py
git commit -m "refactor(engine): single _build_history with per-type branches, merge, configurable window; delete dead _fetch_conversation_history (R-078/79/80/83/84, F55/56/67/69, DB-H2/7/12/13)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Structured `cart_state` into context + DB-precedence; Fake agent consumes it (R-072/73/74/76, R-060)

The interpreter currently sees only the prose `context["cart_summary"]`. Add `context["cart_state"]` — an array of `{cart_item_id, dish, variant, note, qty, price}` built from the DB — and instruct the agent that this DB cart is authoritative over any history prose (R-074). `FakeConversationAgent` is updated to read `cart_state` so the eval harness drives a structured correction (`"only 1 chicken biryani"` → `update_qty`) deterministically; the production prompts (`claude.py`, `deepseek.py`) gain the same DB-precedence framing.

**Files:**
- Modify: `src/app/conversation/engine.py` (`_build_cart_state`, `_build_context`)
- Modify: `src/app/llm/fake.py` (`FakeConversationAgent.respond` ordering branch)
- Modify: `src/app/llm/deepseek.py` and `src/app/llm/claude.py` (prompt: CART STATE + precedence line)
- Create: `tests/conversation/test_cart_state_context.py`

**Interfaces:**
- `_build_cart_state(session, conv) -> list[dict]` next to `_build_cart_summary`.
- `_build_context` sets `ctx["cart_state"]` in `ordering` and `address_capture` phases (alongside `cart_summary`).
- `ConversationAgentResult` unchanged; the Fake's `update_qty` returns `action_data={"items": [{"dish_query","qty"}]}` (matches the existing multi-update shape consumed by `_dispatch_action`).

- [ ] **Step 1 (failing tests):** Create `tests/conversation/test_cart_state_context.py`:

```python
import pytest

from app.conversation.engine import _build_cart_state, _build_context
from app.llm.fake import FakeConversationAgent
from app.ordering.service import add_item, create_draft_order, get_or_create_customer
from app.conversation.models import Conversation


async def _conv_with_cart(session, restaurant, seed_biryani_menu, qty=2):
    from app.menu.models import Dish
    from sqlalchemy import select
    conv = Conversation(restaurant_id=restaurant.id, phone="971500000090",
                        counterpart="customer", state={})
    session.add(conv)
    await session.flush()
    cust = await get_or_create_customer(session, restaurant_id=restaurant.id,
                                        phone="971500000090")
    order = await create_draft_order(session, restaurant_id=restaurant.id,
                                     customer_id=cust.id)
    dish = await session.scalar(
        select(Dish).where(Dish.restaurant_id == restaurant.id,
                           Dish.name.ilike("%chicken biryani%")))
    await add_item(session, order=order, dish=dish, qty=qty)
    conv.state = {"draft_order_id": order.id, "dialogue_phase": "ordering"}
    await session.flush()
    return conv


@pytest.mark.asyncio
async def test_build_cart_state_is_structured(db_session, restaurant, seed_biryani_menu):
    conv = await _conv_with_cart(db_session, restaurant, seed_biryani_menu, qty=2)
    state = await _build_cart_state(db_session, conv)
    assert isinstance(state, list) and len(state) == 1
    line = state[0]
    assert {"cart_item_id", "dish", "variant", "note", "qty", "price"} <= set(line)
    assert line["qty"] == 2
    assert "biryani" in line["dish"].lower()


@pytest.mark.asyncio
async def test_context_exposes_cart_state(db_session, restaurant, seed_biryani_menu):
    conv = await _conv_with_cart(db_session, restaurant, seed_biryani_menu)
    ctx = await _build_context(db_session, conv, restaurant.id, "ordering", restaurant)
    assert isinstance(ctx.get("cart_state"), list) and ctx["cart_state"]


@pytest.mark.asyncio
async def test_fake_agent_corrects_qty_from_cart_state():
    agent = FakeConversationAgent()
    result = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "only 1 chicken biryani"}],
        context={"cart_summary": "2x Chicken Biryani",
                 "cart_state": [{"cart_item_id": 5, "dish": "Chicken Biryani",
                                 "variant": None, "note": None, "qty": 2, "price": "20"}]},
    )
    assert result.action == "update_qty", result
    items = result.action_data.get("items") or []
    assert items and items[0]["qty"] == 1
    assert "biryani" in items[0]["dish_query"].lower()
```

  Run → **RED** (`_build_cart_state` missing; Fake returns add_item).

- [ ] **Step 2 (implement `_build_cart_state` + context):** In `engine.py`, after `_build_cart_summary` (`:3136`):

```python
async def _build_cart_state(session: AsyncSession, conv) -> list[dict]:
    """Structured projection of the live DB cart for the interpreter (R-072).

    The interpreter receives this array (not only the prose cart_summary) and is
    told the DB cart is authoritative over history prose (R-074). Each line carries
    a stable cart_item_id so the model can address a specific line for corrections.
    """
    from app.ordering.models import Order, OrderItem

    draft_order_id = conv.state.get("draft_order_id")
    if not draft_order_id:
        return []
    order = await session.get(Order, draft_order_id)
    if order is None:
        return []
    items = list((await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all())
    return [
        {
            "cart_item_id": it.id,
            "dish": it.dish_name,
            "variant": it.variant_name,
            "note": it.notes,
            "qty": it.qty,
            "price": str(it.price_aed),
        }
        for it in items
    ]
```

  In `_build_context`, set `cart_state` wherever `cart_summary` is set (ordering at `:3313`, address_capture at `:3316`):
```python
        ctx["cart_summary"] = await _build_cart_summary(session, conv)
        ctx["cart_state"] = await _build_cart_state(session, conv)
```

- [ ] **Step 3 (implement Fake correction):** In `src/app/llm/fake.py`, in the `ordering` branch of `FakeConversationAgent.respond`, **before** the quantity-prefix add (just after the multi-dish `update_qty` block, ~L194), add a structured-correction rule that consults `context["cart_state"]`:

```python
            # Structured correction: "only/just N <dish>" sets the qty of the
            # matching DB cart line (R-072/R-074). Uses context['cart_state'] —
            # the authoritative DB cart — not the prose summary or history.
            _cart_state = context.get("cart_state") or []
            _m_only = re.match(r'^\s*(?:only|just)\s+(\d+)\s+(.*\S)', last_user)
            if _m_only and _cart_state:
                _q = int(_m_only.group(1))
                _query = _m_only.group(2).strip()
                for _line in _cart_state:
                    if _query in (_line.get("dish") or "").lower():
                        return ConversationAgentResult(
                            message="Updated!", action="update_qty",
                            action_data={"items": [{"dish_query": _line["dish"], "qty": _q}]},
                        )
```

- [ ] **Step 4 (implement prompt precedence — production parity):** In `src/app/llm/deepseek.py` and `src/app/llm/claude.py`, where the prompt template renders `CURRENT CART: {cart_summary}`, add the structured state and a precedence line. In each `respond(...)` `.format(...)` call add `cart_state=json.dumps(context.get("cart_state") or [], ensure_ascii=False)` and extend the template block:
```
CURRENT CART (authoritative — overrides anything in the chat history): {cart_summary}
CART STATE (structured; each line has cart_item_id you may reference): {cart_state}
If the chat history and the CURRENT CART disagree, the CURRENT CART is correct.
```
  (Import `json` at top of each module if not already imported. This is prompt text only — no behavioural test asserts the string, but `tests/llm/test_*` import-smoke must still pass.)

- [ ] **Step 5 (GREEN):** `.venv/bin/pytest tests/conversation/test_cart_state_context.py -v` → PASS.
- [ ] **Step 6: regression:** `.venv/bin/pytest tests/llm tests/conversation -v` → PASS.
- [ ] **Step 7: commit**
```bash
git add src/app/conversation/engine.py src/app/llm/fake.py src/app/llm/deepseek.py src/app/llm/claude.py tests/conversation/test_cart_state_context.py
git commit -m "feat(llm): structured cart_state in context + DB-cart precedence over history prose (R-072/073/074/076)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Normalise phone in the catalogue handler → single conversation thread (F71, R-027)

`handle_catalog_order` calls `get_or_create_conversation(..., phone=inbound.from_phone)` without `normalize_phone`, so a `+971…` basket and a `971…` text can split into two `conversations` rows — and the correction turn loses the basket from history.

**Files:**
- Modify: `src/app/catalog/service.py` (`handle_catalog_order`)
- Create: `tests/catalog/test_catalog_phone_normalization.py`

- [ ] **Step 1 (failing test):** Create `tests/catalog/test_catalog_phone_normalization.py`:

```python
import pytest
from sqlalchemy import func, select

from app.catalog.service import handle_catalog_order
from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.whatsapp.port import InboundMessage, MessageType


@pytest.mark.asyncio
async def test_basket_and_text_share_one_conversation(db_session, restaurant, seed_biryani_menu):
    # Basket arrives on the '+'-prefixed number.
    order_in = InboundMessage(
        wa_message_id="o-1", from_phone="+971500000099", type=MessageType.ORDER,
        payload={"product_items": [{"product_retailer_id": "ju9f8jfy90", "quantity": 1}]},
        restaurant_phone=restaurant.phone, timestamp=1_700_000_000)
    await handle_catalog_order(db_session, order_in, restaurant_id=restaurant.id)
    # Follow-up text arrives without the '+'.
    text_in = InboundMessage(
        wa_message_id="t-1", from_phone="971500000099", type=MessageType.TEXT,
        payload={"text": "anything else"}, restaurant_phone=restaurant.phone,
        timestamp=1_700_000_001)
    await handle_inbound(db_session, text_in, restaurant_id=restaurant.id)
    await db_session.flush()

    n = await db_session.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.restaurant_id == restaurant.id,
            Conversation.phone.in_(["971500000099", "+971500000099"]),
        )
    )
    assert n == 1, f"catalogue basket split the conversation thread: {n} rows (F71)"
```

  Run → **RED** (two conversation rows).

- [ ] **Step 2 (implement):** In `handle_catalog_order`, import and apply `normalize_phone`:
```python
    from app.identity.phones import normalize_phone

    _phone = normalize_phone(inbound.from_phone)
    conv = await get_or_create_conversation(
        session, restaurant_id=restaurant_id, phone=_phone, counterpart="customer",
    )
```
  (`get_or_create_customer` already normalises internally; if it does not in this codebase, pass `_phone` there too — verify with `grep -n "def get_or_create_customer" src/app/ordering/service.py` and normalise at the call site if needed.)

- [ ] **Step 3 (GREEN):** `.venv/bin/pytest tests/catalog/test_catalog_phone_normalization.py -v` → PASS.
- [ ] **Step 4: commit**
```bash
git add src/app/catalog/service.py tests/catalog/test_catalog_phone_normalization.py
git commit -m "fix(catalog): normalize phone in catalogue handler so basket + text share one thread (F71/R-027)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Graduate W7a — flip basket-visible + structured-cart-correction

Tasks 3–6 should now make two of the three W7 evals pass. Confirm they XPASS, then remove their `xfail` markers so they become permanent regression guards (they are "done" only once green and graduated).

**Files:**
- Modify: `tests/evals/test_response_accuracy_suite.py` (remove 2 markers)
- Reference: `tests/evals/REGISTRY.md` (update status if it tracks per-eval state)

- [ ] **Step 1: confirm both XPASS** (strict xfail makes an unexpected pass a failure, so run without strict first to observe):
  Run: `.venv/bin/pytest tests/evals/test_response_accuracy_suite.py -k "basket_visible or structured_cart" -rX -v`
  Expected: both report **XPASS**. If either still XFAILs, debug with `superpowers:systematic-debugging` against Tasks 3–5 before removing markers.

- [ ] **Step 2: remove the two `@pytest.mark.xfail(...)` decorators** from `test_basket_visible_in_history` and `test_structured_cart_drives_correction`. Leave `test_all_customer_outbounds_recorded` xfail (flips in Task 12).

- [ ] **Step 3 (GREEN as regular tests):** `.venv/bin/pytest tests/evals/test_response_accuracy_suite.py -k "basket_visible or structured_cart" -v` → 2 PASS.

- [ ] **Step 4: full eval suite still green (no strict xpass elsewhere):**
  Run: `.venv/bin/pytest tests/evals -v`

- [ ] **Step 5: commit (W7a complete)**
```bash
git add tests/evals/test_response_accuracy_suite.py tests/evals/REGISTRY.md
git commit -m "test(evals): graduate basket-in-history + structured-cart correction to regression (W7a, R-029/R-030/R-072)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## W7b — Transcript completeness, delivery truth & replay

### Task 8: Migration — `messages.outbox_id / delivery_status / ai_decision / state_snapshot` + updated_at trigger (DB-H9/10/15 schema)

Add the storage W7b needs. All four are columns on the **existing** `messages` table, so no new `alembic/env.py` / `tests/conftest.py` import is required. Because W7b now UPDATEs message rows, also create the missing `trg_messages_updated_at BEFORE UPDATE` trigger (the `set_updated_at()` function already exists).

**Files:**
- Modify: `src/app/conversation/models.py` (`Message`: 4 new mapped columns)
- Create: `alembic/versions/m7a1b2c3d4e5_messages_delivery_and_replay.py`
- Create: `tests/conversation/test_message_replay_columns.py`

**Interfaces:** current head is `l5e6f7a8b9c0` (verify: `.venv/bin/alembic heads`). New revision `m7a1b2c3d4e5`, `down_revision="l5e6f7a8b9c0"`.

- [ ] **Step 1 (failing test): assert the columns exist + round-trip**
  Create `tests/conversation/test_message_replay_columns.py`:

```python
import pytest
from sqlalchemy import select

from app.conversation.models import Conversation, Message


@pytest.mark.asyncio
async def test_message_has_replay_columns(db_session, restaurant):
    conv = Conversation(restaurant_id=restaurant.id, phone="971500000100",
                        counterpart="customer", state={})
    db_session.add(conv)
    await db_session.flush()
    msg = Message(
        conversation_id=conv.id, direction="outbound", wa_message_id=None,
        type="text", payload={"body": "hi"}, ts=1,
        outbox_id=None, delivery_status="pending",
        ai_decision={"action": "add_item"}, state_snapshot={"dialogue_phase": "ordering"},
    )
    db_session.add(msg)
    await db_session.flush()
    got = await db_session.scalar(select(Message).where(Message.id == msg.id))
    assert got.delivery_status == "pending"
    assert got.ai_decision == {"action": "add_item"}
    assert got.state_snapshot == {"dialogue_phase": "ordering"}
    assert got.outbox_id is None
```

  Run → **RED** (`TypeError: 'outbox_id' is an invalid keyword`).

- [ ] **Step 2 (implement model):** In `src/app/conversation/models.py`, extend `Message` (keep imports; add `Integer`/`ForeignKey` already imported; `JSONB` imported):
```python
    # W7b — delivery coupling + per-turn replay (DB-H9/10/15)
    outbox_id: Mapped[int | None] = mapped_column(
        ForeignKey("outbox_messages.id"), nullable=True, index=True
    )
    delivery_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_decision: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    state_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 3 (implement migration):** Create `alembic/versions/m7a1b2c3d4e5_messages_delivery_and_replay.py`:

```python
"""messages: delivery coupling + per-turn AI decision/state snapshot (W7b)

Adds outbox_id (FK outbox_messages), delivery_status, ai_decision (JSONB),
state_snapshot (JSONB) to the existing messages table. Also installs the missing
BEFORE UPDATE trg_messages_updated_at trigger (set_updated_at() already exists)
because W7b now updates message rows on delivery backfill.

Revision ID: m7a1b2c3d4e5
Revises: l5e6f7a8b9c0
Create Date: 2026-06-30
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "m7a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "l5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("outbox_id", sa.BigInteger(), nullable=True))
    op.add_column("messages", sa.Column("delivery_status", sa.String(length=16), nullable=True))
    op.add_column("messages", sa.Column("ai_decision", postgresql.JSONB(), nullable=True))
    op.add_column("messages", sa.Column("state_snapshot", postgresql.JSONB(), nullable=True))
    op.create_index("ix_messages_outbox_id", "messages", ["outbox_id"])
    op.create_foreign_key(
        "fk_messages_outbox_id", "messages", "outbox_messages", ["outbox_id"], ["id"]
    )
    # messages had no updated_at trigger before W7b; add it now (function exists).
    op.execute(
        "CREATE TRIGGER trg_messages_updated_at BEFORE UPDATE ON messages "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_messages_updated_at ON messages;")
    op.drop_constraint("fk_messages_outbox_id", "messages", type_="foreignkey")
    op.drop_index("ix_messages_outbox_id", table_name="messages")
    op.drop_column("messages", "state_snapshot")
    op.drop_column("messages", "ai_decision")
    op.drop_column("messages", "delivery_status")
    op.drop_column("messages", "outbox_id")
```

- [ ] **Step 4: apply to dev + verify single head**
  Run: `.venv/bin/alembic upgrade head && .venv/bin/alembic heads`
  Expected: head `m7a1b2c3d4e5` (single head). (Conftest builds the test schema via `create_all`, so the test DB gets the columns from the model.)

- [ ] **Step 5 (GREEN):** `.venv/bin/pytest tests/conversation/test_message_replay_columns.py -v` → PASS.
- [ ] **Step 6: migration round-trips:** `.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` → clean.
- [ ] **Step 7: commit**
```bash
git add src/app/conversation/models.py alembic/versions/m7a1b2c3d4e5_messages_delivery_and_replay.py tests/conversation/test_message_replay_columns.py
git commit -m "feat(db): messages.outbox_id/delivery_status/ai_decision/state_snapshot + updated_at trigger (DB-H9/10/15)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: One `record_outbound` helper; record ALL customer-facing outbounds; normalise body (DB-H2/3/4/5)

Today `send_catalog` (catalog cards), the STT-fail apology, the webhook error apology and the keyword-catalog path write to the outbox but **not** to `messages`. Introduce one helper `record_outbound(...)` in `conversation/service.py` that records an outbound `Message` with the body normalised to the delivered form, then call it from every outbound path. Route the keyword-catalog through a conversation thread so its inbound + outbound both land (DB-H3).

**Files:**
- Modify: `src/app/conversation/service.py` (add `record_outbound`)
- Modify: `src/app/catalog/service.py` (`send_catalog` records a `product_list` outbound; DB-H4)
- Modify: `src/app/conversation/engine.py` (STT-fail apology records; DB-H5)
- Modify: `src/app/webhook/router.py` (keyword-catalog records inbound+outbound DB-H3; `_send_error_apology` records DB-H5)
- Create: `tests/conversation/test_outbound_recording.py`

**Interfaces:**
- `record_outbound(session, *, conversation_id, msg_type, payload, wa_message_id=None, outbox_id=None, delivery_status="pending", ts=0) -> Message` — normalises `payload["body"]` via `to_whatsapp_text`.

- [ ] **Step 1 (failing tests):** Create `tests/conversation/test_outbound_recording.py`:

```python
import pytest
from sqlalchemy import select

from app.catalog.service import send_catalog
from app.conversation.models import Conversation, Message
from app.conversation.service import record_outbound, get_or_create_conversation


@pytest.mark.asyncio
async def test_record_outbound_normalises_body(db_session, restaurant):
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="971500000110", counterpart="customer")
    await record_outbound(db_session, conversation_id=conv.id, msg_type="text",
                          payload={"body": "**Bold** menu"})
    await db_session.flush()
    msg = await db_session.scalar(
        select(Message).where(Message.conversation_id == conv.id))
    assert "**" not in msg.payload["body"] and "*Bold*" in msg.payload["body"]


@pytest.mark.asyncio
async def test_send_catalog_records_product_list(db_session, restaurant, seed_biryani_menu):
    await send_catalog(db_session, restaurant_id=restaurant.id,
                       to_phone="971500000111", idempotency_key="cat-1")
    await db_session.flush()
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.restaurant_id == restaurant.id,
                                   Conversation.phone == "971500000111"))
    assert conv is not None, "send_catalog must land on a conversation thread (DB-H3)"
    out = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id,
                              Message.direction == "outbound"))).all()
    assert any(m.type == "product_list" for m in out), f"catalog cards not recorded: {[m.type for m in out]}"
```

  Run → **RED**.

- [ ] **Step 2 (implement `record_outbound`):** In `src/app/conversation/service.py`, after `record_message` (`:181`):
```python
async def record_outbound(
    session: AsyncSession,
    *,
    conversation_id: int,
    msg_type: str,
    payload: dict,
    wa_message_id: str | None = None,
    outbox_id: int | None = None,
    delivery_status: str | None = "pending",
    ts: int = 0,
) -> Message:
    """Record any customer-facing outbound in `messages` with the body normalised
    to the WhatsApp-delivered form (DB-H2). Shared by every send path so the
    transcript is complete (DB-H3/4/5)."""
    from app.outbox.service import to_whatsapp_text

    body = payload.get("body")
    if isinstance(body, str):
        payload = {**payload, "body": to_whatsapp_text(body)}
    msg = await record_message(
        session, conversation_id=conversation_id, direction="outbound",
        wa_message_id=wa_message_id, msg_type=msg_type, payload=payload, ts=ts,
    )
    msg.outbox_id = outbox_id
    msg.delivery_status = delivery_status
    return msg
```

- [ ] **Step 3 (implement `send_catalog` recording):** In `catalog/service.py`, `send_catalog` currently only enqueues. After the product_list `enqueue_message`, resolve/lookup the conversation thread and record a `product_list` outbound:
```python
    from app.conversation.service import get_or_create_conversation, record_outbound
    from app.identity.phones import normalize_phone

    _conv = await get_or_create_conversation(
        session, restaurant_id=restaurant_id,
        phone=normalize_phone(to_phone), counterpart="customer",
    )
    await record_outbound(
        session, conversation_id=_conv.id, msg_type="product_list",
        payload={"body": "[catalogue cards sent]",
                 "section_summary": [p.retailer_id for p in sendable]},
    )
```
  (Use the actual variable holding sendable products in `send_catalog` — `sendable` per `catalog/service.py:118`. If the menu fallback branch runs instead, record `msg_type="text"` with the fallback body there.)

- [ ] **Step 4 (implement STT-fail recording):** In `engine.py` STT-fail block (`:5352-5363`), after `enqueue_message(... "stt-fail-..." ...)` and before `return`, add:
```python
            await record_outbound(
                session, conversation_id=conv.id, msg_type="text",
                payload={"body": "Sorry, I couldn't catch that 🎙️. Could you type it, "
                                 "or send another voice note?"},
            )
```
  (Import `record_outbound` alongside the existing `record_message` import at `engine.py:9`.)

- [ ] **Step 5 (implement webhook DB-H3 + error apology DB-H5):** In `webhook/router.py`:
  - Keyword-catalog branch (`:118-128`): `send_catalog` now records its own outbound (Step 3) and creates the thread; additionally record the customer's inbound text so the turn is not missing — before the `send_catalog` call, `get_or_create_conversation(...)` + `record_message(... direction="inbound", msg_type="text", payload={"text": <the text>} ...)`.
  - `_send_error_apology` (`:201`): after `enqueue_message(...)`/`flush`, resolve the conversation (`get_or_create_conversation` on the fresh session) and `record_outbound(... msg_type="text", payload={"body": <apology>} ...)`.

- [ ] **Step 6 (GREEN):** `.venv/bin/pytest tests/conversation/test_outbound_recording.py -v` → PASS.
- [ ] **Step 7: regression:** `.venv/bin/pytest tests/webhook tests/catalog tests/conversation -v` → PASS.
- [ ] **Step 8: commit**
```bash
git add src/app/conversation/service.py src/app/catalog/service.py src/app/conversation/engine.py src/app/webhook/router.py tests/conversation/test_outbound_recording.py
git commit -m "feat(conversation): record ALL customer-facing outbounds via shared record_outbound; normalise body (DB-H2/3/4/5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Couple `messages`↔`outbox`; backfill `wa_message_id` + delivery status (DB-H1, DB-H15)

Capture the `outbox_id` at send time on the recorded `Message`, and have the outbox worker backfill the Meta `wa_message_id` and the `delivery_status` onto the coupled message after delivery. Support cannot match quoted replies (F24) or see `dead`/`pending` rows today.

**Files:**
- Modify: `src/app/conversation/engine.py` (`_send_text`, `_send_buttons`, `_send_cta_url`, `_send_location_request` → capture `outbox_id`, use `record_outbound`)
- Modify: `src/app/outbox/worker.py` (`_deliver_one` → backfill coupled `Message`)
- Create: `tests/outbox/test_message_delivery_coupling.py`

**Interfaces:** `enqueue_message` already returns the `OutboxMessage`; `flush` to get `row.id`, pass as `outbox_id` to `record_outbound`. Worker updates `Message` where `outbox_id == row.id`.

- [ ] **Step 1 (failing test):** Create `tests/outbox/test_message_delivery_coupling.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.conversation.models import Conversation, Message
from app.conversation.service import get_or_create_conversation, record_outbound
from app.outbox.service import enqueue_message
from app.outbox.worker import _deliver_one
from app.whatsapp.port import OutboundMessageType


@pytest.mark.asyncio
async def test_delivery_backfills_wa_message_id_and_status(db_session, restaurant, monkeypatch):
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="971500000120", counterpart="customer")
    row = await enqueue_message(
        db_session, restaurant_id=restaurant.id, to_phone="971500000120",
        msg_type=OutboundMessageType.TEXT, payload={"body": "hello"},
        idempotency_key="couple-1", mirror_rider_conversation=False)
    await db_session.flush()
    msg = await record_outbound(db_session, conversation_id=conv.id, msg_type="text",
                                payload={"body": "hello"}, outbox_id=row.id)
    await db_session.commit()

    class _Provider:
        async def send(self, _msg):
            return "wamid.TESTBACKFILL"

    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False,
                                 join_transaction_mode="create_savepoint")
    await _deliver_one(row.id, provider=_Provider(), session_factory=factory)

    refreshed = await db_session.scalar(select(Message).where(Message.id == msg.id))
    await db_session.refresh(refreshed)
    assert refreshed.wa_message_id == "wamid.TESTBACKFILL", "outbound wa_message_id not backfilled (DB-H1)"
    assert refreshed.delivery_status == "sent", f"delivery_status not coupled: {refreshed.delivery_status} (DB-H15)"
```

  Run → **RED** (worker doesn't touch messages).

- [ ] **Step 2 (implement engine sends):** Refactor each `_send_*` helper to capture `outbox_id` and record via `record_outbound`. Example for `_send_text` (`engine.py:1156`):
```python
async def _send_text(session, *, conv, inbound, restaurant_id, prefix, body):
    import time
    from app.conversation.service import record_outbound

    row = await enqueue_message(
        session, restaurant_id=restaurant_id, to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.TEXT, payload={"body": body},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )
    await session.flush()  # assign row.id for coupling
    await record_outbound(
        session, conversation_id=conv.id, msg_type="text",
        payload={"body": body}, outbox_id=row.id, ts=int(time.time()),
    )
```
  Apply the same pattern to `_send_buttons` (msg_type="buttons", payload keeps `buttons`), `_send_cta_url` (msg_type="cta_url", keep payload), `_send_location_request` (msg_type="location_request"). `record_outbound` normalises the body, so the stored body matches the delivered one (DB-H2).

- [ ] **Step 3 (implement worker backfill):** In `outbox/worker.py` `_deliver_one`, after setting `row.status`/`row.wa_message_id`, backfill the coupled message in the same transaction:
```python
        from app.conversation.models import Message

        coupled = await session.scalar(
            select(Message).where(Message.outbox_id == row.id)
        )
        if coupled is not None:
            coupled.delivery_status = row.status  # "sent" | "failed" | "dead"
            if row.wa_message_id:
                coupled.wa_message_id = row.wa_message_id
        await session.commit()
```
  (`select` is already imported in worker.py via the claim helpers; if not, add `from sqlalchemy import select`. Place the backfill before the existing `await session.commit()` and remove the duplicate commit, or fold into the try/except so both success and failure update the coupled status.)

- [ ] **Step 4 (GREEN):** `.venv/bin/pytest tests/outbox/test_message_delivery_coupling.py -v` → PASS.
- [ ] **Step 5: regression (delivery paths):** `.venv/bin/pytest tests/outbox tests/webhook -v` → PASS.
- [ ] **Step 6: commit**
```bash
git add src/app/conversation/engine.py src/app/outbox/worker.py tests/outbox/test_message_delivery_coupling.py
git commit -m "feat(outbox): couple messages<->outbox and backfill wa_message_id + delivery_status on send (DB-H1/DB-H15)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Per-turn AI decision + state snapshot; link audit to chat rows (DB-H9/10/11, R-037)

Persist, on the inbound `Message`, the AI decision (`action` + `action_data` + `phase` + provider/model) and the `conversations.state` snapshot at that turn, so support can answer "why did turn N choose `add_item`?" and "what was the cart when the customer said X?" without re-inference. Pass the source message id into cart-mutation audit rows.

**Files:**
- Modify: `src/app/conversation/engine.py` (`handle_inbound` capture inbound msg; `_handle_customer_ai`/`_dispatch_action` write `ai_decision` + `state_snapshot`; pass `source_message_id` into audit)
- Create: `tests/conversation/test_turn_persistence.py`

**Interfaces:**
- `record_message` already returns the inbound `Message`; flush to get its id, thread it through `_handle_customer_ai` → `_dispatch_action`.
- `state_snapshot` = a copy of `conv.state` taken at the start of the turn (before mutation).
- `ai_decision` = `{"action": result.action, "action_data": result.action_data, "phase": phase, "provider": <agent class name>}`.

- [ ] **Step 1 (failing test):** Create `tests/conversation/test_turn_persistence.py`:

```python
import pytest
from sqlalchemy import select

from app.conversation.models import Conversation, Message
from tests.harness.replay import drive_turns


@pytest.mark.asyncio
async def test_inbound_turn_records_ai_decision_and_state(db_session, restaurant, seed_biryani_menu):
    await drive_turns(db_session, restaurant_id=restaurant.id, phone="+971500000130",
                      turns=[{"type": "text", "text": "one chicken biryani"}])
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.restaurant_id == restaurant.id,
                                   Conversation.phone == "971500000130"))
    inbound = await db_session.scalar(
        select(Message).where(Message.conversation_id == conv.id,
                              Message.direction == "inbound", Message.type == "text"))
    assert inbound.ai_decision is not None, "AI decision not persisted (DB-H9)"
    assert inbound.ai_decision.get("action"), inbound.ai_decision
    assert inbound.state_snapshot is not None, "state snapshot not persisted (DB-H10)"
```

  Run → **RED**.

- [ ] **Step 2 (implement):**
  - In `handle_inbound`, keep the returned inbound message: `inbound_msg = await record_message(...)` (the call at `engine.py:5340`), `await session.flush()`, and stash `inbound_msg.id` so the AI path can find it. Simplest: pass the `Message` object down — `_handle_customer_ai` already receives `inbound: InboundMessage`; thread an optional `inbound_msg: Message | None = None` parameter through the customer-routing calls, or re-query by `wa_message_id` inside `_handle_customer_ai`.
  - In `_handle_customer_ai`, snapshot state before dispatch:
```python
    _state_snapshot = dict(conv.state or {})
```
  After `result = await agent.respond(...)` and before/after `_dispatch_action`, write onto the inbound message:
```python
    from app.conversation.models import Message as _Msg
    _inbound_row = await session.scalar(
        select(_Msg).where(
            _Msg.conversation_id == conv.id,
            _Msg.wa_message_id == inbound.wa_message_id,
            _Msg.direction == "inbound",
        ).order_by(_Msg.id.desc()).limit(1)
    )
    if _inbound_row is not None:
        _inbound_row.ai_decision = {
            "action": result.action,
            "action_data": result.action_data,
            "phase": phase,
            "provider": type(agent).__name__,
        }
        _inbound_row.state_snapshot = _state_snapshot
```
  - Audit link (DB-H11/R-037): where cart mutations call `record_audit(...)` in `_dispatch_action`/`_execute_ai_add_item`, pass `source_message_id=_inbound_row.id` into the audit `after`/metadata (extend the existing audit call signature if it accepts a metadata dict; otherwise include it in the `after` payload). Add a focused assertion only if `record_audit` exposes the field — keep this best-effort and do not break existing audit tests.

- [ ] **Step 3 (GREEN):** `.venv/bin/pytest tests/conversation/test_turn_persistence.py -v` → PASS.
- [ ] **Step 4: regression:** `.venv/bin/pytest tests/conversation tests/audit -v` → PASS.
- [ ] **Step 5: commit**
```bash
git add src/app/conversation/engine.py tests/conversation/test_turn_persistence.py
git commit -m "feat(conversation): persist per-turn AI decision + state snapshot; link audit to chat rows (DB-H9/10/11, R-037)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Graduate W7b — flip all-outbounds-recorded

**Files:** Modify `tests/evals/test_response_accuracy_suite.py` (remove the 3rd marker); update `tests/evals/REGISTRY.md`.

- [ ] **Step 1: confirm XPASS:** `.venv/bin/pytest tests/evals/test_response_accuracy_suite.py -k all_customer_outbounds -rX -v` → **XPASS**.
- [ ] **Step 2: remove the `@pytest.mark.xfail(...)` decorator** from `test_all_customer_outbounds_recorded`.
- [ ] **Step 3 (GREEN):** `.venv/bin/pytest tests/evals/test_response_accuracy_suite.py -k all_customer_outbounds -v` → PASS.
- [ ] **Step 4: full eval suite:** `.venv/bin/pytest tests/evals -v` → all pass / xfail as expected, no strict XPASS.
- [ ] **Step 5: commit**
```bash
git add tests/evals/test_response_accuracy_suite.py tests/evals/REGISTRY.md
git commit -m "test(evals): graduate all-outbounds-recorded to regression (W7b, DB-H3/4/5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Self-review, full matrix, ruff, graphify, understanding.txt

**Files:** none new (verification + docs housekeeping).

- [ ] **Step 1: self-review the diff** against the W7 design bullets — confirm each is covered: ORDER renders as basket (T3/T4); structured cart + DB precedence (T5); single `_build_history` + per-type branches + merge + window + dead-code delete (T4); all outbounds recorded + body normalised (T9); `wa_message_id` backfill + coupling (T10); phone normalised in catalogue handler (T6); per-turn AI decision + state snapshot + audit link (T11). Use `superpowers:requesting-code-review`.
- [ ] **Step 2: full test matrix** (per CLAUDE.md): `.venv/bin/pytest -q` (unit/integration/system/regression/smoke) plus `.venv/bin/pytest tests/evals -v`. Confirm the three W7 evals pass as regular tests and no other strict-xfail unexpectedly XPASSes.
- [ ] **Step 3: lint:** `.venv/bin/ruff check src apps tests` → clean.
- [ ] **Step 4: graph + understanding:** `/graphify . --update`; append dated bullets to `understanding.txt` summarising W7a/W7b (faithful history, structured context, full transcript, delivery truth).
- [ ] **Step 5: final commit (docs only, if any housekeeping changed)**
```bash
git add understanding.txt
git commit -m "chore(w7): full matrix green, graph + understanding updated (W7 history/DB faithfulness complete)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Coverage vs the W7 design bullets (design doc §"W7"):**

| W7 deliverable | Task(s) | Finding IDs |
|---|---|---|
| ORDER renders as readable basket, not `[order]` | 3, 4 | R-077, R-082, F63, DB-H8 |
| `display_text` + `cart_snapshot` persisted at record time | 3 | R-077/082, DB-H8 |
| Structured cart array to interpreter | 5 | R-072 |
| DB cart precedence over history prose | 5 | R-074, R-073, R-076 |
| Single `_build_history`; delete dead `_fetch_conversation_history` | 4 | F67, F69, R-083 |
| Branch for every `Message.type` (list_reply, buttons id/title) | 4 | F56, DB-H12, DB-H13 |
| Merge consecutive same-role | 4 | R-079 |
| Configurable window | 4 | R-080, F55 |
| Record ALL outbounds (catalog cards, STT-fail, error apology) | 9 | DB-H3, DB-H4, DB-H5 |
| Normalize stored body to delivered body | 4 (render) + 9 (store) | DB-H2 |
| Backfill `wa_message_id` from outbox | 10 | DB-H1 |
| Couple `messages`↔`outbox` delivery status | 8 (schema) + 10 | DB-H15 |
| Normalize phone in catalogue handler → single thread | 6 | F71, R-027 |
| Per-turn AI decision + state snapshot persistence | 8 (schema) + 11 | DB-H9, DB-H10, DB-H11, R-037 |
| Canonical `(ts, id)` ordering | 4 | DB-H7 |
| Reliability/direction labels in history | 4 (`[tapped:]`/`[sent catalogue basket:]`/role) | R-084 |

**Risks / judgement calls flagged for the executor:**

1. **Split recommended.** W7a (Tasks 1–7) and W7b (Tasks 8–13) are independently shippable. W7a is the load-bearing biryani repair; ship it first. If timeboxed, W7b (storage/replay) can follow without re-gating W7a.
2. **`cart_snapshot` lives in `payload` JSONB, not a column** (Task 3) — deliberate: it is read only by history rendering, needs no index, and avoids a migration on the hot ORDER path. The four *queryable*/*updatable* fields (`outbox_id`, `delivery_status`, `ai_decision`, `state_snapshot`) are real columns (Task 8) because they are filtered/updated by the worker and support tooling.
3. **No new table, but a new trigger.** `messages` had no `trg_messages_updated_at` (verified). Task 8 adds it because W7b is the first code to UPDATE message rows; without it `updated_at` would silently freeze. No new `env.py`/`conftest.py` import is needed (column-only change to an already-registered model).
4. **Eval realism caveat (carried from W0).** The three W7 evals run against `FakeConversationAgent`. `test_structured_cart_drives_correction` proves the *engine plumbing* (structured `cart_state` reaches the agent and an `update_qty` is dispatched against the right line) — it does **not** prove the production DeepSeek prompt obeys precedence. The prompt change (Task 5 Step 4) is shipped for parity; true coverage needs the deferred live-LLM harness. Mark the eval with the same "Fake-scoped guard" note style already used in the suite if desired.
5. **`_dispatch_action` ↔ inbound-message threading** (Task 11). The cleanest implementation threads the inbound `Message` object from `handle_inbound` down to `_handle_customer_ai`; the plan's re-query by `wa_message_id` avoids touching every call signature but adds one `SELECT`. Either is acceptable — prefer threading the object if the surrounding signatures are already being edited.
6. **Worker backfill transaction** (Task 10). `_deliver_one` already commits once; fold the coupled-`Message` update into the **same** transaction so delivery status and message status can never diverge. Watch the existing single `await session.commit()` — do not double-commit.
7. **Catalogue keyword path now creates a conversation** (Task 9 Step 5). This changes a path that previously wrote nothing; confirm `tests/webhook` does not assert "no conversation created" for the `menu` keyword (update such an assertion if present — it was the DB-H3 bug).
8. **Harness routing parity.** `tests/harness/replay.drive_turns` mirrors production routing (ORDER → `handle_catalog_order`, keyword → `send_catalog`). The W7 evals rely on that; do not "simplify" the driver to route everything through `handle_inbound`.

## Execution handoff

- **Branch:** `remediation/w7-history-db-faithfulness` off the W4(+W5/W6) integration base.
- **Order:** Tasks 1→13 sequentially. W7a (1–7) is a coherent first PR; W7b (8–13) a second. Each task is its own commit; never squash a RED into a GREEN.
- **Pre-flight each session:** `bash scripts/dev_db_bootstrap.sh` (brings `restaurant` + `restaurant_test` to head — required after Task 8's migration).
- **Per-task loop (strict TDD):** write the failing test → run it RED → implement → run it GREEN → run the task's regression slice → commit. Use `superpowers:test-driven-development` and, on any surprise, `superpowers:systematic-debugging` (never patch past a RED you don't understand).
- **Gating:** the full W0 regression suite (`tests/evals` + `tests/harness`) must stay green on every commit. A W7 eval is "done" only when green AND graduated (marker removed in Task 7 / Task 12) AND still green through Task 13.
- **Definition of done:** `basket_visible_in_history`, `structured_cart_drives_correction`, and `all_customer_outbounds_recorded` pass as **non-xfail** regression tests; `_fetch_conversation_history` is gone; `grep -rn "\\[order\\]" src/app/conversation/engine.py` shows no placeholder render path remains; `ruff` clean; `/graphify . --update` run; `understanding.txt` appended.
- **Review:** run `superpowers:requesting-code-review` before each PR; `superpowers:finishing-a-development-branch` to integrate.
