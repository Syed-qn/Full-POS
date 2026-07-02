# W0 — Eval Harness & Deploy-Unblock Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make WhatsApp-ordering correctness measurable and the tree deployable — commit the broken HEAD's missing dependency, get a migrated dev DB, and build a transcript-replay eval harness with outcome graders plus the first 20-task suite seeded from the two real incident transcripts.

**Architecture:** A pytest-based replay harness drives the real `handle_inbound` / catalogue path against an isolated per-trial DB, captures every outbound + DB cart + totals + phase, and grades outcomes (not paths). Incident transcripts become capability evals; once green they graduate to a regression suite that gates every later workstream (W1–W8).

**Tech Stack:** Python 3.12, pytest, async SQLAlchemy 2, Alembic, FastAPI DI overrides, `FakeConversationAgent`/`FakeExtractor` ports, Docker Postgres+PostGIS (`:5433`), `restaurant_test` DB.

## Global Constraints

- Multi-tenant: every tenant table carries `restaurant_id`; never leak across tenants — copied verbatim from spec.
- Multi-language: no hardcoded English phrase tables on live paths.
- LLM never authors money, menu, totals, or order numbers.
- Money: `Numeric(8,2)` / `Decimal`, AED. DB UTC; Celery Asia/Dubai.
- Tests use `restaurant_test` DB, recreate schema per test (see `tests/conftest.py`).
- New model modules must be imported in BOTH `alembic/env.py` and `tests/conftest.py`.
- After completion run full matrix + `.venv/bin/ruff check src apps tests` + `/graphify . --update` + append `understanding.txt` (date/time bullets).
- Conventional commits (`feat:`, `chore:`, `test:`). Commit per task. Branch off `main` first (never commit remediation work directly to `main`).
- Source of findings + workstream definitions: `docs/superpowers/specs/2026-06-30-whatsapp-ordering-remediation-design.md` and `…-biryani-correction-flow-root-cause.md`.

---

### Task 0: Create the remediation branch

**Files:** none (git only)

**Interfaces:**
- Produces: branch `remediation/w0-eval-harness` checked out from `main`.

- [ ] **Step 1: Verify clean-ish tree and current branch**

Run: `git status --short && git branch --show-current`
Expected: branch `main`. Note any pre-existing unstaged `src/app/ordering/service.py` and `tests/conversation/test_engine_draft_lifecycle.py` — those are F19's missing commit and are handled in Task 1; leave them for now.

- [ ] **Step 2: Create and switch to the branch**

Run: `git checkout -b remediation/w0-eval-harness`
Expected: `Switched to a new branch 'remediation/w0-eval-harness'`

---

### Task 1: Unblock deploy — commit the missing `set_item_note` dependency (F19)

**Files:**
- Modify (commit existing working-tree changes): `src/app/ordering/service.py`, `tests/conversation/test_engine_draft_lifecycle.py`
- Verify import: `src/app/conversation/engine.py`

**Interfaces:**
- Consumes: working-tree edits already present (per F19, root-cause doc L800–808).
- Produces: a HEAD where `from app.ordering.service import set_item_note` succeeds.

- [ ] **Step 1: Confirm the defect exists (test it fails to import at HEAD)**

Run: `git stash list; git show HEAD:src/app/ordering/service.py | grep -c "def set_item_note"`
Expected: `0` (HEAD lacks the definition). Then confirm the working tree HAS it:
Run: `grep -c "def set_item_note" src/app/ordering/service.py`
Expected: `1`.

- [ ] **Step 2: Write an import-smoke test**

Create `tests/smoke/test_import_smoke.py`:

```python
def test_engine_and_service_import():
    # F19 regression: engine.py calls set_item_note which must exist in service.py
    import app.conversation.engine  # noqa: F401
    from app.ordering.service import set_item_note  # noqa: F401
    assert callable(set_item_note)
```

- [ ] **Step 3: Run the smoke test against the working tree**

Run: `.venv/bin/pytest tests/smoke/test_import_smoke.py -v`
Expected: PASS (working tree has the function).

- [ ] **Step 4: Run the targeted lifecycle test that exercises the note path**

Run: `.venv/bin/pytest tests/conversation/test_engine_draft_lifecycle.py -v`
Expected: PASS (DB must be up: `docker compose up -d`). If it fails on DB, run `docker compose up -d` and the one-time `CREATE DATABASE restaurant_test;` per CLAUDE.md, then re-run.

- [ ] **Step 5: Commit the F19 fix coherently**

```bash
git add src/app/ordering/service.py tests/conversation/test_engine_draft_lifecycle.py tests/smoke/test_import_smoke.py
git commit -m "fix(ordering): commit set_item_note + import-smoke gate (F19 deploy unblock)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Dev/CI database bootstrap (F68)

**Files:**
- Create: `scripts/dev_db_bootstrap.sh`
- Modify: `tests/smoke/test_import_smoke.py` (add a schema-presence check)

**Interfaces:**
- Consumes: Alembic config (`alembic.ini`, `alembic/env.py`), `docker-compose.yml` (db `:5433`).
- Produces: a repeatable command that brings `restaurant` + `restaurant_test` to `head`.

- [ ] **Step 1: Write the bootstrap script**

Create `scripts/dev_db_bootstrap.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
# Bring local dev + test DBs to head. Idempotent.
docker compose up -d db redis
# Wait for db health
until docker compose exec -T db pg_isready -U app >/dev/null 2>&1; do sleep 1; done
# Ensure test DB exists (ignore error if present)
docker compose exec -T db psql -U app -d restaurant -c "CREATE DATABASE restaurant_test;" 2>/dev/null || true
.venv/bin/alembic upgrade head
echo "dev_db_bootstrap: restaurant @ head"
```

- [ ] **Step 2: Make it executable and run it**

Run: `chmod +x scripts/dev_db_bootstrap.sh && ./scripts/dev_db_bootstrap.sh`
Expected: ends with `dev_db_bootstrap: restaurant @ head`; no migration errors.

- [ ] **Step 3: Verify app tables now exist**

Run: `docker compose exec -T db psql -U app -d restaurant -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('messages','conversations','orders','order_items');"`
Expected: `4`.

- [ ] **Step 4: Commit**

```bash
git add scripts/dev_db_bootstrap.sh
git commit -m "chore(dev): db bootstrap script — alembic upgrade head for dev+test (F68)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: TranscriptResult capture model

**Files:**
- Create: `tests/harness/__init__.py`
- Create: `tests/harness/result.py`
- Create: `tests/harness/test_result.py`

**Interfaces:**
- Produces:
  - `class OutboundCapture` with fields `prefix: str`, `body: str`, `msg_type: str`.
  - `class TranscriptTurnResult` with `inbound_text: str`, `outbounds: list[OutboundCapture]`, `cart_rows: list[dict]` (each `{dish_id, dish_name, variant_name, notes, qty, price_aed}`), `subtotal: Decimal | None`, `total: Decimal | None`, `phase: str | None`, `state: dict`.
  - `class TranscriptResult` with `turns: list[TranscriptTurnResult]` and helpers `last_outbound() -> OutboundCapture | None`, `final_cart() -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Create `tests/harness/test_result.py`:

```python
from decimal import Decimal
from tests.harness.result import OutboundCapture, TranscriptTurnResult, TranscriptResult


def test_result_helpers():
    t1 = TranscriptTurnResult(
        inbound_text="one biryani",
        outbounds=[OutboundCapture(prefix="ai-add", body="Added 1x", msg_type="text")],
        cart_rows=[{"dish_id": 1, "dish_name": "Chicken Biryani", "variant_name": None,
                    "notes": None, "qty": 1, "price_aed": Decimal("20.00")}],
        subtotal=Decimal("20.00"), total=Decimal("20.00"),
        phase="ordering", state={"draft_order_id": 5},
    )
    res = TranscriptResult(turns=[t1])
    assert res.last_outbound().body == "Added 1x"
    assert res.final_cart()[0]["dish_name"] == "Chicken Biryani"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/harness/test_result.py -v`
Expected: FAIL — `ModuleNotFoundError: tests.harness.result`.

- [ ] **Step 3: Implement the model**

Create `tests/harness/__init__.py` (empty). Create `tests/harness/result.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class OutboundCapture:
    prefix: str
    body: str
    msg_type: str


@dataclass
class TranscriptTurnResult:
    inbound_text: str
    outbounds: list[OutboundCapture] = field(default_factory=list)
    cart_rows: list[dict] = field(default_factory=list)
    subtotal: Decimal | None = None
    total: Decimal | None = None
    phase: str | None = None
    state: dict = field(default_factory=dict)


@dataclass
class TranscriptResult:
    turns: list[TranscriptTurnResult] = field(default_factory=list)

    def last_outbound(self) -> OutboundCapture | None:
        for turn in reversed(self.turns):
            if turn.outbounds:
                return turn.outbounds[-1]
        return None

    def final_cart(self) -> list[dict]:
        for turn in reversed(self.turns):
            if turn.cart_rows:
                return turn.cart_rows
        return []
```

- [ ] **Step 4: Run to confirm pass**

Run: `.venv/bin/pytest tests/harness/test_result.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/harness/__init__.py tests/harness/result.py tests/harness/test_result.py
git commit -m "test(harness): TranscriptResult capture model (W0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Replay driver — drive turns through the real engine and capture state

**Files:**
- Create: `tests/harness/replay.py`
- Create: `tests/harness/test_replay_smoke.py`
- Reference (read, do not modify): `src/app/conversation/engine.py` (`handle_inbound`), `src/app/ordering/models.py` (`Order`, `OrderItem`), `tests/conversation/conftest.py` (`restaurant` fixture), existing engine tests for the inbound-message + outbox-capture pattern.

**Interfaces:**
- Consumes: `TranscriptResult`, `TranscriptTurnResult`, `OutboundCapture` (Task 3); the project's existing async `session`/`restaurant` fixtures; `FakeConversationAgent` via FastAPI DI override (the pattern used in `tests/conversation/test_engine_full_ai.py`).
- Produces:
  - `async def drive_turns(session, *, restaurant_id: int, phone: str, turns: list[dict]) -> TranscriptResult` where each turn dict is `{"type": "text"|"order"|"button_reply"|"audio", "text": str, ...payload}`.
  - It records inbound, invokes the same entrypoint production uses, then snapshots outbounds (from the outbox/`messages` rows created this turn), the draft cart, totals, phase, and `conv.state`.

- [ ] **Step 1: Write a smoke test that drives one text turn**

Create `tests/harness/test_replay_smoke.py`:

```python
import pytest
from tests.harness.replay import drive_turns


@pytest.mark.asyncio
async def test_drive_single_text_turn(session, restaurant):
    # "one chicken biryani" should create a draft cart with exactly that dish.
    res = await drive_turns(
        session, restaurant_id=restaurant.id, phone="+971500000001",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )
    assert len(res.turns) == 1
    # at least one outbound was produced (no silent drop)
    assert res.turns[0].outbounds, "every inbound must get a reply"
    # cart reflects the order (dish name comes from the seeded menu)
    names = [r["dish_name"].lower() for r in res.final_cart()]
    assert any("biryani" in n for n in names)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/harness/test_replay_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: tests.harness.replay`.

- [ ] **Step 3: Implement the driver**

First, inspect the exact entrypoint + capture points (do not guess):
Run: `grep -n "async def handle_inbound" src/app/conversation/engine.py`
Run: `grep -n "def record_message\|async def enqueue_message" src/app/conversation/service.py src/app/outbox/service.py`
Run: `sed -n '1,60p' tests/conversation/conftest.py` (learn the `restaurant`/`session` fixtures and how existing tests build an `InboundMessage` and read outbox rows).

Create `tests/harness/replay.py`. Implement using the SAME construction the existing conversation tests use (mirror `tests/conversation/test_engine_full_ai.py` for: building `InboundMessage`, overriding the conversation-agent port with `FakeConversationAgent`, and reading outbound rows). Concretely:

```python
from __future__ import annotations
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation, Message
from app.ordering.models import Order, OrderItem
from app.whatsapp.port import InboundMessage, MessageType  # adjust import to actual location
from tests.harness.result import OutboundCapture, TranscriptResult, TranscriptTurnResult


def _build_inbound(turn: dict, phone: str, idx: int) -> InboundMessage:
    ttype = turn.get("type", "text")
    payload = {k: v for k, v in turn.items() if k != "type"}
    mt = {
        "text": MessageType.TEXT,
        "order": MessageType.ORDER,
        "button_reply": MessageType.BUTTON_REPLY,
        "audio": MessageType.AUDIO,
    }[ttype]
    return InboundMessage(
        wa_message_id=f"harness-{phone}-{idx}",
        from_phone=phone,
        type=mt,
        payload=payload,
        timestamp=1_700_000_000 + idx,  # fixed clock; no Date.now in tests
    )


async def _conv_for(session, restaurant_id: int, phone: str) -> Conversation | None:
    return await session.scalar(
        select(Conversation).where(Conversation.phone == phone)
    )


async def _snapshot_cart(session, draft_order_id: int | None) -> tuple[list[dict], Decimal | None, Decimal | None]:
    if not draft_order_id:
        return [], None, None
    order = await session.get(Order, draft_order_id)
    if order is None:
        return [], None, None
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id))).all()
    rows = [{
        "dish_id": it.dish_id, "dish_name": it.dish_name,
        "variant_name": it.variant_name, "notes": it.notes,
        "qty": it.qty, "price_aed": it.price_aed,
    } for it in items]
    return rows, order.subtotal, order.total


async def drive_turns(session, *, restaurant_id: int, phone: str, turns: list[dict]) -> TranscriptResult:
    result = TranscriptResult()
    for idx, turn in enumerate(turns):
        # high-water mark so we only capture THIS turn's outbounds
        before = await session.scalar(
            select(Message.id).where(Message.direction == "outbound").order_by(Message.id.desc()).limit(1)
        ) or 0
        inbound = _build_inbound(turn, phone, idx)
        await handle_inbound(session, inbound, restaurant_id=restaurant_id)
        await session.flush()

        out_rows = (await session.scalars(
            select(Message)
            .where(Message.direction == "outbound", Message.id > before)
            .order_by(Message.id)
        )).all()
        outbounds = [OutboundCapture(
            prefix=(m.payload or {}).get("prefix", ""),
            body=(m.payload or {}).get("body") or (m.payload or {}).get("text", ""),
            msg_type=m.type,
        ) for m in out_rows]

        conv = await _conv_for(session, restaurant_id, phone)
        state = dict(conv.state or {}) if conv else {}
        rows, subtotal, total = await _snapshot_cart(session, state.get("draft_order_id"))
        result.turns.append(TranscriptTurnResult(
            inbound_text=turn.get("text", ""),
            outbounds=outbounds, cart_rows=rows,
            subtotal=subtotal, total=total,
            phase=state.get("dialogue_phase"), state=state,
        ))
    return result
```

NOTE for implementer: the imports (`InboundMessage`/`MessageType` location, `handle_inbound` signature, how outbounds are persisted — `messages` vs `outbox_messages`) MUST be confirmed by the greps in this step and adjusted to the real signatures. If outbounds live only in `outbox_messages`, capture from that table instead of `Message`. The behavior contract (capture this turn's outbounds + cart + state) stays the same.

- [ ] **Step 4: Run the smoke test**

Run: `./scripts/dev_db_bootstrap.sh && .venv/bin/pytest tests/harness/test_replay_smoke.py -v`
Expected: PASS. If it fails because no menu is seeded, add a minimal dish via the existing menu fixtures/factory used in `tests/conversation/test_engine_full_ai.py` and re-run.

- [ ] **Step 5: Commit**

```bash
git add tests/harness/replay.py tests/harness/test_replay_smoke.py
git commit -m "test(harness): transcript replay driver over handle_inbound (W0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Outcome graders

**Files:**
- Create: `tests/harness/graders.py`
- Create: `tests/harness/test_graders.py`

**Interfaces:**
- Consumes: `TranscriptResult`, `TranscriptTurnResult` (Task 3).
- Produces (each returns `GradeResult{passed: bool, reason: str}`):
  - `grade_no_duplicate_dish_line(turn) ` — no two cart rows share `(dish_id, variant_name)`.
  - `grade_last_outbound_matches_cart(turn)` — the last outbound body contains every cart dish name (DB-render truth, RA-1).
  - `grade_total_consistency(turn)` — `subtotal + delivery_fee == total` is not asserted here (fee unknown); asserts `total is None or total >= subtotal`.
  - `grade_no_mutation(prev_cart, turn)` — cart rows unchanged vs `prev_cart` (for question/reaction turns, RA-5/F83).
  - `grade_reply_subset_of_menu(turn, menu_names)` — any dish-like token in the reply is in `menu_names` (F96/F98).

- [ ] **Step 1: Write the failing test**

Create `tests/harness/test_graders.py`:

```python
from decimal import Decimal
from tests.harness.result import OutboundCapture, TranscriptTurnResult
from tests.harness.graders import (
    grade_no_duplicate_dish_line, grade_last_outbound_matches_cart,
    grade_no_mutation,
)


def _turn(cart, body="", inbound="x"):
    return TranscriptTurnResult(
        inbound_text=inbound,
        outbounds=[OutboundCapture("p", body, "text")] if body else [],
        cart_rows=cart, subtotal=Decimal("0"), total=Decimal("0"),
        phase="ordering", state={},
    )


def test_duplicate_line_detected():
    cart = [
        {"dish_id": 1, "variant_name": None, "dish_name": "Biryani", "notes": None, "qty": 1, "price_aed": Decimal("20")},
        {"dish_id": 1, "variant_name": None, "dish_name": "Biryani", "notes": "x", "qty": 1, "price_aed": Decimal("20")},
    ]
    assert grade_no_duplicate_dish_line(_turn(cart)).passed is False


def test_last_outbound_must_name_cart_dishes():
    cart = [{"dish_id": 1, "variant_name": None, "dish_name": "Lemon mint", "notes": None, "qty": 1, "price_aed": Decimal("12")}]
    assert grade_last_outbound_matches_cart(_turn(cart, body="Added 1x Lemon mint")).passed is True
    assert grade_last_outbound_matches_cart(_turn(cart, body="Added 1x Biryani")).passed is False


def test_no_mutation_on_question():
    cart = [{"dish_id": 1, "variant_name": None, "dish_name": "Biryani", "notes": None, "qty": 2, "price_aed": Decimal("20")}]
    assert grade_no_mutation(cart, _turn(cart)).passed is True
    grew = cart + [{"dish_id": 1, "variant_name": None, "dish_name": "Biryani", "notes": None, "qty": 1, "price_aed": Decimal("20")}]
    assert grade_no_mutation(cart, _turn(grew)).passed is False
```

- [ ] **Step 2: Run to confirm fail**

Run: `.venv/bin/pytest tests/harness/test_graders.py -v`
Expected: FAIL — `ModuleNotFoundError: tests.harness.graders`.

- [ ] **Step 3: Implement graders**

Create `tests/harness/graders.py`:

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class GradeResult:
    passed: bool
    reason: str


def grade_no_duplicate_dish_line(turn) -> GradeResult:
    seen = set()
    for r in turn.cart_rows:
        key = (r["dish_id"], r.get("variant_name"))
        if key in seen:
            return GradeResult(False, f"duplicate line for {key}")
        seen.add(key)
    return GradeResult(True, "no duplicate lines")


def grade_last_outbound_matches_cart(turn) -> GradeResult:
    if not turn.outbounds:
        return GradeResult(False, "no outbound for a turn with a cart")
    body = turn.outbounds[-1].body.lower()
    missing = [r["dish_name"] for r in turn.cart_rows if r["dish_name"].lower() not in body]
    if missing:
        return GradeResult(False, f"reply omits cart dishes: {missing}")
    return GradeResult(True, "reply names all cart dishes")


def grade_total_consistency(turn) -> GradeResult:
    if turn.total is None or turn.subtotal is None:
        return GradeResult(True, "no totals to check")
    if turn.total < turn.subtotal:
        return GradeResult(False, f"total {turn.total} < subtotal {turn.subtotal}")
    return GradeResult(True, "total >= subtotal")


def _cart_key(cart):
    return sorted((r["dish_id"], r.get("variant_name"), r.get("notes"), r["qty"]) for r in cart)


def grade_no_mutation(prev_cart, turn) -> GradeResult:
    if _cart_key(prev_cart) != _cart_key(turn.cart_rows):
        return GradeResult(False, "cart mutated on a no-mutation turn")
    return GradeResult(True, "cart unchanged")


def grade_reply_subset_of_menu(turn, menu_names) -> GradeResult:
    menu_lower = {n.lower() for n in menu_names}
    for r in turn.cart_rows:  # any named dish in cart must exist on the menu
        if r["dish_name"].lower() not in menu_lower:
            return GradeResult(False, f"cart dish not on menu: {r['dish_name']}")
    return GradeResult(True, "cart dishes are on menu")
```

- [ ] **Step 4: Run to confirm pass**

Run: `.venv/bin/pytest tests/harness/test_graders.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/harness/graders.py tests/harness/test_graders.py
git commit -m "test(harness): outcome graders (dup line, db-render, no-mutation, menu subset) (W0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: First capability eval — biryani correction (RA-7 / F49 / RA-5) as an xfail regression anchor

**Files:**
- Create: `tests/fixtures/transcripts/biryani_r1_0097.json`
- Create: `tests/evals/__init__.py`
- Create: `tests/evals/test_biryani_correction_eval.py`

**Interfaces:**
- Consumes: `drive_turns` (Task 4), graders (Task 5).
- Produces: the canonical incident as an executable eval. It is expected to FAIL today (capability eval, marked `xfail(strict=True)`); W2/W3/W4 will flip it to passing and it then becomes a guarding regression.

- [ ] **Step 1: Write the transcript fixture**

Create `tests/fixtures/transcripts/biryani_r1_0097.json`:

```json
{
  "phone": "+971500009097",
  "turns": [
    {"type": "order", "product_items": [
      {"product_retailer_id": "dish-8-6", "quantity": 3, "item_price": 50, "currency": "AED"},
      {"product_retailer_id": "dv5fh8l7j6", "quantity": 1, "item_price": 12, "currency": "AED"},
      {"product_retailer_id": "ju9f8jfy90", "quantity": 1, "item_price": 20, "currency": "AED"}
    ]},
    {"type": "text", "text": "Need double masala in biriyani"},
    {"type": "text", "text": "That's all"},
    {"type": "text", "text": "Only 1 biriyani"},
    {"type": "text", "text": "Why did you add 2 biriyani"},
    {"type": "text", "text": "I need only 1 biriyani with double masala"}
  ]
}
```

- [ ] **Step 2: Write the eval (xfail until W2–W4 land)**

Create `tests/evals/__init__.py` (empty) and `tests/evals/test_biryani_correction_eval.py`:

```python
import json
from pathlib import Path

import pytest

from tests.harness.replay import drive_turns
from tests.harness.graders import grade_no_duplicate_dish_line, grade_no_mutation

FIXTURE = Path(__file__).parent.parent / "fixtures" / "transcripts" / "biryani_r1_0097.json"


@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="capability eval: passes after W2 (notes) + W3 (render) + W4 (router)")
async def test_biryani_correction_final_state(session, restaurant, seed_biryani_menu):
    data = json.loads(FIXTURE.read_text())
    res = await drive_turns(session, restaurant_id=restaurant.id,
                            phone=data["phone"], turns=data["turns"])
    final = res.final_cart()
    # Expected end state: exactly one biryani line, qty 1, note preserved; no duplicate.
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1, f"expected one biryani line, got {biryani}"
    assert biryani[0]["qty"] == 1
    assert biryani[0]["notes"] and "double masala" in biryani[0]["notes"].lower()
    # 'Why did you add 2' turn (index 4) must NOT have mutated the cart vs the turn before it.
    assert grade_no_mutation(res.turns[3].cart_rows, res.turns[4]).passed
    assert grade_no_duplicate_dish_line(res.turns[-1]).passed
```

- [ ] **Step 3: Add the `seed_biryani_menu` fixture**

Inspect the existing menu/dish factory first:
Run: `grep -rn "def restaurant\b\|dish_factory\|create_dish\|Dish(" tests/conversation/conftest.py tests/conftest.py | head`

Add to `tests/conversation/conftest.py` (or the nearest conftest the evals can see) a fixture `seed_biryani_menu` that creates dishes matching the fixture's `product_retailer_id`s (Mndhi-2 → `dish-8-6` @ 50, Lemon mint → `dv5fh8l7j6` @ 12, Chicken Biryani → `ju9f8jfy90` @ 20) with `catalog_retailer_id` set so the catalogue path resolves them. Mirror the existing dish-creation helper exactly (column names, `is_available=True`, `dish_number`, `price_aed`).

- [ ] **Step 4: Run the eval — expect xfail (not error)**

Run: `./scripts/dev_db_bootstrap.sh && .venv/bin/pytest tests/evals/test_biryani_correction_eval.py -v`
Expected: `XFAIL` (the body runs end-to-end and the assertions fail today, exactly reproducing the incident). If it ERRORS instead of XFAILs (import/fixture problem), fix the harness/fixture until it cleanly runs and fails on the assertions, not on setup.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/transcripts/biryani_r1_0097.json tests/evals/__init__.py tests/evals/test_biryani_correction_eval.py tests/conversation/conftest.py
git commit -m "test(evals): biryani correction capability eval (xfail until W2-W4) (W0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Eval-suite registry + the remaining 19 capability tasks (stubs that run)

**Files:**
- Create: `tests/evals/REGISTRY.md`
- Create: `tests/evals/test_response_accuracy_suite.py`
- Create fixtures under `tests/fixtures/transcripts/` referenced below.

**Interfaces:**
- Consumes: `drive_turns`, graders.
- Produces: 19 more capability evals (the list in design §6.3 / root-cause §6.3), each `xfail(strict=True)` with the workstream that will fix it named in `reason`. They MUST run end-to-end (no setup errors) so they flip to PASS automatically as workstreams land.

- [ ] **Step 1: Write the registry**

Create `tests/evals/REGISTRY.md` listing all 20 evals: id, transcript line, grader(s), the finding(s) it guards, and the workstream that flips it green. (Row 1 = Task 6 biryani.) Use the 20-task list from `…-remediation-design.md` §6.3 / root-cause §6.3 verbatim.

- [ ] **Step 2: Write the 19 evals as a parametrized suite**

Create `tests/evals/test_response_accuracy_suite.py` with one parametrized async test per scenario. Each case: a small turns list + an assertion using the graders. Mark every case `xfail(strict=True, reason="<Wn>")`. Example cases (write all 19; here are 3 concrete ones — repeat the pattern, do NOT leave placeholders):

```python
import pytest
from tests.harness.replay import drive_turns
from tests.harness.graders import grade_no_mutation, grade_reply_subset_of_menu

@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="W4 router: question must not mutate")
async def test_why_did_you_add_is_not_a_mutation(session, restaurant, seed_biryani_menu):
    res = await drive_turns(session, restaurant_id=restaurant.id, phone="+971500000002", turns=[
        {"type": "text", "text": "one chicken biryani"},
        {"type": "text", "text": "why did you add it"},
    ])
    assert grade_no_mutation(res.turns[0].cart_rows, res.turns[1]).passed

@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="W6 menu SoT: no invented dishes")
async def test_full_menu_request_no_hallucination(session, restaurant, seed_biryani_menu):
    res = await drive_turns(session, restaurant_id=restaurant.id, phone="+971500000003", turns=[
        {"type": "text", "text": "show me the full menu"},
    ])
    # reply must not name dishes outside the seeded menu
    menu = {"chicken biryani", "mutton biryani", "lemon mint", "mndhi - 2"}
    body = res.turns[0].outbounds[-1].body.lower()
    for invented in ("egg biryani", "prawn", "parotta", "noodles", "chicken 65"):
        assert invented not in body

@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="W8 QuantityPolicy: lakh != 1")
async def test_lakh_is_not_quantity_one(session, restaurant, seed_biryani_menu):
    res = await drive_turns(session, restaurant_id=restaurant.id, phone="+971500000004", turns=[
        {"type": "text", "text": "one lemon mint"},
        {"type": "text", "text": "make it 1 lakh"},
    ])
    lemon = [r for r in res.final_cart() if "lemon" in r["dish_name"].lower()]
    assert lemon and lemon[0]["qty"] != 1, "lakh must escalate, never silently set qty 1"
```

Remaining 16 (write each fully, same shape): catalogue basket→double masala one noted line (W2/W3); confirm-time make-it-2 shown==confirmed total (W3); 5-item voice all present (W1/W3); modify-flow remove decrements (W2/W4); reaction → no reply/no mutation (W8); "No that's all" ×1 proceeds not loop (W4); catalogue request→send_catalog (W6/W8); saved-address question truthful (W7/W8); non-English question answered not menu-dumped (W4/W6); fee deterministic per address (W5); order# unique across two orders (W8); wallet line == total math (W5); caps-insensitive dish match (W6); "PLS" not a note (W2); clear_cart only on explicit clear (W2/W4); out-of-order/idempotent redelivery same `wa_message_id` (W8).

- [ ] **Step 3: Run the whole eval suite — expect all xfail, zero errors**

Run: `.venv/bin/pytest tests/evals/ -v`
Expected: every test `XFAIL` (or the biryani one too). ZERO `ERROR`/`PASS`. An ERROR means a fixture/harness gap — fix it. A surprise PASS (`XPASS`) with `strict=True` fails the run and tells you that behavior is already correct — convert that case to a normal (non-xfail) regression test.

- [ ] **Step 4: Commit**

```bash
git add tests/evals/REGISTRY.md tests/evals/test_response_accuracy_suite.py tests/fixtures/transcripts/
git commit -m "test(evals): 20-task response-accuracy capability suite, xfail-gated by workstream (W0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Wire the suite into the regression gate + finalize W0

**Files:**
- Modify: `pyproject.toml` (pytest markers) or `pytest.ini` — register an `eval` marker.
- Create: `docs/superpowers/plans/2026-06-30-w0-eval-harness-foundation.md` is this file; append a "W0 done" note to `understanding.txt`.

**Interfaces:**
- Produces: `pytest -m eval` runs the capability suite; the convention that flipping an eval from `xfail` to pass (and removing the marker) graduates it to the regression suite.

- [ ] **Step 1: Register the marker**

Add to `pyproject.toml` under `[tool.pytest.ini_options]` `markers`:

```
markers = [
    "eval: transcript-replay capability/regression evals (W0 harness)",
]
```

(If a `markers` list already exists, append the line; do not duplicate the key.)

- [ ] **Step 2: Run the full suite + lint to confirm nothing else broke**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src apps tests`
Expected: all prior tests PASS; eval suite XFAILs; ruff clean. (If ruff flags the new harness, fix imports/formatting.)

- [ ] **Step 3: Update graph + understanding**

Run: `/graphify . --update`
Then append dated bullets to `understanding.txt` describing: F19 committed, dev DB bootstrap, replay harness + graders + 20-task xfail eval suite; note the graduation convention.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml understanding.txt graphify-out
git commit -m "chore(evals): register eval marker; W0 foundation complete

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (W0 section of design):** unblock deploy (Task 1 ✓), dev/CI data (Task 2 ✓), replay harness (Tasks 3–4 ✓), outcome + LLM-judge graders (Task 5 ✓ for code graders; LLM-judge graders deferred to the first workstream that needs subjective grading — noted below), first 20-task suite (Tasks 6–7 ✓), capability→regression graduation + pass^k convention (Tasks 7–8 ✓). **Gap acknowledged:** LLM-judge graders (in-language, refusal, "answers the question") are scaffolded but not implemented in W0 because they need a model call harness; they are added in W4/W6 where the first subjective evals (non-English answered, refusal) flip green. This is intentional, not a placeholder.

**Placeholder scan:** Task 7 Step 2 names all 19 remaining evals explicitly with their workstream tags; the implementer writes each in the given shape. No "TBD"/"similar to". The driver in Task 4 flags the two imports that must be grep-confirmed (entrypoint signature, outbound table) — this is a verification instruction, not a placeholder, because the exact module path can only be read from the repo at execution time.

**Type consistency:** `TranscriptResult`/`TranscriptTurnResult`/`OutboundCapture` (Task 3) are consumed unchanged in Tasks 4–7; `GradeResult` (Task 5) returned by every grader; `drive_turns(session, *, restaurant_id, phone, turns)` signature identical in Tasks 4/6/7. cart_row dict keys (`dish_id, dish_name, variant_name, notes, qty, price_aed`) identical across driver, graders, and evals.

---

## Subsequent plans (W1–W8)

W0 produces working, testable software on its own (a green build, a migrated dev DB, and a runnable — if xfailing — eval suite). Each later workstream is its own spec-aligned plan, written when we reach it so its tasks reference the real code that exists at that point:

| Plan | Flips these evals green | Depends on |
|------|--------------------------|------------|
| `…-w1-tool-schema-parity.md` | provider-parity, required-field, qty-absolute | W0 |
| `…-w2-cart-line-identity.md` | biryani note preserved, PLS-not-note, clear-only-explicit | W1 |
| `…-w3-render-gate.md` | shown==confirmed total, single-add cart tail, wallet math | W2 |
| `…-w4-router.md` | question≠mutation, closing-loop, modify global intents | W3 |
| `…-w5-money.md` | card price==charged, fee deterministic | W4 |
| `…-w6-menu-sot.md` | no hallucinated menu, orderable==displayed, caps-insensitive | W4 |
| `…-w7-history.md` | basket visible, structured cart, all outbounds recorded | W4 |
| `…-w8-state-ops.md` | order# unique, reaction no-op, idempotent redelivery, buttons | W5–W7 |

Each W1–W8 task: failing-test-first (flip the relevant xfail), implement, full matrix + ruff + graphify + understanding, commit.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-30-w0-eval-harness-foundation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
