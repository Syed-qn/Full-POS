"""End-to-end wallet-spend safety: confirm holds credit, rider collects only the
remainder, delivery captures — never double-charging the customer."""
from decimal import Decimal

from app.identity.models import Restaurant
from app.ordering import service as ordering
from app.ordering.models import Customer, Order, OrderItem
from app.ordering.payments import cod_due_aed
from app.wallet import service as wallet


async def _seed(db_session):
    r = Restaurant(name="Spend R", phone="+97140000020", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500000020", name="Spend C")
    db_session.add(c)
    await db_session.flush()
    return r, c


async def _confirmable_order(db_session, r, c):
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=r.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=1, name="Biryani",
                price_aed=Decimal("60.00"), category="Rice", is_available=True,
                name_normalized="biryani")
    db_session.add(dish)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="S-1",
              status="pending_confirmation", subtotal=Decimal("60.00"),
              total=Decimal("60.00"), delivery_fee_aed=Decimal("0.00"))
    db_session.add(o)
    await db_session.flush()
    db_session.add(OrderItem(order_id=o.id, dish_id=dish.id, dish_number=1,
                             dish_name="Biryani", qty=1, price_aed=Decimal("60.00")))
    await db_session.flush()
    return o


async def test_confirm_holds_wallet_and_cod_due_reduced(db_session):
    r, c = await _seed(db_session)
    await wallet.credit(db_session, restaurant_id=r.id, customer_id=c.id,
                        amount=Decimal("20.00"), idempotency_key="seed", created_by="mgr:1")
    o = await _confirmable_order(db_session, r, c)
    await ordering.finalize_confirmation(db_session, order=o, actor="customer")
    assert o.wallet_applied_aed == Decimal("20.00")
    # COD the rider collects = 60 - 20 = 40.
    assert cod_due_aed(o) == Decimal("40.00")
    # Credit only HELD until delivery — balance intact, available zero.
    acc = await wallet.get_or_create_account(db_session, restaurant_id=r.id, customer_id=c.id)
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("20.00")
    assert await wallet.available(db_session, account_id=acc.id) == Decimal("0.00")


async def test_no_credit_confirm_unchanged(db_session):
    r, c = await _seed(db_session)
    o = await _confirmable_order(db_session, r, c)
    await ordering.finalize_confirmation(db_session, order=o, actor="customer")
    assert o.wallet_applied_aed == Decimal("0.00")
    assert cod_due_aed(o) == Decimal("60.00")  # full COD, no wallet


async def test_rider_collects_only_remainder_and_capture_settles(db_session, monkeypatch):
    r, c = await _seed(db_session)
    await wallet.credit(db_session, restaurant_id=r.id, customer_id=c.id,
                        amount=Decimal("20.00"), idempotency_key="seed", created_by="mgr:1")
    o = await _confirmable_order(db_session, r, c)
    await ordering.finalize_confirmation(db_session, order=o, actor="customer")
    # Simulate the rider stop COD shown.
    assert cod_due_aed(o) == Decimal("40.00")
    # Drive to delivered (capture settles the hold).
    o.status = "arriving"
    await db_session.flush()
    from app.dispatch.delivery import advance_delivery
    await advance_delivery(db_session, order_id=o.id, to_status="delivered")
    acc = await wallet.get_or_create_account(db_session, restaurant_id=r.id, customer_id=c.id)
    # Wallet portion consumed; cash portion (40) collected separately = no double charge.
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("0.00")
