"""Response-accuracy capability eval suite — 19 scenarios (W0).

All xfail evals run end-to-end against the real engine today and FAIL (reproducing
the incident).  As each workstream lands the relevant eval flips to PASS and must be
graduated to the permanent regression suite (it is done when it stays green across all
later workstreams).

Session fixture name: db_session  (see tests/conftest.py).

XPASS note — behaviours already correct with the Fake LLM (converted from xfail):
  test_why_did_you_add_is_not_a_mutation        → no mutation; fake LLM add_item is NO_MATCH
  test_saved_address_question_truthful           → fake LLM gives correct denial
  test_non_english_question_answered_…           → fake LLM doesn't invent an Arabic reply
  test_fee_deterministic_per_address             → grade_total_consistency already passes
  test_order_number_unique_across_two_orders     → sequential PKs are unique
  test_wallet_line_equals_total_math             → subtotal maths out for seeded dishes
  test_caps_insensitive_dish_match               → engine normalises dish query
These 7 tests are kept as NON-XFAIL regression guards at the bottom of this file.
"""
from __future__ import annotations

import pytest

from tests.harness.graders import (
    grade_no_duplicate_dish_line,
    grade_no_mutation,
    grade_total_consistency,
)
from tests.harness.replay import drive_turns

# ─────────────────────────────────────────────────────────────────────────────
# XFAIL capability evals  (10 evals; strict=True)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalogue_basket_double_masala_one_noted_line(
    db_session, restaurant, seed_biryani_menu
):
    """Catalog basket with biryani, then 'Need double masala in biriyani'.
    Engine today adds a duplicate biryani instead of updating the note on the
    existing line."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000030",
        turns=[
            {
                "type": "order",
                "product_items": [
                    {"product_retailer_id": "ju9f8jfy90", "quantity": 1,
                     "item_price": 20, "currency": "AED"},
                ],
            },
            {"type": "text", "text": "Need double masala in biriyani"},
        ],
    )
    final = res.final_cart()
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1, f"expected 1 biryani line, got {biryani}"
    assert biryani[0]["qty"] == 1
    assert biryani[0]["notes"] and "double masala" in biryani[0]["notes"].lower()
    assert grade_no_duplicate_dish_line(res.turns[-1]).passed


@pytest.mark.asyncio
async def test_confirm_time_edit_total_matches(db_session, restaurant, seed_biryani_menu):
    """Customer adds 1 chicken biryani then says 'make it 2 chicken biryani'.
    Engine today creates a second OrderItem instead of updating qty; the
    confirmation total diverges from DB subtotal."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000031",
        turns=[
            {"type": "text", "text": "1 chicken biryani"},
            {"type": "text", "text": "make it 2 chicken biryani"},
        ],
    )
    final = res.final_cart()
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1, f"expected 1 biryani line at qty 2, got {biryani}"
    assert biryani[0]["qty"] == 2, f"expected qty 2, got {biryani[0]['qty']}"
    assert grade_total_consistency(res.turns[-1]).passed


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="W1 voice STT + W3 render: 5-item voice order must land all lines in cart",
)
async def test_voice_order_five_items_all_present(db_session, restaurant, seed_biryani_menu):
    """A voice note naming 5 items.  Without audio_id the harness cannot reach
    FakeTranscriber — the engine replies 'couldn't catch that' and adds nothing;
    the cart stays empty instead of having ≥3 lines."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000032",
        turns=[
            {
                "type": "audio",
                # No audio_id → _download_and_transcribe_voice returns (None,None,None)
                # → engine sends STT-fail reply and returns early.  Cart stays empty.
                "audio_id": None,
                "text": "1 chicken biryani, 1 mutton biryani, 2 mndhi, 1 lemon mint",
            },
        ],
    )
    final = res.final_cart()
    # Fixture has exactly 4 unique product lines (chicken biryani, mutton biryani,
    # mndhi, lemon mint) — assert the exact count, not a weak threshold.
    assert len(final) == 4, f"expected exactly 4 cart lines from voice order, got {final}"


@pytest.mark.asyncio
async def test_modify_flow_remove_decrements(db_session, restaurant, seed_biryani_menu):
    """Add 2 lemon mints then 'remove 1 lemon mint'.  Today the engine either
    duplicates the line or fails to decrement — qty stays 2 or a new line appears."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000033",
        turns=[
            {"type": "text", "text": "2 lemon mint"},
            {"type": "text", "text": "remove 1 lemon mint"},
        ],
    )
    final = res.final_cart()
    lemon = [r for r in final if "lemon" in r["dish_name"].lower()]
    assert len(lemon) == 1, f"expected exactly 1 lemon mint line, got {lemon}"
    assert lemon[0]["qty"] == 1, f"expected qty 1 after remove, got {lemon[0]['qty']}"


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="W8 QuantityPolicy: lakh escalates, not silent huge qty",
)
async def test_lakh_is_not_quantity_one(db_session, restaurant, seed_biryani_menu):
    """'make it 1 lakh' after adding lemon mint.  The engine today silently
    accepts qty 1 (treating 'lakh' as filler) without sending any escalation
    or clarification reply.  W8 must send a clarification message and leave the
    cart unchanged (qty stays 1, but an escalation reply is produced).

    Correct W8 behaviour:
      - cart qty < 1000 (lakh must never be literally parsed as 100 000)
      - last outbound reply contains escalation/clarification language

    Current bug: engine sends a non-escalation reply (or none at all), so the
    escalation_markers assertion fails → correct xfail today.
    """
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000034",
        turns=[
            {"type": "text", "text": "one lemon mint"},
            {"type": "text", "text": "make it 1 lakh"},
        ],
    )
    lemon = [r for r in res.final_cart() if "lemon" in r["dish_name"].lower()]
    assert lemon, "lemon mint must still be in cart after escalation"
    # W8: lakh must never be parsed as a literal large number.
    assert lemon[0]["qty"] < 1000, (
        f"lakh parsed as a large literal qty: {lemon[0]['qty']}"
    )
    # W8: escalation/clarification reply must be sent — NOT a generic off-menu decline.
    # Current bug: engine interprets "make it 1 lakh" as a dish lookup, gets NO_MATCH,
    # and sends "Sorry, we don't have make it 1 lakh on our menu..." — which is
    # semantically wrong (this is a quantity mutation, not a dish search).
    # W8 QuantityPolicy will detect "lakh" before calling add_item and will instead
    # send a quantity-specific clarification like "How many lemon mints did you want?"
    # or "1 lakh isn't a valid quantity — please clarify".
    # Assertions that FAIL today (off-menu decline contains none of these) and will
    # PASS once W8 sends a genuine quantity-escalation reply:
    last_reply = (
        res.turns[-1].outbounds[-1].body if res.turns[-1].outbounds else ""
    ).lower()
    # W8 must NOT send the generic "don't have X on our menu" off-menu response —
    # the engine should know this is a qty intent, not a dish search.
    assert "don't have" not in last_reply and "on our menu" not in last_reply, (
        f"engine sent an off-menu-decline instead of a quantity escalation: {last_reply!r}"
    )
    # W8 must send a reply that references the quantity problem
    # (e.g. "how many", "quantity", "valid", "lakh is not").
    quantity_markers = ("how many", "quantity", "valid", "invalid", "lakh is not")
    assert any(m in last_reply for m in quantity_markers), (
        f"engine must send a quantity-escalation reply for 'lakh'; "
        f"got: {last_reply!r}"
    )


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="W8 reactions: UNKNOWN/reaction message must produce no outbound reply",
)
async def test_reaction_no_reply_no_mutation(db_session, restaurant, seed_biryani_menu):
    """A 'reaction' arrives as UNKNOWN type.  Today the engine falls through to
    the AI path which tries to add '[unknown]' as a dish and sends an error reply.
    Both the outbound reply and any cart mutation are bugs (F83)."""
    # Establish a cart first.
    res1 = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000035",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )
    cart_after_order = res1.turns[0].cart_rows

    # Replay an UNKNOWN-type message (any type not in the driver map defaults to UNKNOWN).
    res2 = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000035",
        turns=[{"type": "unknown_reaction", "text": ""}],
    )
    assert len(res2.turns[0].outbounds) == 0, (
        f"reaction produced unexpected outbound(s): {res2.turns[0].outbounds}"
    )
    assert grade_no_mutation(cart_after_order, res2.turns[0]).passed, (
        grade_no_mutation(cart_after_order, res2.turns[0]).reason
    )


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="W6/W8 catalog: misspelled catalog keyword must still route to send_catalog",
)
async def test_multilingual_catalog_request_sends_catalog(
    db_session, restaurant, seed_biryani_menu
):
    """'catlog' (common typo) is NOT in _MENU_KEYWORDS today, so it falls through
    to the AI path rather than calling send_catalog.  The engine must send a
    product-list (catalog cards) even for known misspellings/variants."""
    from app.outbox.models import OutboxMessage
    from sqlalchemy import select

    await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000036",
        turns=[{"type": "text", "text": "catlog"}],
    )
    # The engine must route to send_catalog → OutboxMessage with type product_list.
    outbox = (
        await db_session.scalars(
            select(OutboxMessage).order_by(OutboxMessage.id.desc()).limit(5)
        )
    ).all()
    product_list_msgs = [m for m in outbox if m.type == "product_list"]
    assert product_list_msgs, (
        f"'catlog' typo did not trigger send_catalog; outbox: {[(m.type, m.payload) for m in outbox]}"
    )


@pytest.mark.asyncio
async def test_pls_not_a_note(db_session, restaurant, seed_biryani_menu):
    """'pls add extra masala' after ordering biryani.  The engine today either
    stores 'pls' as part of the note, or treats the phrase as a new dish lookup
    and fails to attach the note at all."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000037",
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "pls add extra masala"},
        ],
    )
    final = res.final_cart()
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1, f"expected 1 biryani line, got {biryani}"
    note = (biryani[0].get("notes") or "").lower()
    assert note and not note.startswith("pls"), (
        f"note incorrectly starts with 'pls': {note!r}"
    )
    assert "masala" in note, f"note missing 'masala': {note!r}"


@pytest.mark.asyncio
async def test_clear_cart_only_on_explicit_clear(db_session, restaurant, seed_biryani_menu):
    """Cart has biryani + lemon mint. 'only 1 biryani' means set biryani qty to 1;
    the lemon mint must survive.  Today the engine adds a duplicate biryani or
    silently clears the lemon mint."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000038",
        turns=[
            {"type": "text", "text": "2 chicken biryani"},
            {"type": "text", "text": "1 lemon mint"},
            {"type": "text", "text": "only 1 chicken biryani"},
        ],
    )
    final = res.final_cart()
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    lemon = [r for r in final if "lemon" in r["dish_name"].lower()]
    assert len(lemon) == 1, f"lemon mint lost after 'only 1 biryani': cart={final}"
    assert len(biryani) == 1, f"expected 1 biryani line, got {biryani}"
    assert biryani[0]["qty"] == 1, f"expected qty 1, got {biryani[0]['qty']}"


@pytest.mark.asyncio
async def test_idempotent_redelivery_same_wa_message_id(
    db_session, restaurant, seed_biryani_menu
):
    """The engine layer has no deduplication gate (that lives in the webhook router).
    A duplicate delivery of the same order text currently adds the item a second time,
    creating a duplicate OrderItem line (F94/F115)."""
    # First delivery.
    await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000039",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )
    # Duplicate delivery — same phone, same text, different call.
    res2 = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000039",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )
    biryani = [r for r in res2.turns[0].cart_rows if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1, (
        f"duplicate delivery added a second biryani line: {biryani}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# W1 acceptance evals — new regression guards added by Task 8.
# These exercise W1 capabilities end-to-end through the real engine.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_qty_missing_total_no_mutation(db_session, restaurant, seed_biryani_menu):
    """A set-qty intent without a quantity must not change the cart and must ask a
    clarification (R-069).

    Flow: customer orders 2 chicken biryani, then says "change the biryani" with no
    number.  FakeConversationAgent emits cart_set_qty(dish_query="biryani", no new_total).
    to_engine_result detects the missing required field (new_total) and returns
    no_action{needs_clarification:True}.  The engine clarification gate (W1, engine.py)
    sends a clarification reply WITHOUT touching the cart.

    Driven via FakeConversationAgent → to_engine_result → real engine → real DB.
    """
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000051",
        turns=[
            {"type": "text", "text": "2 chicken biryani"},
            {"type": "text", "text": "change the biryani"},  # no number → clarification
        ],
    )
    final = res.final_cart()
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1 and biryani[0]["qty"] == 2, (
        f"cart must be unchanged after missing-qty edit, got {final}"
    )
    last = (res.turns[-1].outbounds[-1].body if res.turns[-1].outbounds else "").lower()
    assert any(m in last for m in ("quantity", "how many", "didn't", "catch", "exact")), (
        f"engine must send a clarification reply when qty is missing; got: {last!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Regression tests — behaviours already correct with the Fake LLM today.
# Converted from xfail because they XPASS (behaviour already correct).
# ─────────────────────────────────────────────────────────────────────────────


# NOTE: Fake-scoped guard. Passes because FakeConversationAgent does not reproduce this LLM-interpretation bug. Real coverage requires the live-LLM eval harness (deferred). Does NOT prove the production LLM path is correct.
@pytest.mark.asyncio
async def test_why_did_you_add_is_not_a_mutation(db_session, restaurant, seed_biryani_menu):
    """'Why did you add 2 biriyani' must not mutate the cart.
    CONVERTED FROM XFAIL: fake LLM returns add_item("why did you add 2 biriyani")
    which resolves to NO_MATCH → cart unchanged → grade_no_mutation passes today."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000040",
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "why did you add 2 biriyani"},
        ],
    )
    assert grade_no_mutation(res.turns[0].cart_rows, res.turns[1]).passed, (
        grade_no_mutation(res.turns[0].cart_rows, res.turns[1]).reason
    )


@pytest.mark.asyncio
async def test_that_is_all_once_proceeds(db_session, restaurant, seed_biryani_menu):
    """After adding an item, 'That's all' must advance dialogue out of ordering.
    CONVERTED FROM XFAIL: fake LLM correctly handles closing tokens → proceeds."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000041",
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "That's all"},
        ],
    )
    assert res.turns[-1].phase != "ordering", (
        f"engine still in ordering after 'That's all': {res.turns[-1].phase}"
    )


# NOTE: Fake-scoped guard. Passes because FakeConversationAgent does not reproduce this LLM-interpretation bug. Real coverage requires the live-LLM eval harness (deferred). Does NOT prove the production LLM path is correct.
@pytest.mark.asyncio
async def test_saved_address_question_truthful(db_session, restaurant, seed_biryani_menu):
    """'Do you have my saved address?' with no address in DB — bot must deny.
    CONVERTED FROM XFAIL: fake LLM does not invent an address; truthful_markers pass."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000042",
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "do you have my saved address?"},
        ],
    )
    body = (res.turns[1].outbounds[-1].body if res.turns[1].outbounds else "").lower()
    invented = ("building", "villa", "street", "road", "tower", "flat", "apartment")
    assert not any(m in body for m in invented), (
        f"bot appears to have invented an address: {body!r}"
    )


# NOTE: Fake-scoped guard. Passes because FakeConversationAgent does not reproduce this LLM-interpretation bug. Real coverage requires the live-LLM eval harness (deferred). Does NOT prove the production LLM path is correct.
@pytest.mark.asyncio
async def test_non_english_question_no_invented_english_dish(
    db_session, restaurant, seed_biryani_menu
):
    """Arabic question 'ما هو أفضل طبق؟' must not dump an invented English dish list.
    CONVERTED FROM XFAIL: fake LLM tries add_item with the Arabic query → NO_MATCH
    → no invented dish is added to the cart."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000043",
        turns=[{"type": "text", "text": "ما هو أفضل طبق؟"}],
    )
    final = res.final_cart()
    invented = [r for r in final if r["dish_name"].lower() not in
                {"chicken biryani", "mutton biryani", "lemon mint", "mndhi - 2"}]
    assert not invented, f"invented dish in cart from Arabic query: {invented}"


@pytest.mark.asyncio
async def test_fee_total_consistency_regression(db_session, restaurant, seed_biryani_menu):
    """grade_total_consistency must pass for a basic cart (total ≥ subtotal).
    CONVERTED FROM XFAIL: totals are internally consistent for seeded dishes."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000044",
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "done"},
        ],
    )
    for turn in res.turns:
        result = grade_total_consistency(turn)
        assert result.passed, f"total inconsistency: {result.reason}"


@pytest.mark.asyncio
async def test_order_number_unique_across_two_orders(db_session, restaurant, seed_biryani_menu):
    """Two separate carts must get different order numbers.
    CONVERTED FROM XFAIL: sequential PKs guarantee uniqueness today."""
    from app.ordering.models import Order

    res1 = await drive_turns(
        db_session, restaurant_id=restaurant.id, phone="+971500000045",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )
    res2 = await drive_turns(
        db_session, restaurant_id=restaurant.id, phone="+971500000046",
        turns=[{"type": "text", "text": "one mutton biryani"}],
    )
    oid1 = res1.turns[0].state.get("draft_order_id")
    oid2 = res2.turns[0].state.get("draft_order_id")
    assert oid1 and oid2 and oid1 != oid2
    o1 = await db_session.get(Order, oid1)
    o2 = await db_session.get(Order, oid2)
    assert o1 and o2
    assert o1.order_number != o2.order_number, (
        f"order numbers must be unique; both got {o1.order_number}"
    )


@pytest.mark.asyncio
async def test_wallet_subtotal_math_regression(db_session, restaurant, seed_biryani_menu):
    """Subtotal must equal sum of line prices for a basic two-item cart.
    CONVERTED FROM XFAIL: arithmetic is correct for seeded AED prices."""
    from decimal import Decimal

    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000047",
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "one lemon mint"},
        ],
    )
    last = res.turns[-1]
    assert last.subtotal is not None, "subtotal must be computed after two items"
    assert last.subtotal == Decimal("32.00"), (
        f"subtotal {last.subtotal} != AED 32 (20+12); cart: {last.cart_rows}"
    )


@pytest.mark.asyncio
async def test_caps_insensitive_dish_match(db_session, restaurant, seed_biryani_menu):
    """'CHICKEN BIRYANI' (all-caps) must resolve to the seeded dish.
    CONVERTED FROM XFAIL: engine normalises query before pg_trgm lookup."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000048",
        turns=[{"type": "text", "text": "CHICKEN BIRYANI"}],
    )
    final = res.final_cart()
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    assert biryani, f"CAPS dish name not matched: cart is {final}"


@pytest.mark.asyncio
async def test_english_menu_request_updates_dialogue_state(
    db_session, restaurant, seed_biryani_menu
):
    """'menu' keyword must trigger send_catalog and enqueue a product_list.

    After I-2 driver fix: the harness now mirrors production routing — a TEXT message
    whose normalised text is in _CATALOG_KEYWORDS and whose restaurant has catalog mode
    on is routed directly to send_catalog (bypassing handle_inbound), exactly as
    webhook/router.py does.  In this path, dialogue_state is NOT written to
    'menu_sent'; instead we assert that an OutboxMessage of type product_list was
    enqueued (the production-faithful signal that the menu was sent)."""
    from app.outbox.models import OutboxMessage
    from sqlalchemy import select

    await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000049",
        turns=[{"type": "text", "text": "menu"}],
    )
    outbox = (
        await db_session.scalars(
            select(OutboxMessage).order_by(OutboxMessage.id.desc()).limit(5)
        )
    ).all()
    # OutboxMessage stores the type inside payload["type"] (not a top-level column).
    product_list_msgs = [m for m in outbox if m.payload.get("type") == "product_list"]
    assert product_list_msgs, (
        f"'menu' keyword did not trigger send_catalog product_list; "
        f"outbox: {[(m.payload.get('type'), m.payload) for m in outbox]}"
    )


@pytest.mark.asyncio
async def test_no_hallucination_in_menu_state(db_session, restaurant, seed_biryani_menu):
    """'show me the full menu' must not produce invented dish names.
    CONVERTED FROM XFAIL: with catalog mode the engine routes to send_catalog (no LLM);
    engine sets dialogue_state='menu_sent' without LLM fabrication.
    Note: send_catalog outbounds are in OutboxMessage, not Message table — check state."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000050",
        turns=[{"type": "text", "text": "show me the full menu"}],
    )
    assert res.turns[0].state.get("dialogue_state") == "menu_sent", (
        f"expected menu_sent state, got {res.turns[0].state}"
    )
    # Also assert the cart stays empty (no LLM added phantom dishes).
    assert res.turns[0].cart_rows == [], (
        f"menu request must not add phantom dishes: {res.turns[0].cart_rows}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# W7 capability evals (xfail-strict until W7a/W7b land)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_basket_visible_in_history(db_session, restaurant, seed_biryani_menu):
    """After a catalogue basket, _build_history must show the resolved dish names
    for that turn (e.g. 'Chicken Biryani'), not the opaque placeholder '[order]'
    (R-029/R-077/F63/DB-H8).
    GRADUATED (W7a Task 7): _build_history now renders the ORDER turn from the
    cart_snapshot/display_text persisted at record time (Task 3 + Task 4)."""
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
async def test_structured_cart_drives_correction(db_session, restaurant, seed_biryani_menu):
    """The interpreter receives context['cart_state'] (a structured array) and is
    told the DB cart wins over history prose. A correction sets the existing line's
    qty rather than appending a duplicate (R-072/R-074/R-060).
    CONVERTED FROM XFAIL (W7a Task 2): already passes on this branch — the
    catalogue basket + text correction path already sets qty=1 correctly."""
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
