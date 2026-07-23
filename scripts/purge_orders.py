"""Hard-delete every order for a restaurant, plus everything hanging off them.

DESTRUCTIVE AND IRREVERSIBLE. Intended for resetting a demo/dev tenant to a
clean slate — never point this at production data.

Deletion order matters because `orders` is referenced by ~23 tables and
`payment_transactions` by another 4. Soft references (a coupon that merely
records which order redeemed it, a resale pointer) are NULLed instead of
cascading a delete into unrelated records.

Run: APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/restaurant \
     PYTHONPATH=src ./.venv/Scripts/python.exe scripts/purge_orders.py <restaurant_id> --yes
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

import app.kds.models  # noqa: F401
from app.db import get_session

# Nullable back-references: keep the row, drop the pointer.
SOFT_REFS: list[tuple[str, str]] = [
    ("coupons", "redeemed_on_order_id"),
    ("marketing_sends", "converted_order_id"),
    ("orders", "resale_of_order_id"),
]

# Children of payment_transactions — must go before the transactions themselves.
TXN_CHILDREN: list[tuple[str, str]] = [
    ("payment_settlement_lines", "payment_transaction_id"),
    ("credit_notes", "transaction_id"),
    ("refund_notes", "transaction_id"),
    ("payment_links", "paid_transaction_id"),
]

# Everything with a direct order_id FK. payment_transactions is deliberately
# last so its own children are gone first.
ORDER_CHILDREN: list[str] = [
    "approval_requests",
    "assignments",
    "batch_orders",
    "cod_collections",
    "coupons",
    "credit_notes",
    "e_invoice_transmissions",
    "loyalty_point_entries",
    "nps_responses",
    "offline_payment_ledger",
    "order_items",
    "order_tracking_sessions",
    "payment_links",
    "print_jobs",
    "refund_notes",
    "review_reply_suggestions",
    "sla_events",
    "staff_mistakes",
    "tickets",
    "payment_transactions",
]


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: purge_orders.py <restaurant_id> --yes")
        return
    restaurant_id = int(args[0])
    if "--yes" not in sys.argv:
        print(
            f"Refusing to run without --yes. This DELETES ALL ORDERS for "
            f"restaurant #{restaurant_id} and cannot be undone."
        )
        return

    async for session in get_session():
        ids = list(
            (
                await session.execute(
                    text("select id from orders where restaurant_id = :r"),
                    {"r": restaurant_id},
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            print(f"No orders for restaurant #{restaurant_id} — nothing to do.")
            return
        print(f"Purging {len(ids)} orders for restaurant #{restaurant_id}…")

        params = {"ids": ids}

        # 1. Drop soft pointers so we do not delete unrelated rows.
        for table, col in SOFT_REFS:
            res = await session.execute(
                text(f"update {table} set {col} = null where {col} = any(:ids)"), params
            )
            if res.rowcount:
                print(f"  ~ {table}.{col}: nulled {res.rowcount}")

        # 2. Children of payment_transactions belonging to these orders.
        txn_ids = list(
            (
                await session.execute(
                    text("select id from payment_transactions where order_id = any(:ids)"),
                    params,
                )
            )
            .scalars()
            .all()
        )
        if txn_ids:
            tparams = {"ids": txn_ids}
            for table, col in TXN_CHILDREN:
                res = await session.execute(
                    text(f"delete from {table} where {col} = any(:ids)"), tparams
                )
                if res.rowcount:
                    print(f"  - {table}: {res.rowcount}")

        # 3. Direct children.
        for table in ORDER_CHILDREN:
            res = await session.execute(
                text(f"delete from {table} where order_id = any(:ids)"), params
            )
            if res.rowcount:
                print(f"  - {table}: {res.rowcount}")

        # 4. The orders themselves.
        res = await session.execute(
            text("delete from orders where restaurant_id = :r"), {"r": restaurant_id}
        )
        print(f"  - orders: {res.rowcount}")

        # 5. Free every table — their occupied state was order-derived.
        res = await session.execute(
            text(
                "update tables set status = 'available' "
                "where restaurant_id = :r and status <> 'available'"
            ),
            {"r": restaurant_id},
        )
        if res.rowcount:
            print(f"  ~ tables freed: {res.rowcount}")

        await session.commit()
        print("Done — clean slate.")
        return


if __name__ == "__main__":
    asyncio.run(main())
