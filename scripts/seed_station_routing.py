"""Map menu categories to KDS stations so items route to the right place.

Without rows in category_station_defaults, kds.service.resolve_station() falls
all the way through to the Main station — meaning drinks, desserts and fried
items all print at the hot kitchen. This seeds a sane default mapping.

Resolution order in the app is: dish.station_id -> CategoryStationDefault ->
Main. So a single dish can still override its category here.

Run: APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/restaurant \
     PYTHONPATH=src ./.venv/Scripts/python.exe scripts/seed_station_routing.py [restaurant_id]

Idempotent: re-running updates existing mappings rather than duplicating them.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

import app.kds.models  # noqa: F401
from app.db import get_session
from app.identity.models import Restaurant
from app.kds.models import CategoryStationDefault, KitchenStation

# category -> station_type
CATEGORY_STATION: dict[str, str] = {
    # Drinks never touch the hot line.
    "Soft Drinks": "beverage",
    "Fresh Juice": "beverage",
    "Crush Milkshake": "beverage",
    "Tea & Coffee": "beverage",
    # Sweets have their own pass.
    "Dessert Corner": "dessert",
    # Fryer items.
    "Popcorn": "fry",
    # Hot line / grill.
    "Burger Sandwich": "grill",
    "Club Sandwich": "grill",
    "Wrap Sandwich": "grill",
    "Combo Sandwich": "grill",
    "Paratha Spot": "grill",
    # Cold prep stays on main.
    "Healthy Salad": "main",
}


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target_id = int(args[0]) if args else 4

    async for session in get_session():
        restaurant = await session.get(Restaurant, target_id)
        if restaurant is None:
            print(f"Restaurant #{target_id} not found.")
            return

        stations = list(
            (
                await session.scalars(
                    select(KitchenStation)
                    .where(KitchenStation.restaurant_id == restaurant.id)
                    .order_by(KitchenStation.id)
                )
            ).all()
        )
        if not stations:
            print("No kitchen stations for this restaurant — nothing to map.")
            return

        # This restaurant has duplicate preset rows; always bind to the lowest id
        # of each type so routing is deterministic.
        by_type: dict[str, KitchenStation] = {}
        for st in stations:
            by_type.setdefault(st.station_type, st)

        dupes = len(stations) - len(by_type)
        if dupes:
            print(f"  ! {dupes} duplicate station rows present — binding to lowest id per type")

        created = 0
        updated = 0
        for category, station_type in CATEGORY_STATION.items():
            station = by_type.get(station_type) or by_type.get("main")
            if station is None:
                print(f"  - {category}: no '{station_type}' station, skipped")
                continue
            row = await session.scalar(
                select(CategoryStationDefault).where(
                    CategoryStationDefault.restaurant_id == restaurant.id,
                    CategoryStationDefault.category == category,
                )
            )
            if row is None:
                session.add(
                    CategoryStationDefault(
                        restaurant_id=restaurant.id,
                        category=category,
                        station_id=station.id,
                    )
                )
                created += 1
            else:
                row.station_id = station.id
                updated += 1
            print(f"  {category:<18} -> {station.name} (#{station.id})")

        await session.commit()
        print(f"Mapped {created} new, {updated} updated.")
        return


if __name__ == "__main__":
    asyncio.run(main())
