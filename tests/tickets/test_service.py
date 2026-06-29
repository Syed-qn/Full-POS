from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.outbox.models import OutboxMessage
from app.tickets import service as t
from app.tickets.service import TicketError
from app.wallet import service as w


async def test_create_ticket_open(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    tk = await t.create_ticket(
        db_session, restaurant_id=rid, customer_id=cid, order_id=None,
        source_message="biryani was cold",
    )
    assert tk.status == "open"
    assert tk.resolution_action == "none"


async def test_list_open_first(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    a = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid, order_id=None, source_message="a")
    b = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid, order_id=None, source_message="b")
    await t.resolve_no_action(db_session, restaurant_id=rid, ticket_id=a.id, note="ok", created_by="mgr:1")
    rows = await t.list_tickets(db_session, restaurant_id=rid)
    assert rows[0][0].id == b.id  # (ticket, phone, name) tuples; open before resolved


async def test_get_ticket_cross_tenant(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    tk = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid, order_id=None, source_message="x")
    with pytest.raises(TicketError):
        await t.get_ticket(db_session, restaurant_id=rid + 999, ticket_id=tk.id)


async def test_resolve_wallet_refund_credits_and_notifies(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    tk = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid, order_id=None, source_message="cold")
    await t.resolve_wallet_refund(
        db_session, restaurant_id=rid, ticket_id=tk.id, amount=Decimal("20.00"),
        note="cold food goodwill", created_by="mgr:1",
    )
    assert tk.status == "resolved"
    assert tk.resolution_action == "wallet_refund"
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("20.00")
    n = await db_session.scalar(select(func.count(OutboxMessage.id)).where(OutboxMessage.restaurant_id == rid))
    assert n == 1


async def test_refund_idempotent_no_double_credit(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    tk = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid, order_id=None, source_message="cold")
    await t.resolve_wallet_refund(db_session, restaurant_id=rid, ticket_id=tk.id,
                                  amount=Decimal("20.00"), note="x", created_by="mgr:1")
    # Re-resolve returns the already-resolved ticket, no extra credit.
    await t.resolve_wallet_refund(db_session, restaurant_id=rid, ticket_id=tk.id,
                                  amount=Decimal("20.00"), note="x", created_by="mgr:1")
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("20.00")


async def test_no_action_requires_note(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    tk = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid, order_id=None, source_message="x")
    with pytest.raises(TicketError):
        await t.resolve_no_action(db_session, restaurant_id=rid, ticket_id=tk.id, note="  ", created_by="mgr:1")


async def test_replacement_sets_link(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    tk = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid, order_id=None, source_message="x")
    await t.resolve_replacement(db_session, restaurant_id=rid, ticket_id=tk.id,
                                replacement_order_id=555, note="remaking", created_by="mgr:1")
    assert tk.resolution_action == "replacement"
    assert tk.replacement_order_id == 555
