"""A refused catalogue card must not leave the customer with nothing.

Prod (La Cafe, 7 Aug 2026): the WABA was attached to a catalog we had no access to,
so every product id we sent was a stranger to it and Meta answered

    131009 | Parameter value is not valid | Products not found in FB Catalog

The customer said "hi", got the greeting, and then silence — the card was the only
thing carrying the menu. Retrying is pointless (same ids, same catalog), so the row
is marked dead and a plain-text menu goes out in its place.
"""
from unittest.mock import patch

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one
from app.whatsapp.port import OutboundMessageType


def _factory(db_session):
    return async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


def _products_not_found() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://graph.facebook.com/v21.0/1/messages")
    response = httpx.Response(
        400,
        json={"error": {
            "code": 131009,
            "message": "(#131009) Parameter value is not valid",
            "error_data": {"details": "Products not found in FB Catalog"},
        }},
        request=request,
    )
    return httpx.HTTPStatusError("131009", request=request, response=response)


class _Refuses:
    async def send(self, msg, *, phone_number_id=None, access_token=None):
        raise _products_not_found()


async def _seed(db_session, restaurant_id, *, msg_type: str, key: str) -> OutboxMessage:
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone="+971509999601",
        payload={"type": msg_type, "body": "menu", "thumbnail_product_retailer_id": "dish-1-1"},
        idempotency_key=key,
        status="pending",
        attempts=0,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def test_catalog_message_refusal_queues_the_text_menu(db_session, restaurant):
    row = await _seed(
        db_session, restaurant.id, msg_type="catalog_message", key="mismatch-card"
    )

    called: list[tuple[int, str]] = []

    async def _fake(session, *, restaurant_id, to_phone):
        called.append((restaurant_id, to_phone))
        return True

    with patch("app.catalog.service.send_text_menu_after_catalog_failure", _fake):
        await _deliver_one(row.id, provider=_Refuses(), session_factory=_factory(db_session))

    await db_session.refresh(row)
    assert row.status == "dead", "retrying the same ids against the same catalog is futile"
    assert row.payload.get("fail_reason") == "catalog_mismatch"
    assert "Products not found in FB Catalog" in (row.last_error or "")
    assert called == [(restaurant.id, "+971509999601")]


async def test_product_list_refusal_also_falls_back(db_session, restaurant):
    row = await _seed(
        db_session, restaurant.id, msg_type="product_list", key="mismatch-list"
    )
    called: list[str] = []

    async def _fake(session, *, restaurant_id, to_phone):
        called.append(to_phone)
        return True

    with patch("app.catalog.service.send_text_menu_after_catalog_failure", _fake):
        await _deliver_one(row.id, provider=_Refuses(), session_factory=_factory(db_session))

    assert called == ["+971509999601"]


async def test_plain_text_failure_does_not_trigger_a_menu(db_session, restaurant):
    """Only catalogue sends get rescued — a failed text must not spawn a menu."""
    row = await _seed(db_session, restaurant.id, msg_type=str(OutboundMessageType.TEXT),
                      key="mismatch-text")
    called: list[str] = []

    async def _fake(session, *, restaurant_id, to_phone):
        called.append(to_phone)
        return True

    with patch("app.catalog.service.send_text_menu_after_catalog_failure", _fake):
        await _deliver_one(row.id, provider=_Refuses(), session_factory=_factory(db_session))

    assert called == []


async def test_fallback_failure_does_not_break_the_dead_marking(db_session, restaurant):
    """If the rescue itself raises, the original row must still be marked dead."""
    row = await _seed(
        db_session, restaurant.id, msg_type="catalog_message", key="mismatch-raises"
    )

    async def _boom(session, *, restaurant_id, to_phone):
        raise RuntimeError("mirror unavailable")

    with patch("app.catalog.service.send_text_menu_after_catalog_failure", _boom):
        await _deliver_one(row.id, provider=_Refuses(), session_factory=_factory(db_session))

    await db_session.refresh(row)
    assert row.status == "dead"
