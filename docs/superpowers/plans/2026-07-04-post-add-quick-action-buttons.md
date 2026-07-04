# Post-Add Quick-Action Buttons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every add-to-cart confirmation (including WhatsApp catalogue basket) sends three quick-action buttons — Proceed to delivery, upsell dish or Suggestions, Clear cart — with a 3-tier grounded upsell resolver (history → menu special → top seller).

**Architecture:** Extend existing `_post_add_extras()` in `engine.py` with `_upsell_dish_for_cart()` priority chain. Wire `catalog/service.py` basket success path to `_send_buttons` + `_post_add_extras`. Add deterministic `_handle_top_sellers()` for `suggest_dishes` button taps (no LLM). Reuse existing BUTTON_REPLY handlers.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy 2, pytest-asyncio, WhatsApp interactive buttons (max 3, title ≤ 20 chars).

**Spec:** `docs/superpowers/specs/2026-07-04-post-add-quick-action-buttons-design.md`

---

## File structure

```
src/app/conversation/engine.py     # _menu_special_dish, _top_seller_dish, _upsell_dish_for_cart,
                                   # _handle_top_sellers; refactor _history_upsell_dish;
                                   # update _post_add_extras, suggest_dishes handler
src/app/catalog/service.py         # handle_catalog_order: _send_buttons + _post_add_extras
tests/conversation/test_engine_ordering.py   # upsell tier tests, top sellers tap test
tests/catalog/test_catalog_order.py          # update basket test + new buttons test
understanding.txt                  # log entry after each task commit
```

---

### Task 1: Menu-special detection helper

**Files:**
- Modify: `src/app/conversation/engine.py` (near `_history_upsell_dish`, ~L4760)
- Test: `tests/conversation/test_engine_ordering.py`

- [ ] **Step 1: Write the failing test**

Add after existing upsell tests (~L1923):

```python
async def test_menu_special_dish_picked_for_upsell(db_session, restaurant):
    """Dish in a 'Chef Specials' category is upsell when customer has no history."""
    from app.conversation.engine import _upsell_dish_for_cart
    from app.conversation.service import get_or_create_conversation
    from app.menu.models import Dish, Menu
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    soup = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=10,
        name="Chicken Soup", price_aed=Decimal("15.00"), category="Soup",
        is_available=True, name_normalized="chicken soup",
    )
    special = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=20,
        name="Chef Special Mandi", price_aed=Decimal("45.00"), category="Chef Specials",
        is_available=True, name_normalized="chef special mandi",
    )
    db_session.add_all([soup, special])
    await db_session.flush()

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971501110301",
        counterpart="customer",
    )
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110301"
    )
    draft = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=draft, dish=soup, qty=1)
    await db_session.commit()

    dish, source = await _upsell_dish_for_cart(
        db_session, conv, restaurant.id, draft
    )
    assert dish is not None
    assert dish.id == special.id
    assert source == "menu_special"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_menu_special_dish_picked_for_upsell -v
```

Expected: FAIL — `ImportError: cannot import name '_upsell_dish_for_cart'`

- [ ] **Step 3: Implement menu-special helpers**

In `engine.py`, above `_history_upsell_dish`, add:

```python
_MENU_SPECIAL_PHRASES: tuple[str, ...] = (
    "chef special", "chef's special", "restaurant special", "house special",
    "today's special", "todays special",
)


def _text_signals_menu_special(*, category: str | None, name: str, description: str | None) -> bool:
    cat = (category or "").lower()
    if "special" in cat or "specials" in cat:
        return True
    blob = f"{name} {description or ''}".lower()
    return any(p in blob for p in _MENU_SPECIAL_PHRASES)


async def _menu_special_dish(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order,
):
    """First available dish flagged as a menu special, not already in cart."""
    from app.menu.models import Dish, Menu

    if conv.state.get("upsell_shown_for") == order.id:
        return None
    in_cart = {
        did for (did,) in (
            await session.execute(
                select(OrderItem.dish_id).where(OrderItem.order_id == order.id)
            )
        ).all()
    }
    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
    if menu is None:
        return None
    dishes = (
        await session.scalars(
            select(Dish).where(
                Dish.menu_id == menu.id,
                Dish.is_available == True,  # noqa: E712
                Dish.meta_status == "active",
            ).order_by(Dish.category, Dish.name)
        )
    ).all()
    for dish in dishes:
        if dish.id in in_cart:
            continue
        if not getattr(dish, "whatsapp_enabled", True):
            continue
        if _SLUG_NAME.match(dish.name or ""):
            continue
        if not _text_signals_menu_special(
            category=dish.category, name=dish.name, description=dish.description
        ):
            continue
        if await _catalog_excludes_dish(session, restaurant_id, dish):
            continue
        _set_state(conv, upsell_shown_for=order.id)
        return dish
    return None
```

Add stub returning `(None, "none")`:

```python
async def _upsell_dish_for_cart(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order,
) -> tuple[object | None, str]:
    dish = await _menu_special_dish(session, conv, restaurant_id, order)
    if dish is not None:
        return dish, "menu_special"
    return None, "none"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_menu_special_dish_picked_for_upsell -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_ordering.py
git commit -m "feat: detect menu-special dishes for cart upsell"
```

---

### Task 2: Top-seller resolver + unified upsell chain

**Files:**
- Modify: `src/app/conversation/engine.py`
- Test: `tests/conversation/test_engine_ordering.py`

- [ ] **Step 1: Write failing tests**

```python
async def test_top_seller_picked_when_no_history_or_special(db_session, restaurant):
    from app.conversation.engine import _upsell_dish_for_cart
    from app.conversation.service import get_or_create_conversation
    from app.menu.models import Dish, Menu
    from app.ordering.models import Order, OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    soup = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=10,
        name="Chicken Soup", price_aed=Decimal("15.00"), category="Soup",
        is_available=True, name_normalized="chicken soup",
    )
    mandi = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=30,
        name="Mandi", price_aed=Decimal("45.00"), category="Rice",
        is_available=True, name_normalized="mandi",
    )
    db_session.add_all([soup, mandi])
    await db_session.flush()

    cust_a = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110401"
    )
    past = Order(
        restaurant_id=restaurant.id, customer_id=cust_a.id, order_number="R1-9001",
        status="delivered", priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("45.00"), total=Decimal("45.00"),
    )
    db_session.add(past)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=past.id, dish_id=mandi.id, dish_number=30, dish_name="Mandi",
        qty=5, price_aed=Decimal("45.00"),
    ))

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971501110402",
        counterpart="customer",
    )
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110402"
    )
    draft = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=draft, dish=soup, qty=1)
    await db_session.commit()

    dish, source = await _upsell_dish_for_cart(
        db_session, conv, restaurant.id, draft
    )
    assert dish is not None
    assert dish.id == mandi.id
    assert source == "top_seller"


async def test_history_still_wins_over_special_and_volume(db_session, restaurant):
    """Personal history remains tier-1."""
    from app.conversation.engine import _upsell_dish_for_cart

    conv, customer, draft, lemon_mint = await _seed_history_customer(
        db_session, restaurant, "+971501110403"
    )
    dish, source = await _upsell_dish_for_cart(
        db_session, conv, restaurant.id, draft
    )
    assert dish is not None
    assert dish.id == lemon_mint.id
    assert source == "history"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_top_seller_picked_when_no_history_or_special tests/conversation/test_engine_ordering.py::test_history_still_wins_over_special_and_volume -v
```

Expected: FAIL on top_seller (`source == 'none'`)

- [ ] **Step 3: Implement `_top_seller_dish` and wire `_upsell_dish_for_cart`**

```python
_UPSELL_VOLUME_DAYS = 30


async def _top_seller_dish(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order, *, limit: int = 10,
):
    from datetime import datetime, timedelta, timezone
    from app.menu.models import Dish
    from app.ordering.models import Order, OrderItem

    if conv.state.get("upsell_shown_for") == order.id:
        return None
    in_cart = {
        did for (did,) in (
            await session.execute(
                select(OrderItem.dish_id).where(OrderItem.order_id == order.id)
            )
        ).all()
    }
    since = datetime.now(timezone.utc) - timedelta(days=_UPSELL_VOLUME_DAYS)
    rows = (
        await session.execute(
            select(OrderItem.dish_id, func.sum(OrderItem.qty).label("units"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.status.notin_(("draft", "cancelled")),
                Order.created_at >= since,
                OrderItem.dish_id.isnot(None),
            )
            .group_by(OrderItem.dish_id)
            .order_by(func.sum(OrderItem.qty).desc())
            .limit(limit)
        )
    ).all()
    for dish_id, _units in rows:
        if dish_id in in_cart:
            continue
        dish = await session.get(Dish, dish_id)
        if dish is None or not dish.is_available:
            continue
        if not getattr(dish, "whatsapp_enabled", True):
            continue
        if _SLUG_NAME.match(dish.name or ""):
            continue
        if await _catalog_excludes_dish(session, restaurant_id, dish):
            continue
        _set_state(conv, upsell_shown_for=order.id)
        return dish
    return None
```

Refactor `_history_upsell_dish` body into tier-1 only (remove duplicate `upsell_shown_for` check from inner — centralize in `_upsell_dish_for_cart`):

```python
async def _upsell_dish_for_cart(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order,
) -> tuple[object | None, str]:
    if conv.state.get("upsell_shown_for") == order.id:
        return None, "none"
    try:
        dish = await _history_upsell_dish(session, conv, restaurant_id, order)
        if dish is not None:
            return dish, "history"
        dish = await _menu_special_dish(session, conv, restaurant_id, order)
        if dish is not None:
            return dish, "menu_special"
        dish = await _top_seller_dish(session, conv, restaurant_id, order)
        if dish is not None:
            return dish, "top_seller"
    except Exception:  # noqa: BLE001
        _logger.debug("upsell resolver failed", exc_info=True)
    return None, "none"
```

Update `_history_upsell_dish` to NOT set `upsell_shown_for` itself — `_upsell_dish_for_cart` sets it when returning a dish. Remove the early `upsell_shown_for` guard from `_history_upsell_dish` (keep in `_menu_special_dish` / `_top_seller_dish` as no-ops or remove duplicates).

Update `_post_add_extras`:

```python
async def _post_add_extras(...) -> tuple[str, list[dict]]:
    upsell_line = ""
    dish, source = await _upsell_dish_for_cart(session, conv, restaurant_id, order)
    if dish is not None:
        if source == "history":
            upsell_line = (
                f"\n\nYou had {dish.name} (AED {_aed(dish.price_aed)}) last time. "
                "Add one? 😊"
            )
        else:
            upsell_line = (
                f"\n\nTry {dish.name} (AED {_aed(dish.price_aed)})? Add one? 😊"
            )
        title = f"Add {dish.name}"
        if len(title) > 20:
            title = title[:20]
        upsell_btn = {"id": f"upsell_add:{dish.id}", "title": title}
    else:
        upsell_btn = {"id": "suggest_dishes", "title": "Suggestions"}
    buttons = [
        {"id": "proceed_delivery", "title": "Proceed to delivery"},
        upsell_btn,
        {"id": "clear_cart", "title": "Clear cart"},
    ]
    return upsell_line, buttons
```

Update `_history_upsell_line` to call `_upsell_dish_for_cart` and only emit line when `source == "history"`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/conversation/test_engine_ordering.py -k "upsell or top_seller or history_upsell or add_confirmation" -v
```

Expected: all PASS (update `test_history_upsell_no_history_is_silent` if it now gets top_seller from other tests' data — isolate with fresh restaurant or no volume orders)

- [ ] **Step 5: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_ordering.py
git commit -m "feat: unified upsell resolver with history, menu special, top seller"
```

---

### Task 3: Deterministic top-sellers handler (`suggest_dishes` button)

**Files:**
- Modify: `src/app/conversation/engine.py` (~L968 `_handle_suggestions`, BUTTON_REPLY ~L8810)
- Test: `tests/conversation/test_engine_ordering.py`

- [ ] **Step 1: Write failing test**

```python
async def test_suggest_dishes_button_shows_top_sellers_not_llm(db_session, restaurant, monkeypatch):
    from app.conversation.engine import handle_inbound
    from app.llm.factory import get_suggestion_agent
    from app.outbox.models import OutboxMessage

    def _boom():
        raise AssertionError("LLM suggestion agent must not run for suggest_dishes button")

    monkeypatch.setattr("app.llm.factory.get_suggestion_agent", _boom)

    phone = "+971501110501"
    conv, customer, draft, lemon_mint = await _seed_history_customer(
        db_session, restaurant, phone
    )
    # Clear upsell_shown so Suggestions path is open; tap suggest_dishes directly.
    conv.state = {**conv.state, "upsell_shown_for": None}
    await db_session.commit()

    await handle_inbound(
        db_session, _btn_msg("suggest_dishes", phone, "wamid.sug1"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    bodies = [
        m.payload.get("body", "")
        for m in (await db_session.scalars(select(OutboxMessage))).all()
    ]
    assert any("bestseller" in b.lower() for b in bodies), bodies
    assert not any("having a moment" in b.lower() for b in bodies)
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_suggest_dishes_button_shows_top_sellers_not_llm -v
```

Expected: FAIL — AssertionError LLM called, or no "bestseller" in body

- [ ] **Step 3: Add `_handle_top_sellers` and route button**

```python
async def _handle_top_sellers(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Deterministic bestseller list for the Suggestions quick-action button."""
    from app.menu.models import Dish

    order_id = conv.state.get("draft_order_id") or conv.state.get("pending_order_id")
    order = await session.get(Order, order_id) if order_id else None
    in_cart: set[int] = set()
    if order is not None:
        in_cart = {
            did for (did,) in (
                await session.execute(
                    select(OrderItem.dish_id).where(OrderItem.order_id == order.id)
                )
            ).all()
        }
    picks: list[Dish] = []
    dish = await _top_seller_dish(session, conv, restaurant_id, order or Order(), limit=10)
    # _top_seller_dish sets upsell_shown_for — use a volume-only query for list:
    since = datetime.now(timezone.utc) - timedelta(days=_UPSELL_VOLUME_DAYS)
    rows = (
        await session.execute(
            select(OrderItem.dish_id, func.sum(OrderItem.qty).label("units"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.status.notin_(("draft", "cancelled")),
                Order.created_at >= since,
                OrderItem.dish_id.isnot(None),
            )
            .group_by(OrderItem.dish_id)
            .order_by(func.sum(OrderItem.qty).desc())
            .limit(10)
        )
    ).all()
    for dish_id, _ in rows:
        if dish_id in in_cart:
            continue
        d = await session.get(Dish, dish_id)
        if d is None or not d.is_available:
            continue
        if not getattr(d, "whatsapp_enabled", True):
            continue
        if await _catalog_excludes_dish(session, restaurant_id, d):
            continue
        picks.append(d)
        if len(picks) >= 3:
            break

    if not picks:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="top-sellers-none",
            body="Tell us what you're in the mood for 😊",
        )
        await _send_menu_or_catalog(
            session, conv, inbound, restaurant_id, prefix="top-sellers-menu",
        )
        return

    lines = ["Here are our bestsellers 😊"]
    for d in picks:
        lines.append(f"• {d.name} — AED {_aed(d.price_aed)}")
    lines.append("\nTell me what you'd like and I'll add it 😊")
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="top-sellers",
        body="\n".join(lines),
    )
```

**Refactor note:** Extract shared `_top_seller_candidates(session, restaurant_id, *, limit)` used by both `_top_seller_dish` and `_handle_top_sellers` to avoid duplication (implement in Step 3).

In BUTTON_REPLY block, change:

```python
if btn_id == "suggest_dishes":
    await _handle_top_sellers(session, conv, inbound, restaurant_id)
    return
```

Change stale upsell fallback (~L8807):

```python
await _handle_top_sellers(session, conv, inbound, restaurant_id)
```

Leave text-triggered `_is_suggestion_browse_intent` → `_handle_suggestions` (LLM path) unchanged.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_suggest_dishes_button_shows_top_sellers_not_llm -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_ordering.py
git commit -m "feat: deterministic top-sellers for Suggestions button"
```

---

### Task 4: Catalogue basket quick-action buttons

**Files:**
- Modify: `src/app/catalog/service.py` (~L706)
- Modify: `tests/catalog/test_catalog_order.py`

- [ ] **Step 1: Write failing test**

In `tests/catalog/test_catalog_order.py`, add:

```python
async def test_catalog_basket_carries_quick_action_buttons(db_session, restaurant):
    await _seed_catalog_menu(db_session, restaurant.id)
    inbound = _order_inbound([
        {"product_retailer_id": "nwb4pa5fbn", "quantity": "1",
         "item_price": "20", "currency": "AED"},
    ])
    await handle_catalog_order(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    msg = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).one()
    buttons = msg.payload.get("buttons") or []
    assert buttons, "catalog basket must send quick-action buttons"
    ids = {b["id"] for b in buttons}
    assert "proceed_delivery" in ids
    assert "clear_cart" in ids
    assert any(i.startswith("upsell_add:") or i == "suggest_dishes" for i in ids)
    assert "done" not in msg.payload.get("body", "").lower()
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
.venv/bin/pytest tests/catalog/test_catalog_order.py::test_catalog_basket_carries_quick_action_buttons -v
```

Expected: FAIL — `buttons` empty / assertion on buttons

- [ ] **Step 3: Wire catalogue handler**

In `catalog/service.py`, replace import:

```python
from app.conversation.engine import (
    _build_cart_summary, _post_add_extras, _send_buttons, _set_state,
)
```

Replace success-path `_send_text` block:

```python
    upsell_line, buttons = await _post_add_extras(
        session, conv, restaurant_id, order
    )
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="catalog-cart",
        body=f"Got your basket 🎉\n\n🛒 {cart}{extra}{upsell_line}",
        buttons=buttons,
    )
```

- [ ] **Step 4: Update existing catalog test**

In `test_catalog_cart_creates_order_and_confirms`, replace:

```python
assert "done" in body.lower()
```

with:

```python
assert msg.payload.get("buttons")
assert "proceed_delivery" in {b["id"] for b in msg.payload["buttons"]}
```

- [ ] **Step 5: Run catalog + conversation tests**

```bash
.venv/bin/pytest tests/catalog/test_catalog_order.py tests/conversation/test_engine_ordering.py -k "upsell or top_seller or catalog or add_confirmation or suggest_dishes" -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/catalog/service.py tests/catalog/test_catalog_order.py
git commit -m "feat: catalogue basket sends post-add quick-action buttons"
```

---

### Task 5: Regression sweep + understanding.txt

**Files:**
- Modify: `understanding.txt`

- [ ] **Step 1: Full regression**

```bash
.venv/bin/pytest tests/catalog tests/conversation/test_engine_ordering.py -v
.venv/bin/ruff check src/app/conversation/engine.py src/app/catalog/service.py
```

Expected: PASS, 0 ruff errors in touched files

- [ ] **Step 2: Log to understanding.txt**

Append bullet with date/time covering: catalogue basket buttons, 3-tier upsell, deterministic Suggestions, tests added.

- [ ] **Step 3: Mark spec plan complete**

Update spec status if needed; final commit:

```bash
git add understanding.txt docs/superpowers/plans/2026-07-04-post-add-quick-action-buttons.md
git commit -m "docs: post-add quick-action buttons plan complete"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Catalogue basket buttons | Task 4 |
| 3-tier upsell priority | Task 2 |
| Menu special from menu text | Task 1 |
| Top seller 30-day volume | Task 2 |
| Suggestions = deterministic bestsellers | Task 3 |
| Existing typed/AI paths use new resolver | Task 2 (`_post_add_extras`) |
| WhatsApp 3-button / 20-char limits | Task 2 (`_post_add_extras`) |
| Error handling (resolver try/except) | Task 2 |
| Cart edit paths out of scope | — |

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-post-add-quick-action-buttons.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — implement tasks in this session with checkpoints

Which approach do you want?