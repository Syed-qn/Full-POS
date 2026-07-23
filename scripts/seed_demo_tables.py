"""Seed a realistic dining-room floor so the waiter Floor screen has live data.

Positions are FLOAT GRID COORDINATES, not pixels: the waiter floor canvas
multiplies them by its grid unit (76px). Tables are spread across the room in
two seating bands so the layout reads like a real dining room.

Every table is seeded FREE. No fake reserved/cleaning/occupied states: table
status is meant to reflect reality, and "occupied" is derived by the tables
router from a real open order anyway (guests = order.covers), so a table only
turns amber once someone actually opens a tab on it.

Run: APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/restaurant \
     PYTHONPATH=src ./.venv/Scripts/python.exe scripts/seed_demo_tables.py [restaurant_id]

Existing tables are reused (relabelled + repositioned) instead of deleted —
orders hold a table_id FK, so deleting a table that ever took an order fails.
Re-running this script is idempotent and safe.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

import app.kds.models  # noqa: F401  (register cross-module FK tables)
from app.db import get_session
from app.identity.models import Restaurant
from app.tables.models import DiningTable

# label, seats, pos_x, pos_y, status
TABLES: list[tuple[str, int, float, float, str]] = [
    # ── upper band ────────────────────────────────────────────────────────
    ("T01", 4, 1.2, 0.5, "available"),
    ("T02", 4, 4.3, 0.5, "available"),
    ("T03", 6, 7.4, 0.5, "available"),
    ("T04", 4, 11.6, 0.5, "available"),
    ("T05", 4, 14.8, 0.5, "available"),
    # ── middle band ───────────────────────────────────────────────────────
    ("T06", 10, 1.5, 3.2, "available"),
    ("T16", 4, 6.4, 3.2, "available"),
    ("T17", 6, 9.6, 3.2, "available"),
    ("T18", 4, 13.2, 3.2, "available"),
    ("T19", 2, 16.0, 3.2, "available"),
    ("T07", 4, 1.2, 5.6, "available"),
    ("T08", 4, 4.3, 5.6, "available"),
    ("T09", 8, 7.4, 5.4, "available"),
    ("T10", 4, 11.6, 5.6, "available"),
    ("T11", 4, 14.8, 5.6, "available"),
    # ── lower band ────────────────────────────────────────────────────────
    ("T12", 10, 1.5, 8.8, "available"),
    ("T13", 6, 6.4, 8.8, "available"),
    ("T14", 6, 10.4, 8.8, "available"),
    ("T15", 2, 14.9, 8.8, "available"),
    ("T20", 4, 16.8, 8.8, "available"),
    # ── window row ────────────────────────────────────────────────────────
    ("T21", 2, 1.2, 11.2, "available"),
    ("T22", 4, 4.3, 11.2, "available"),
    ("T23", 6, 7.8, 11.2, "available"),
    ("T24", 4, 11.6, 11.2, "available"),
    ("T25", 2, 14.9, 11.2, "available"),
]


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target_id = int(args[0]) if args else 4

    async for session in get_session():
        restaurant = await session.get(Restaurant, target_id)
        if restaurant is None:
            print(f"Restaurant #{target_id} not found.")
            return
        print(f"Seeding floor for restaurant #{restaurant.id} ({restaurant.name})")

        existing = list(
            (
                await session.scalars(
                    select(DiningTable)
                    .where(DiningTable.restaurant_id == restaurant.id)
                    .order_by(DiningTable.id)
                )
            ).all()
        )

        # Existing rows are REUSED (relabelled + repositioned) rather than deleted:
        # orders carry a table_id FK, so dropping a table that ever held an order
        # fails. Re-running this script is therefore always safe.
        by_label = {row.label: row for row in existing}
        spare = [row for row in existing if row.label not in {t[0] for t in TABLES}]

        created = 0
        moved = 0
        reused = 0
        for label, seats, x, y, status in TABLES:
            row = by_label.get(label)
            if row is None and spare:
                row = spare.pop(0)
                print(f"  ~ reusing '{row.label}' (id={row.id}) as {label}")
                row.label = label
                reused += 1
            if row is None:
                session.add(
                    DiningTable(
                        restaurant_id=restaurant.id,
                        label=label,
                        seats=seats,
                        pos_x=x,
                        pos_y=y,
                        status=status,
                    )
                )
                created += 1
                continue
            # The layout in this file is authoritative — re-running repositions.
            row.seats = seats
            row.pos_x = x
            row.pos_y = y
            row.status = status
            moved += 1

        await session.commit()
        print(f"Created {created}, repositioned {moved} (of which {reused} relabelled).")
        return


if __name__ == "__main__":
    asyncio.run(main())
