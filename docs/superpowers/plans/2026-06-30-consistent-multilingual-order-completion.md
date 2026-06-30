# Consistent, Multilingual Order-Completion Handling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "I'm done ordering" advance to address capture on the first try in any language/phrasing, and stop silently inflating the cart when the LLM mis-fires an add.

**Architecture:** Remove the brittle hardcoded English closing guard; push the completion decision into the LLM via a restructured, language-agnostic ordering prompt and tightened tool schema; add a menu-data-driven (not phrase-based) re-add backstop in the dispatch path so a mis-fired `add_item` can never increment an existing cart line.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy 2, pytest. LLM provider DeepSeek (function calling). No new dependencies.

## Global Constraints

- Multi-tenant: per-restaurant prompt variables (`restaurant_name`, menu, fees, hours, phone) stay intact; nothing tenant-specific hardcoded.
- Multilingual: completion intent must work in any language and any phrasing; no English/transliterated phrase tables drive production behavior.
- Money: cart quantities must never increase without an explicit customer add. `Numeric(8,2)` / `Decimal`, AED.
- TDD: failing test first, then implementation.
- No commits until the user explicitly authorizes (user instruction, 2026-06-30). Each task's "Commit" step is **staged but NOT committed** until then — run `git add` only, hold the commit.
- After code changes: run `/graphify . --update` per project CLAUDE.md (do at the very end, once).

## Refinements vs. approved spec (flagged for user)

1. **Backstop trigger corrected.** Spec item 4 keyed on an empty `dish_query`; the real bug carries `dish_query="<existing dish>"`. Corrected rule: a single-dish `add_item` is suppressed when the resolved dish is **already in the draft cart** AND the resolved dish's own name does not appear (normalized substring) in the customer's raw inbound text. Uses the tenant's menu name as the needle — language-agnostic, no phrase table. Tradeoff: a name-less, number-less "give me another" is suppressed (customer restates with the name or a number); far cheaper than silent overcharge.
2. **Multilingual unit tests dropped as low-value.** Faking the LLM to "understand" Arabic/Hindi only tests the test double, not real comprehension. Real multilingual completion is enforced by the prompt directives (Task 4) and validated against live DeepSeek, not unit-fakeable. Engine path is already script-agnostic; the backstop + curly-apostrophe + frustration tests cover the engine behavior.

---

## File Structure

- `src/app/llm/fake.py` — test double; broaden closing detection (apostrophe-normalize + frustration). Test-double only.
- `src/app/conversation/engine.py` — remove hardcoded closing guard; add menu-data-driven re-add backstop in `_dispatch_action`.
- `src/app/llm/deepseek.py` — restructure `_ORDERING_BLOCK` (decision order + anti-re-add) and tighten `_DS_TOOL` action descriptions.
- `tests/conversation/test_engine_ordering.py` — update existing regression to curly apostrophe + cart-quantity assertion; add backstop + frustration tests.
- `tests/llm/test_fake.py` — fake closing-detection unit tests.

---

### Task 1: Fake agent recognizes closings robustly (test double parity)

**Files:**
- Modify: `src/app/llm/fake.py:130-149`
- Test: `tests/llm/test_fake.py`

**Interfaces:**
- Consumes: `FakeConversationAgent.respond(*, restaurant_name, dialogue_phase, history, context) -> ConversationAgentResult`
- Produces: same signature; ordering-phase closings (curly apostrophe, frustration, bare "no") with a non-empty cart return `action="proceed_to_address"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/llm/test_fake.py
import pytest
from app.llm.fake import FakeConversationAgent

pytestmark = pytest.mark.asyncio


async def _closing(text: str):
    agent = FakeConversationAgent()
    return await agent.respond(
        restaurant_name="Test",
        dialogue_phase="ordering",
        history=[
            {"role": "assistant", "content": "1x Lemon mint added! Anything else?"},
            {"role": "user", "content": text},
        ],
        context={"cart_summary": "1x Lemon mint"},
    )


@pytest.mark.parametrize("text", [
    "No that’s all",          # curly apostrophe (U+2019) — production keyboard
    "That’s all",
    "thats all can't you understand",
    "no",
])
async def test_fake_closing_variants_proceed(text):
    result = await _closing(text)
    assert result.action == "proceed_to_address"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/llm/test_fake.py -v`
Expected: FAIL — curly-apostrophe and "no" variants currently return `add_item`.

- [ ] **Step 3: Write minimal implementation**

In `fake.py`, normalize the extracted `last_user` and broaden the closing branch. Replace the `last_user` extraction (around line 132-136) and the closing branch (line 144) so apostrophes are unified and bare-decline/frustration count:

```python
        last_user = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                last_user = (msg.get("content") or "").lower()
                break
        # Unify curly/smart apostrophes so "that’s all" == "that's all".
        last_user = last_user.replace("’", "'").replace("ʼ", "'")
```

```python
            # Closing / decline / impatience with a non-empty cart -> proceed.
            # Test double only; real comprehension is DeepSeek's job.
            _closing_tokens = (
                "done", "that's all", "thats all", "bas", "khalaas", "khalas",
                "proceed", "checkout", "no more", "nothing else", "nope",
            )
            _cart = (context.get("cart_summary") or "").strip()
            _is_decline = last_user.strip() in {"no", "na", "nah", "np"}
            if _cart and (_is_decline or any(w in last_user for w in _closing_tokens)):
                return ConversationAgentResult(
                    message="Great! Let me get your delivery details.",
                    action="proceed_to_address",
                    action_data={},
                )
```

Note: the old unconditional `if any(w in last_user for w in ("done", "that's all", ...))` branch at line 144 is replaced by the block above. Keep the `cancel` branch and everything after unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/llm/test_fake.py -v`
Expected: PASS (all 4 params).

- [ ] **Step 5: Stage (hold commit per Global Constraints)**

```bash
git add src/app/llm/fake.py tests/llm/test_fake.py
# DO NOT commit yet — user authorization pending.
```

---

### Task 2: Remove the hardcoded production closing guard

**Files:**
- Modify: `src/app/conversation/engine.py` — delete `_CLOSING_PHRASES` (~4559), `_normalise_closing` (~4569), `_CLOSING_FILLER` (~4582), `_is_closing` (~4589), and the bypass block inside `_handle_customer_ai` (~4670-4687).
- Test: `tests/conversation/test_engine_ordering.py:193-221`

**Interfaces:**
- Consumes: `handle_inbound(session, inbound, restaurant_id)`; `FakeConversationAgent` from Task 1 (returns `proceed_to_address` for closings).
- Produces: `_handle_customer_ai` no longer references any closing constant; all closing handling flows through the agent.

- [ ] **Step 1: Update the existing regression test to production-representative input**

Replace the loop and assertions in `test_negative_reply_advances_and_does_not_re_add` (currently line 209-221) so it (a) uses a curly apostrophe and (b) asserts the cart quantity is unchanged after every closing:

```python
    # Closings as production actually sends them (curly apostrophe U+2019), plus a
    # bare decline. None may re-add or inflate the cart line.
    for i, word in enumerate(
        ("No that’s all", "No", "Np", "That’s all", "ok done thanks")
    ):
        await handle_inbound(db_session, _msg(word, f"wamid.close{i}"), restaurant_id=restaurant.id)
        await db_session.commit()
        items = (await db_session.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id))).all()
        assert sum(it.qty for it in items) == qty_before  # never inflates

    conv = await _conv(db_session)
    assert conv.state["dialogue_state"] == "address_capture"
    assert await db_session.get(Order, order_id) is not None
```

- [ ] **Step 2: Run test to verify current state**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_negative_reply_advances_and_does_not_re_add -v`
Expected: With the guard still present and the fake from Task 1, this should PASS (fake returns proceed). If it FAILS, capture the failure — it reveals whether the guard was masking a fake gap. Proceed to remove the guard regardless.

- [ ] **Step 3: Delete the guard symbols and bypass block**

Remove these from `engine.py`:
- The `_CLOSING_PHRASES` frozenset definition.
- The `_normalise_closing` function.
- The `_CLOSING_FILLER` frozenset definition.
- The `_is_closing` function.
- The bypass block in `_handle_customer_ai` (the `if phase == "ordering" and inbound.type == MessageType.TEXT and _is_closing(...) and (context.get("cart_summary") or "").strip():` branch that dispatches a `proceed_to_address` result and returns).

Also remove any now-orphaned comment header above `_CLOSING_PHRASES` (the "A bare 'no more / that's it / done' reply ..." comment block at ~4554-4557).

Verify nothing else references the removed names:

```bash
grep -rn "_is_closing\|_CLOSING_PHRASES\|_CLOSING_FILLER\|_normalise_closing" src tests
```
Expected: no output.

- [ ] **Step 4: Run tests + lint**

Run:
```bash
.venv/bin/pytest tests/conversation/test_engine_ordering.py -v
.venv/bin/ruff check src/app/conversation/engine.py
```
Expected: PASS; lint clean (no unused-import/name errors).

- [ ] **Step 5: Stage (hold commit)**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_ordering.py
# DO NOT commit yet.
```

---

### Task 3: Menu-data-driven re-add backstop in `_dispatch_action`

**Files:**
- Modify: `src/app/conversation/engine.py` — single-dish `add_item` path (~4202-4235) inside `_dispatch_action`.
- Test: `tests/conversation/test_engine_ordering.py`

**Interfaces:**
- Consumes: parsed `ConversationAgentResult` (`action="add_item"`, `action_data["dish_query"]`, `action_data["qty"]`), `inbound.payload["text"]`, draft order id from `conv.state`.
- Produces: a single-dish `add_item` whose resolved dish is already in the cart AND whose dish name is absent from the raw customer text is suppressed (cart unchanged); the customer is nudged toward checkout instead.

- [ ] **Step 1: Write the failing test**

This test forces the exact production bug: agent returns `add_item` for a dish already in the cart while the customer's text is a closing that does not name the dish. Cart must not inflate.

```python
# tests/conversation/test_engine_ordering.py
async def test_readd_backstop_blocks_inflation_on_unnamed_add(db_session, restaurant, monkeypatch):
    """If the agent mis-fires add_item for a dish already in the cart and the
    customer's text does not name that dish, the cart line must not inflate."""
    from app.ordering.models import Order, OrderItem
    from app.llm.port import ConversationAgentResult
    import app.conversation.engine as engine

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.bg"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("lemon mint", "wamid.bi"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    order_id = conv.state["draft_order_id"]
    qty_before = sum(
        it.qty for it in (await db_session.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id))).all()
    )

    class _StubAddAgent:
        async def respond(self, **kwargs):
            # Mis-fire: add the dish already in cart, customer text won't name it.
            return ConversationAgentResult(
                message="1x Lemon mint added! Anything else?",
                action="add_item",
                action_data={"dish_query": "lemon mint", "qty": None, "items": [],
                             "special_note": "", "apt_room": "", "building": "",
                             "receiver_name": ""},
            )

    monkeypatch.setattr(engine, "get_conversation_agent", lambda: _StubAddAgent(),
                        raising=False)

    await handle_inbound(db_session, _msg("No that’s all", "wamid.bclose"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all()
    assert sum(it.qty for it in items) == qty_before  # backstop prevented inflation
```

Note: `get_conversation_agent` is imported inside `_handle_customer_ai` via `from app.llm.factory import get_conversation_agent`. For the monkeypatch to take effect, Task 3 Step 3 must bind it at module level (see implementation note) OR the test patches `app.llm.factory.get_conversation_agent`. Use the factory patch to avoid changing import style:

```python
    monkeypatch.setattr("app.llm.factory.get_conversation_agent",
                        lambda: _StubAddAgent())
```
Use this factory-path patch in the test instead of the `engine` attribute patch above.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_readd_backstop_blocks_inflation_on_unnamed_add -v`
Expected: FAIL — cart inflates from N to N+1 (current merge behavior).

- [ ] **Step 3: Implement the backstop helper + guard**

Add a small helper near the other dispatch helpers in `engine.py`:

```python
def _dish_name_in_text(dish_name: str, raw_text: str) -> bool:
    """True if the dish's own name appears in the customer's message (case/space
    -insensitive substring). Menu-data-driven, language-agnostic — no phrase table."""
    if not dish_name or not raw_text:
        return False
    norm = lambda s: _re.sub(r"\s+", " ", s.casefold()).strip()
    return norm(dish_name) in norm(raw_text)
```

In `_dispatch_action`, inside `if action == "add_item":`, single-dish branch, after `dish_query`/`qty`/`special_note` are resolved (current line ~4210) and before `_execute_ai_add_item` is called (current line ~4217-4219), insert:

```python
        if dish_query:
            raw_text = inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""
            # Re-add backstop: the agent named a dish already in the cart, but the
            # customer never named it (and gave no quantity) -> this is a mis-fired
            # add (e.g. a closing parsed as add_item). Do NOT inflate the cart.
            already = await _resolve_cart_dish(
                session,
                order_id=conv.state.get("draft_order_id"),
                candidates=(await find_dish_matches(
                    session, restaurant_id=restaurant_id, query=dish_query)).candidates,
            )
            gave_qty = data.get("qty") is not None
            if (already is not None
                    and not gave_qty
                    and not _dish_name_in_text(already.name, raw_text)):
                cart = await _build_cart_summary(session, conv)
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="ai-readd-noop",
                    body=f"You're all set 😊{_cart_tail(cart)}\nReady to checkout? Just say 'done'.",
                )
                return
            status = await _execute_ai_add_item(
                session, conv, inbound, restaurant_id, dish_query, qty, special_note
            )
            ...
```

(`find_dish_matches`, `_resolve_cart_dish`, `_build_cart_summary`, `_cart_tail`, `_send_text` already exist in the module; `_re` is the module's `import re as _re`.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_readd_backstop_blocks_inflation_on_unnamed_add -v`
Expected: PASS.

- [ ] **Step 5: Guard against false positives — a genuine repeat that NAMES the dish still adds**

Add a second test proving the backstop does NOT block a real re-order:

```python
async def test_readd_backstop_allows_named_repeat(db_session, restaurant, monkeypatch):
    """Naming the dish again (or giving a qty) is a real add — backstop must allow it."""
    from app.ordering.models import OrderItem
    from app.llm.port import ConversationAgentResult

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.rg"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("lemon mint", "wamid.ri"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    order_id = conv.state["draft_order_id"]
    qty_before = sum(it.qty for it in (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all())

    class _StubAddAgent:
        async def respond(self, **kwargs):
            return ConversationAgentResult(
                message="Added another Lemon mint! 🛒", action="add_item",
                action_data={"dish_query": "lemon mint", "qty": None, "items": [],
                             "special_note": "", "apt_room": "", "building": "",
                             "receiver_name": ""})
    monkeypatch.setattr("app.llm.factory.get_conversation_agent", lambda: _StubAddAgent())

    # Customer NAMES the dish -> real add.
    await handle_inbound(db_session, _msg("another lemon mint", "wamid.rclose"),
                         restaurant_id=restaurant.id)
    await db_session.commit()
    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all()
    assert sum(it.qty for it in items) == qty_before + 1  # named -> added
```

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py -k readd -v`
Expected: both backstop tests PASS.

- [ ] **Step 6: Stage (hold commit)**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_ordering.py
# DO NOT commit yet.
```

---

### Task 4: Restructure ordering prompt + tighten tool schema (DeepSeek)

**Files:**
- Modify: `src/app/llm/deepseek.py` — `_ORDERING_BLOCK` (~359-451), `_DS_TOOL` action descriptions (~205-227).
- Test: `tests/llm/test_deepseek_prompt.py` (new — string-presence assertions on the assembled prompt).

**Interfaces:**
- Consumes: `DeepSeekConversationAgent._build_system(restaurant_name, dialogue_phase, context)`.
- Produces: the ordering system prompt contains an explicit completion-first decision order and an anti-re-add directive; tool descriptions distinguish `proceed_to_address` (done/decline/frustration, any language) from `add_item` (new dish only, never re-add on a decline).

- [ ] **Step 1: Write the failing test**

```python
# tests/llm/test_deepseek_prompt.py
import os
import pytest


@pytest.fixture(autouse=True)
def _ds_env(monkeypatch):
    monkeypatch.setenv("APP_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("APP_DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("APP_DEEPSEEK_MODEL", "deepseek-chat")


def test_ordering_prompt_has_completion_first_decision():
    from app.config import get_settings
    get_settings.cache_clear()
    from app.llm.deepseek import DeepSeekConversationAgent
    agent = DeepSeekConversationAgent()
    sys = agent._build_system("Testaurant", "ordering",
                              {"menu_text": "1. Lemon mint", "cart_summary": "1x Lemon mint"})
    low = sys.lower()
    # Completion decision is evaluated first, language-agnostic.
    assert "proceed_to_address" in sys
    assert "any language" in low
    # Anti-re-add directive present.
    assert "never re-add" in low or "do not re-add" in low


def test_tool_schema_distinguishes_proceed_from_readd():
    from app.config import get_settings
    get_settings.cache_clear()
    from app.llm.deepseek import _DS_TOOL
    action_desc = _DS_TOOL["function"]["parameters"]["properties"]["action"]["description"].lower()
    assert "frustrat" in action_desc or "declines" in action_desc
    assert "never re-add" in action_desc or "not re-add" in action_desc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/llm/test_deepseek_prompt.py -v`
Expected: FAIL — directives not yet present.

- [ ] **Step 3: Implement the prompt restructure**

In `_ORDERING_BLOCK`, immediately after the `CURRENT CART: {cart_summary}` line (~365) and before the `MENU / BROWSING` section, insert a decision-order block:

```python
DECISION ORDER (check in this order, stop at the first that applies):
STEP 1, COMPLETION: If the CURRENT CART is NOT empty AND the customer is finishing,
  declining more items, or showing impatience/frustration that the order has not moved
  on, in ANY language and ANY phrasing (a bare "no", a curse, "can't you understand",
  a closing word, etc.), return action="proceed_to_address". Do NOT add anything and do
  NOT re-show the menu. NEVER re-add a dish that is already in the cart in response to a
  "no" or a decline. (If the cart IS empty, gently ask what they'd like instead.)
STEP 2: Otherwise handle add / remove / quantity / menu / question as below.

```

In the existing `ADDING` section, strengthen the final line (currently "Only add a dish the customer NAMED in THIS message...") to:

```python
  Only add a dish the customer NAMED in THIS message. NEVER re-add a dish already in the
  cart unless the customer names that dish again or gives a number. A "no"/decline is
  NEVER an add.
```

Leave the existing `FINISHING` section in place (it now reinforces STEP 1).

- [ ] **Step 4: Implement the tool-schema tightening**

In `_DS_TOOL`, in the `action` property `description`, change the `proceed_to_address` and `add_item` lines to:

```python
                        "add_item: customer NAMES a NEW dish to add (or a quantity for "
                        "one). NEVER re-add a dish already in the cart in response to a "
                        "'no'/decline. "
```
```python
                        "proceed_to_address: cart ready — customer is done, declines more "
                        "items, or is frustrated the order has not moved on, in ANY "
                        "language. Move to delivery address capture. "
```

- [ ] **Step 5: Run tests + lint**

Run:
```bash
.venv/bin/pytest tests/llm/test_deepseek_prompt.py -v
.venv/bin/ruff check src/app/llm/deepseek.py
```
Expected: PASS; lint clean.

- [ ] **Step 6: Stage (hold commit)**

```bash
git add src/app/llm/deepseek.py tests/llm/test_deepseek_prompt.py
# DO NOT commit yet.
```

---

### Task 5: Frustration regression + full suite + graph update

**Files:**
- Test: `tests/conversation/test_engine_ordering.py`
- No production code change.

**Interfaces:**
- Consumes: Tasks 1-4 deliverables.
- Produces: a regression test proving a frustration message with trailing words advances and does not inflate; a green full suite.

- [ ] **Step 1: Write the frustration regression test**

```python
async def test_frustration_closing_advances_no_inflation(db_session, restaurant):
    """A frustrated 'thats all can't you understand' with a non-empty cart advances
    to address capture without re-adding (uses the real Fake agent path)."""
    from app.ordering.models import OrderItem

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.fg"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("lemon mint", "wamid.fi"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    order_id = conv.state["draft_order_id"]
    qty_before = sum(it.qty for it in (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all())

    await handle_inbound(db_session, _msg("thats all can't you understand", "wamid.ff"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all()
    assert sum(it.qty for it in items) == qty_before
    assert conv.state["dialogue_state"] == "address_capture"
```

- [ ] **Step 2: Run the new test**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_frustration_closing_advances_no_inflation -v`
Expected: PASS (fake from Task 1 recognizes "thats all").

- [ ] **Step 3: Run the full conversation + llm + ordering suites**

Run:
```bash
.venv/bin/pytest tests/conversation tests/llm tests/ordering -q
```
Expected: all PASS. If any prior test depended on the deleted guard or the old fake closing branch, fix it to assert the new behavior (advance + no inflation), not the old.

- [ ] **Step 4: Lint the whole change**

Run: `.venv/bin/ruff check src apps tests`
Expected: clean.

- [ ] **Step 5: Update the knowledge graph (project CLAUDE.md mandate)**

Run: `/graphify . --update`
Confirm no new AMBIGUOUS edges in the conversation/llm area.

- [ ] **Step 6: Stage everything (hold commit until user authorizes)**

```bash
git add -A
git status   # review staged set
# DO NOT commit. Report to user and wait for explicit authorization.
```

---

## Self-Review

**Spec coverage:**
- Spec §Design 1 (remove guard) → Task 2. ✓
- §Design 2 (decision-order prompt + anti-re-add) → Task 4 Step 3. ✓
- §Design 3 (tool schema) → Task 4 Step 4. ✓
- §Design 4 (re-add backstop) → Task 3 (trigger corrected; flagged). ✓
- §Design 5 (fake parity) → Task 1. ✓
- §Design 6 (tests: curly apostrophe, frustration, no-inflation) → Tasks 2, 3, 5. Multilingual unit tests dropped (flagged refinement 2). ✓
- §Success criteria (advance first try, no inflation, no phrase tables) → Tasks 2-5. ✓

**Placeholder scan:** No TBD/TODO; all steps carry concrete code and commands. ✓

**Type consistency:** `_dish_name_in_text(dish_name, raw_text) -> bool`, `_resolve_cart_dish(session, *, order_id, candidates)`, `find_dish_matches(...).candidates`, `ConversationAgentResult(message, action, action_data)` used consistently across tasks. ✓

**Note on commits:** Every task stages only; commits are withheld per the user's standing "do not commit till I say" instruction. Conventional-commit messages will be authored at authorization time.
