from decimal import Decimal


from app.coupons import service as coupons
from app.dispatch.delivery import advance_delivery
from app.identity.models import Restaurant
from app.ordering import payments
from app.ordering import service as ordering
from app.ordering.models import Customer, Order
from app.wallet import service as wallet


async def _seed(db_session):
    r = Restaurant(name="Pay R", phone="+97140000010", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500000010", name="Pay C")
    db_session.add(c)
    await db_session.flush()
    return r, c


async def _order(db_session, r, c, total="60.00", subtotal="60.00"):
    o = Order(
        restaurant_id=r.id, customer_id=c.id, order_number="P-1", status="confirmed",
        subtotal=Decimal(subtotal), total=Decimal(total), delivery_fee_aed=Decimal("0.00"),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_wallet_applied_reduces_cod_due(db_session):
    r, c = await _seed(db_session)
    await wallet.credit(db_session, restaurant_id=r.id, customer_id=c.id,
                        amount=Decimal("20.00"), idempotency_key="seed", created_by="mgr:1")
    o = await _order(db_session, r, c)
    summary = await payments.apply_at_confirm(db_session, order=o, use_wallet=True)
    assert summary["wallet_applied_aed"] == Decimal("20.00")
    assert summary["cod_due_aed"] == Decimal("40.00")
    # Balance unchanged until delivery (held only).
    acc = await wallet.get_or_create_account(db_session, restaurant_id=r.id, customer_id=c.id)
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("20.00")
    assert await wallet.available(db_session, account_id=acc.id) == Decimal("0.00")


async def test_capture_on_deliver_drops_balance(db_session):
    r, c = await _seed(db_session)
    await wallet.credit(db_session, restaurant_id=r.id, customer_id=c.id,
                        amount=Decimal("20.00"), idempotency_key="seed", created_by="mgr:1")
    o = await _order(db_session, r, c)
    await payments.apply_at_confirm(db_session, order=o, use_wallet=True)
    # Move through delivery FSM to delivered.
    o.status = "arriving"
    await db_session.flush()
    await advance_delivery(db_session, order_id=o.id, to_status="delivered")
    acc = await wallet.get_or_create_account(db_session, restaurant_id=r.id, customer_id=c.id)
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("0.00")


async def test_release_on_cancel_restores_credit(db_session):
    r, c = await _seed(db_session)
    await wallet.credit(db_session, restaurant_id=r.id, customer_id=c.id,
                        amount=Decimal("20.00"), idempotency_key="seed", created_by="mgr:1")
    o = await _order(db_session, r, c)
    await payments.apply_at_confirm(db_session, order=o, use_wallet=True)
    await ordering.cancel_order(db_session, order=o, actor="customer", reason="changed mind")
    acc = await wallet.get_or_create_account(db_session, restaurant_id=r.id, customer_id=c.id)
    assert await wallet.available(db_session, account_id=acc.id) == Decimal("20.00")
    assert o.wallet_applied_aed == Decimal("0.00")


async def test_coupon_then_wallet_stack(db_session):
    r, c = await _seed(db_session)
    await wallet.credit(db_session, restaurant_id=r.id, customer_id=c.id,
                        amount=Decimal("100.00"), idempotency_key="seed", created_by="mgr:1")
    cp = await coupons.create_coupon(db_session, restaurant_id=r.id, discount_type="fixed",
                                     discount_value=Decimal("10.00"), created_by="mgr:1")
    o = await _order(db_session, r, c)
    summary = await payments.apply_at_confirm(db_session, order=o, coupon_code=cp.code, use_wallet=True)
    assert summary["coupon_discount_aed"] == Decimal("10.00")
    assert o.total == Decimal("50.00")  # 60 - 10 coupon
    assert summary["wallet_applied_aed"] == Decimal("50.00")  # wallet covers the rest
    assert summary["cod_due_aed"] == Decimal("0.00")


async def test_no_wallet_no_coupon_is_noop(db_session):
    r, c = await _seed(db_session)
    o = await _order(db_session, r, c)
    summary = await payments.apply_at_confirm(db_session, order=o)
    assert summary["wallet_applied_aed"] == Decimal("0.00")
    assert summary["cod_due_aed"] == Decimal("60.00")
    assert o.total == Decimal("60.00")


async def test_wallet_hold_never_exceeds_available(db_session):
    r, c = await _seed(db_session)
    await wallet.credit(db_session, restaurant_id=r.id, customer_id=c.id,
                        amount=Decimal("5.00"), idempotency_key="seed", created_by="mgr:1")
    o = await _order(db_session, r, c)
    summary = await payments.apply_at_confirm(db_session, order=o, use_wallet=True)
    assert summary["wallet_applied_aed"] == Decimal("5.00")
    assert summary["cod_due_aed"] == Decimal("55.00")
