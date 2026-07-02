import pytest

from app.conversation.engine import _build_history
from app.conversation.models import Conversation
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
async def test_order_turn_falls_back_to_product_items_count(db_session, restaurant):
    """Older rows without a display_text/cart_snapshot still render human text,
    never the opaque '[order]' placeholder."""
    conv = await _conv(db_session, restaurant)
    await record_message(
        db_session, conversation_id=conv.id, direction="inbound",
        wa_message_id="o2", msg_type="order",
        payload={"product_items": [{"product_retailer_id": "x", "quantity": 1},
                                    {"product_retailer_id": "y", "quantity": 1}]},
        ts=10,
    )
    await db_session.flush()
    hist = await _build_history(db_session, conv)
    assert hist and "[order]" not in hist[0]["content"]
    assert "2" in hist[0]["content"]


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
async def test_window_is_configurable(db_session, restaurant):
    conv = await _conv(db_session, restaurant)
    for i in range(8):
        await record_message(db_session, conversation_id=conv.id,
            direction="inbound" if i % 2 == 0 else "outbound",
            wa_message_id=f"w{i}", msg_type="text", payload={"text": f"m{i}"}, ts=100 + i)
    await db_session.flush()
    hist_default = await _build_history(db_session, conv)        # default (settings) → all 8
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
async def test_dead_fetch_builder_absent():
    """_fetch_conversation_history was already deleted in W1 (b9ae270); guard
    against its reintroduction (F67/F69/R-083)."""
    import app.conversation.engine as engine
    assert not hasattr(engine, "_fetch_conversation_history")
