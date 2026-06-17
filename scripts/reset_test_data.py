"""TEMP one-off: wipe test orders + delivery operations for a restaurant.

Deletes orders and every row that references them (items, batch links,
assignments, COD cash, SLA events, coupons), plus the restaurant's batches /
rider GPS pings / shift reconciliations. Riders are KEPT but reset to
'available' (pass --delete-riders to remove the rider accounts too). Optionally
clears conversations for a fresh chat (--reset-conversations).

Scope to ONE restaurant with --restaurant-phone (recommended); omit to wipe all.

Usage (PowerShell), against whichever DB you point it at:
    # live: use the Render Postgres EXTERNAL connection string (asyncpg form)
    $env:APP_DATABASE_URL = "postgresql+asyncpg://USER:PASS@HOST:PORT/DBNAME"
    .venv/Scripts/python.exe scripts/reset_test_data.py --restaurant-phone +918754568384 --yes

Without --yes it's a DRY RUN (prints counts, changes nothing).
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Children to clear, scoped to the target orders (FK-safe order: leaves first).
_ORDER_CHILD_TABLES = (
    "cod_collections",
    "sla_events",
    "coupons",
    "assignments",
    "batch_orders",
    "order_items",
)


async def _run(args: argparse.Namespace) -> None:
    from app.config import get_settings

    url = args.database_url or get_settings().database_url
    safe = url.split("@")[-1]  # never print credentials
    print(f"DB target: …@{safe}")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            if args.restaurant_phone:
                rid = (
                    await conn.execute(
                        text("SELECT id FROM restaurants WHERE phone = :p"),
                        {"p": args.restaurant_phone},
                    )
                ).scalar()
                if rid is None:
                    print(f"No restaurant with phone {args.restaurant_phone!r}. Aborting.")
                    return
                scope = " WHERE restaurant_id = :rid"
                params = {"rid": rid}
                oids = "(SELECT id FROM orders WHERE restaurant_id = :rid)"
                print(f"Scope: restaurant_id={rid} ({args.restaurant_phone})")
            else:
                scope, params, oids = "", {}, "(SELECT id FROM orders)"
                print("Scope: ALL restaurants")

            n_orders = (await conn.execute(text(f"SELECT count(*) FROM orders{scope}"), params)).scalar()
            n_riders = (await conn.execute(text(f"SELECT count(*) FROM riders{scope}"), params)).scalar()
            print(f"orders={n_orders}  riders={n_riders}")

            if not args.yes:
                print("\nDRY RUN — nothing changed. Re-run with --yes to execute.")
                return

            # Null soft references that would block the delete.
            await conn.execute(text(f"UPDATE orders SET resale_of_order_id = NULL{scope}"), params)
            await conn.execute(text(f"UPDATE coupons SET redeemed_on_order_id = NULL WHERE redeemed_on_order_id IN {oids}"), params)
            await conn.execute(text(f"UPDATE marketing_sends SET converted_order_id = NULL WHERE converted_order_id IN {oids}"), params)

            # Delete order children, then restaurant-scoped delivery ops, then orders.
            for tbl in _ORDER_CHILD_TABLES:
                await conn.execute(text(f"DELETE FROM {tbl} WHERE order_id IN {oids}"), params)
            await conn.execute(text(f"DELETE FROM batches{scope}"), params)
            await conn.execute(text(f"DELETE FROM rider_locations{scope}"), params)
            await conn.execute(text(f"DELETE FROM rider_shift_reconciliations{scope}"), params)
            await conn.execute(text(f"DELETE FROM orders{scope}"), params)

            if args.reset_conversations:
                await conn.execute(
                    text(f"DELETE FROM messages WHERE conversation_id IN "
                         f"(SELECT id FROM conversations{scope})"),
                    params,
                )
                await conn.execute(text(f"DELETE FROM conversations{scope}"), params)
                print("conversations + messages cleared")

            if args.delete_riders:
                await conn.execute(text(f"DELETE FROM riders{scope}"), params)
                print("riders deleted")
            else:
                await conn.execute(text(f"UPDATE riders SET status = 'available'{scope}"), params)
                print("riders reset to 'available'")

            print(f"\n✅ Reset complete — removed {n_orders} order(s) and their delivery data.")
    finally:
        await engine.dispose()


def main() -> None:
    ap = argparse.ArgumentParser(description="Wipe test orders + delivery ops for a restaurant.")
    ap.add_argument("--restaurant-phone", default=None, help="Scope to one restaurant by phone (recommended).")
    ap.add_argument("--database-url", default=None, help="Override DB URL (asyncpg). Defaults to APP_DATABASE_URL / .env.")
    ap.add_argument("--delete-riders", action="store_true", help="Also delete rider accounts (default: keep, reset to available).")
    ap.add_argument("--reset-conversations", action="store_true", help="Also clear conversations + messages (fresh chat).")
    ap.add_argument("--yes", action="store_true", help="Actually execute (otherwise dry run).")
    asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    main()
