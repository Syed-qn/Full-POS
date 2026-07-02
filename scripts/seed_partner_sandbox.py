#!/usr/bin/env python3
"""Seed a partner integration sandbox for local POS testing.

Creates (idempotent):
  * Restaurant ``Partner Sandbox`` with partner settings enabled
  * One API key (printed once)
  * Sample POS-linked menu items
  * Optional webhook receiver URL (use with test_phase0_webhook_live.py)

Run from repo root:
  .venv/Scripts/python scripts/seed_partner_sandbox.py

Then call partner APIs with the printed ``X-API-Key`` header.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal

os.environ.setdefault("APP_LLM_PROVIDER", "fake")

from sqlalchemy import select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.identity.auth import hash_password  # noqa: E402
from app.identity.models import Restaurant  # noqa: E402
from app.menu.models import Dish, Menu  # noqa: E402
from app.partner.integration import apply_partner_settings  # noqa: E402
from app.partner.keys import generate_api_key  # noqa: E402
from app.partner.models import PartnerApiKey  # noqa: E402

PHONE = "+971509990001"
NAME = "Partner Sandbox"
WEBHOOK_URL = os.environ.get(
    "PARTNER_SANDBOX_WEBHOOK_URL", "http://127.0.0.1:8765/hooks/whatsapp"
)
WEBHOOK_SECRET = os.environ.get("PARTNER_SANDBOX_WEBHOOK_SECRET", "sandbox-secret")
POS_STORE_ID = "CRT-SBX-001"

MENU = [
    ("POS-101", 101, "Chicken Biryani", "45.00", "Main"),
    ("POS-102", 102, "Grill Mandi", "100.00", "Main"),
    ("POS-103", 103, "Lemon Mint", "20.00", "Drinks"),
]


async def main() -> None:
    async with async_session_factory() as session:
        restaurant = await session.scalar(
            select(Restaurant).where(Restaurant.phone == PHONE)
        )
        if restaurant is None:
            restaurant = Restaurant(
                name=NAME,
                phone=PHONE,
                password_hash=hash_password("sandbox123"),
                lat=25.2048,
                lng=55.2708,
                settings={"dispatch_engine": "greedy"},
            )
            session.add(restaurant)
            await session.flush()
            print(f"Created restaurant id={restaurant.id} phone={PHONE}")
        else:
            print(f"Restaurant exists id={restaurant.id}; refreshing sandbox config")

        apply_partner_settings(
            restaurant,
            {
                "partner_enabled": True,
                "partner_webhook_url": WEBHOOK_URL,
                "partner_webhook_secret": WEBHOOK_SECRET,
                "pos_store_id": POS_STORE_ID,
                "pos_order_push_mode": "webhook",
            },
        )

        menu = await session.scalar(
            select(Menu).where(
                Menu.restaurant_id == restaurant.id, Menu.status == "active"
            )
        )
        if menu is None:
            menu = Menu(
                restaurant_id=restaurant.id, version=1, status="active", source_files=[]
            )
            session.add(menu)
            await session.flush()

        for pos_id, num, name, price, category in MENU:
            dish = await session.scalar(
                select(Dish).where(
                    Dish.restaurant_id == restaurant.id,
                    Dish.pos_product_id == pos_id,
                )
            )
            if dish is None:
                dish = Dish(
                    menu_id=menu.id,
                    restaurant_id=restaurant.id,
                    pos_product_id=pos_id,
                    dish_number=num,
                    name=name,
                    price_aed=Decimal(price),
                    category=category,
                    is_available=True,
                )
                session.add(dish)
            else:
                dish.name = name
                dish.price_aed = Decimal(price)
                dish.is_available = True

        existing_key = await session.scalar(
            select(PartnerApiKey).where(
                PartnerApiKey.restaurant_id == restaurant.id,
                PartnerApiKey.label == "Sandbox POS",
                PartnerApiKey.revoked_at.is_(None),
            )
        )
        api_key: str | None = None
        if existing_key is None:
            full_key, prefix, key_hash = generate_api_key()
            session.add(
                PartnerApiKey(
                    restaurant_id=restaurant.id,
                    label="Sandbox POS",
                    key_prefix=prefix,
                    key_hash=key_hash,
                )
            )
            api_key = full_key
        else:
            print(f"API key already exists prefix={existing_key.key_prefix} (revoke & re-run to mint new)")

        await session.commit()

    print("\n--- Partner sandbox ready ---")
    print(f"Restaurant phone : {PHONE}")
    print(f"Manager password : sandbox123")
    print(f"POS store id     : {POS_STORE_ID}")
    print(f"Webhook URL      : {WEBHOOK_URL}")
    if api_key:
        print(f"API key (ONCE)   : {api_key}")
    print("\nTest: GET /api/v1/partner/store with header X-API-Key")
    print("Docs: docs/partners/openapi-partner-v1.yaml")


if __name__ == "__main__":
    asyncio.run(main())