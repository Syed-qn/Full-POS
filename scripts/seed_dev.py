"""Seed a dev restaurant with an active menu for local simulator testing.

Idempotent: re-running updates the existing restaurant's menu rather than
duplicating. Run from repo root with the venv:

    .venv/Scripts/python.exe scripts/seed_dev.py

Then open http://localhost:8000/simulator/ and chat to the restaurant phone
printed at the end.
"""

import asyncio
import os
from decimal import Decimal

os.environ.setdefault("APP_LLM_PROVIDER", "fake")

from sqlalchemy import select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.identity.auth import hash_password  # noqa: E402
from app.identity.models import Restaurant, Rider  # noqa: E402
from app.menu.models import Dish, Menu  # noqa: E402
from app.ordering.matching import normalize_name  # noqa: E402

RESTAURANT_PHONE = "+971565594402"
RESTAURANT_NAME = "Spice Garden (Dev)"
RIDER_PHONE = "+971501111111"
# Dubai (Business Bay) coords — within UAE service area.
LAT, LNG = 25.1877, 55.2633

# (dish_number, name, price_aed, category)
DISHES = [
    (1, "Chicken Biryani", "28.00", "Biryani"),
    (2, "Mutton Biryani", "35.00", "Biryani"),
    (3, "Veg Biryani", "22.00", "Biryani"),
    (4, "Butter Chicken", "32.00", "Curries"),
    (5, "Paneer Tikka Masala", "26.00", "Curries"),
    (6, "Garlic Naan", "6.00", "Breads"),
    (7, "Mango Lassi", "12.00", "Drinks"),
]


async def main() -> None:
    async with async_session_factory() as session:
        restaurant = await session.scalar(
            select(Restaurant).where(Restaurant.phone == RESTAURANT_PHONE)
        )
        if restaurant is None:
            restaurant = Restaurant(
                name=RESTAURANT_NAME,
                phone=RESTAURANT_PHONE,
                password_hash=hash_password("password123"),
                lat=LAT,
                lng=LNG,
            )
            session.add(restaurant)
            await session.flush()
            print(f"created restaurant id={restaurant.id} phone={RESTAURANT_PHONE}")
        else:
            print(f"restaurant already exists id={restaurant.id}; refreshing menu")

        # Non-destructive: keep an existing active menu (its dishes may be
        # referenced by past orders, so deleting would FK-violate). Only build
        # a fresh menu when none is active.
        menu = await session.scalar(
            select(Menu).where(
                Menu.restaurant_id == restaurant.id, Menu.status == "active"
            )
        )
        if menu is None:
            menu = Menu(restaurant_id=restaurant.id, version=1, status="active")
            session.add(menu)
            await session.flush()
            for number, name, price, category in DISHES:
                session.add(
                    Dish(
                        menu_id=menu.id,
                        restaurant_id=restaurant.id,
                        dish_number=number,
                        name=name,
                        price_aed=Decimal(price),
                        category=category,
                        is_available=True,
                        name_normalized=normalize_name(name),
                    )
                )
        else:
            print(f"active menu id={menu.id} already present; leaving as-is")

        # Seed a rider (phone matches the rider simulator's default field).
        rider = await session.scalar(
            select(Rider).where(
                Rider.restaurant_id == restaurant.id, Rider.phone == RIDER_PHONE
            )
        )
        if rider is None:
            rider = Rider(
                restaurant_id=restaurant.id,
                name="Dev Rider",
                phone=RIDER_PHONE,
                status="available",
            )
            session.add(rider)

        await session.commit()
        print(f"active menu id={menu.id}")
        print(f"rider phone={RIDER_PHONE} (status=available)")
        print("\nSeed complete.")
        print("Customer simulator: http://localhost:8000/simulator/")
        print(f"  Restaurant phone: {RESTAURANT_PHONE}")
        print("  Your phone:       any number, e.g. +918220958384")
        print("Rider simulator:    http://localhost:8000/simulator/rider")
        print(f"  Rider phone:      {RIDER_PHONE}")
        print(f"  Restaurant phone: {RESTAURANT_PHONE}  (change the default field to this)")


if __name__ == "__main__":
    asyncio.run(main())
