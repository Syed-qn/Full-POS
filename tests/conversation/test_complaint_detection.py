"""Post-delivery complaint detection — AI opens a ticket, never compensates."""
from decimal import Decimal

from sqlalchemy import func, select

from app.conversation.engine import handle_inbound
from app.conversation.service import get_or_create_conversation
from app.coupons.models import Coupon
from app.tickets.models import Ticket
from app.wallet.models import WalletEntry
from app.whatsapp.port import InboundMessage, MessageType


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()


async def _post_order_conv(db_session, restaurant, phone):
    """Create a customer + a post_order conversation for them."""
    from app.ordering.models import Customer, Order
    cust = Customer(restaurant_id=restaurant.id, phone=phone, name="C")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="C-1",
        status="delivered", subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.flush()
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    conv.state = {**(conv.state or {}), "dialogue_phase": "post_order"}
    await db_session.commit()
    return cust, order


def _inb(restaurant, phone, text, wamid):
    return InboundMessage(
        wa_message_id=wamid, from_phone=phone, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone=restaurant.phone, timestamp=1717660900,
    )


async def test_complaint_opens_ticket(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)
    phone = "+971502220001"
    await _post_order_conv(db_session, restaurant, phone)

    await handle_inbound(db_session, _inb(restaurant, phone, "my biryani was cold and stale", "w1"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    tickets = (await db_session.scalars(select(Ticket).where(Ticket.restaurant_id == restaurant.id))).all()
    assert len(tickets) == 1
    assert tickets[0].status == "open"


async def test_complaint_does_not_compensate(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)
    phone = "+971502220002"
    await _post_order_conv(db_session, restaurant, phone)

    await handle_inbound(db_session, _inb(restaurant, phone, "this is disgusting, I want a refund", "w2"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    # The AI must NOT issue any wallet credit or coupon for a complaint.
    wallet_rows = await db_session.scalar(select(func.count(WalletEntry.id)).where(
        WalletEntry.restaurant_id == restaurant.id))
    coupon_rows = await db_session.scalar(select(func.count(Coupon.id)).where(
        Coupon.restaurant_id == restaurant.id))
    assert wallet_rows == 0
    assert coupon_rows == 0


async def test_status_query_not_treated_as_complaint(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)
    phone = "+971502220003"
    await _post_order_conv(db_session, restaurant, phone)

    await handle_inbound(db_session, _inb(restaurant, phone, "where is my order?", "w3"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    tickets = (await db_session.scalars(select(Ticket).where(Ticket.restaurant_id == restaurant.id))).all()
    assert len(tickets) == 0  # status query, not a complaint
