"""Phase 3: menu sync IN from POS."""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.menu.models import Dish
from app.partner.menu_api import upsert_partner_menu_items, PartnerMenuItemInput

pytestmark = pytest.mark.asyncio


async def _api_key(client, auth_headers) -> str:
    return (
        await client.post(
            "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
        )
    ).json()["api_key"]


@pytest.mark.asyncio
async def test_bulk_upsert_creates_pos_dishes(client, auth_headers, db_session):
    key = await _api_key(client, auth_headers)

    with (
        patch("app.pos.images.generate_dish_image", return_value=b"png"),
        patch("app.menu.service.store_dish_image", new_callable=AsyncMock, return_value="/media/x.png"),
        patch("app.partner.menu_api._publish_menu_mirror", new_callable=AsyncMock),
    ):
        resp = await client.put(
            "/api/v1/partner/menu/items",
            headers={"X-API-Key": key},
            json={
                "items": [
                    {
                        "pos_id": "POS-101",
                        "dish_number": 101,
                        "name": "Grill Mandi",
                        "price": 40.0,
                        "category": "Main",
                        "is_available": True,
                    },
                    {
                        "pos_id": "POS-102",
                        "name": "Avocado Salad",
                        "price": 25.0,
                        "category": "Salad",
                    },
                ]
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 2
    assert body["updated"] == 0

    dishes = (
        await db_session.scalars(
            select(Dish).where(Dish.pos_product_id.in_(["POS-101", "POS-102"]))
        )
    ).all()
    assert len(dishes) == 2


@pytest.mark.asyncio
async def test_bulk_upsert_updates_existing(client, auth_headers, db_session):
    from app.identity.models import Restaurant

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()

    with patch("app.partner.menu_api._publish_menu_mirror", new_callable=AsyncMock):
        await upsert_partner_menu_items(
            db_session,
            restaurant_id=rest.id,
            items=[
                PartnerMenuItemInput(
                    pos_id="POS-200",
                    dish_number=200,
                    name="Soup",
                    price_aed=Decimal("10.00"),
                )
            ],
            publish=False,
        )
        await db_session.commit()

    key = await _api_key(client, auth_headers)
    with patch("app.partner.menu_api._publish_menu_mirror", new_callable=AsyncMock):
        resp = await client.put(
            "/api/v1/partner/menu/items",
            headers={"X-API-Key": key},
            json={
                "items": [
                    {
                        "pos_id": "POS-200",
                        "dish_number": 200,
                        "name": "Soup Updated",
                        "price": 12.0,
                    }
                ]
            },
        )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1
    dish = await db_session.scalar(select(Dish).where(Dish.pos_product_id == "POS-200"))
    assert dish.name == "Soup Updated"
    assert dish.price_aed == Decimal("12.00")


@pytest.mark.asyncio
async def test_patch_availability(client, auth_headers, db_session):
    from app.identity.models import Restaurant

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    with patch("app.partner.menu_api._publish_menu_mirror", new_callable=AsyncMock):
        await upsert_partner_menu_items(
            db_session,
            restaurant_id=rest.id,
            items=[
                PartnerMenuItemInput(
                    pos_id="POS-300",
                    dish_number=300,
                    name="Juice",
                    price_aed=Decimal("15.00"),
                    is_available=True,
                )
            ],
            publish=False,
        )
        await db_session.commit()

    key = await _api_key(client, auth_headers)
    with patch("app.partner.menu_api._publish_menu_mirror", new_callable=AsyncMock):
        resp = await client.patch(
            "/api/v1/partner/menu/items/POS-300",
            headers={"X-API-Key": key},
            json={"is_available": False},
        )
    assert resp.status_code == 200
    assert resp.json()["is_available"] is False


@pytest.mark.asyncio
async def test_menu_sync_status(client, auth_headers, db_session):
    key = await _api_key(client, auth_headers)
    resp = await client.get(
        "/api/v1/partner/menu/sync-status",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200
    assert "pos_dish_count" in resp.json()


@pytest.mark.asyncio
async def test_menu_changed_queues_pull(client, auth_headers):
    key = await _api_key(client, auth_headers)
    with (
        patch("app.pos.worker.sync_pos_menu_task") as mock_task,
        patch("app.config.get_settings") as mock_settings,
    ):
        mock_task.apply_async = lambda **kwargs: None
        mock_settings.return_value.outbox_sync_delivery = False
        resp = await client.post(
            "/api/v1/partner/events/menu-changed",
            headers={"X-API-Key": key},
            json={},
        )
    assert resp.status_code == 200
    assert resp.json()["queued"] is True