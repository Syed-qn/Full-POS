"""Delete restaurants (and ALL their tenant data) by id.

DESTRUCTIVE. Disables FK triggers for the session, deletes child rows keyed by
the deleted orders/customers, then every row with restaurant_id in the target
set, then the restaurants themselves.

Run: APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/restaurant \
     PYTHONPATH=src ./.venv/Scripts/python.exe scripts/delete_restaurants.py 1 2 3
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.db import get_session


async def main(ids: list[int]) -> None:
    id_list = ",".join(str(i) for i in ids)
    async for s in get_session():
        # Column maps
        def cols_with(col: str) -> list[str]:
            return col  # placeholder; replaced below

        rid_tabs = [
            r[0]
            for r in (
                await s.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE column_name='restaurant_id' AND table_schema='public'"
                    )
                )
            ).all()
        ]
        order_child = [
            r[0]
            for r in (
                await s.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE column_name='order_id' AND table_schema='public'"
                    )
                )
            ).all()
        ]
        customer_child = [
            r[0]
            for r in (
                await s.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE column_name='customer_id' AND table_schema='public'"
                    )
                )
            ).all()
        ]

        # Ids of the parents we're about to remove (before deletion).
        order_ids = [
            r[0]
            for r in (
                await s.execute(
                    text(f"SELECT id FROM orders WHERE restaurant_id IN ({id_list})")
                )
            ).all()
        ]
        customer_ids = [
            r[0]
            for r in (
                await s.execute(
                    text(f"SELECT id FROM customers WHERE restaurant_id IN ({id_list})")
                )
            ).all()
        ]

        await s.execute(text("SET session_replication_role = replica"))
        deleted = 0

        def csv(vals: list[int]) -> str:
            return ",".join(str(v) for v in vals)

        if order_ids:
            oids = csv(order_ids)
            for t in order_child:
                res = await s.execute(text(f'DELETE FROM "{t}" WHERE order_id IN ({oids})'))
                deleted += res.rowcount or 0
        if customer_ids:
            cids = csv(customer_ids)
            for t in customer_child:
                if t in rid_tabs:
                    continue  # handled by the restaurant_id sweep
                res = await s.execute(
                    text(f'DELETE FROM "{t}" WHERE customer_id IN ({cids})')
                )
                deleted += res.rowcount or 0

        for t in rid_tabs:
            res = await s.execute(
                text(f'DELETE FROM "{t}" WHERE restaurant_id IN ({id_list})')
            )
            deleted += res.rowcount or 0

        res = await s.execute(text(f"DELETE FROM restaurants WHERE id IN ({id_list})"))
        rest_deleted = res.rowcount or 0

        await s.execute(text("SET session_replication_role = default"))
        await s.commit()
        print(f"Deleted {rest_deleted} restaurants and {deleted} dependent rows.")
        remaining = [
            (r[0], r[1])
            for r in (
                await s.execute(text("SELECT id, name FROM restaurants ORDER BY id"))
            ).all()
        ]
        print("Remaining restaurants:")
        for rid, name in remaining:
            print(f"  #{rid}  {name}")
        break


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:]] or [1, 2, 3]
    asyncio.run(main(ids))
