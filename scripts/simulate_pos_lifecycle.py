#!/usr/bin/env python3
"""End-to-end POS integration simulator — NO real POS needed.

Plays BOTH sides of the integration on your machine, in-process:

  * YOUR PLATFORM (OPS engine): real service functions drive one order
    from customer-confirm -> preparing -> ready -> dispatch -> delivered.
  * THE POS PARTNER: a local HTTP server receives every webhook we send,
    and we act as the POS by advancing kitchen status through the same
    entry point the real POS API uses (``apply_partner_kitchen_status``).

At each step it prints which webhook the POS received (event, HMAC
signature present, body) so you can *see* the whole round-trip work.

It runs against a throwaway ``restaurant_sim`` database whose schema is
built straight from the models (same as the test suite), so it never
touches — and never needs — your (possibly drifted) dev DB. The sim DB is
dropped + recreated fresh on every run.

Requires only the docker DB (``docker compose up -d``). No uvicorn, no
Celery, no migrations. Nothing here ships to prod.

Run from repo root:
  .venv/Scripts/python scripts/simulate_pos_lifecycle.py
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Pin everything to offline/fake BEFORE importing the app ──────────────────
# Dedicated sim DB so we never touch the dev DB. Same creds as docker compose.
_BASE_URL = "postgresql+asyncpg://app:app@localhost:5433"
os.environ["APP_DATABASE_URL"] = f"{_BASE_URL}/restaurant_sim"
os.environ["APP_OUTBOX_SYNC_DELIVERY"] = "true"   # deliver webhooks in-process
os.environ.setdefault("APP_LLM_PROVIDER", "fake")
os.environ.setdefault("APP_WHATSAPP_PROVIDER", "mock")
os.environ.setdefault("APP_GEO_PROVIDER", "fake")
os.environ.setdefault("APP_PUSH_PROVIDER", "fake")
os.environ.setdefault("APP_STT_PROVIDER", "fake")
os.environ.setdefault("APP_MARKETING_SEND_DRY_RUN", "true")
os.environ.setdefault("APP_MARKETING_TEMPLATE_PROVIDER", "mock")
os.environ.setdefault("APP_DISPATCH_INPROCESS_SWEEP", "false")
os.environ.setdefault("APP_RATE_LIMIT_ENABLED", "false")

import asyncpg  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.db import Base  # noqa: E402

# Register ALL model metadata (mirror tests/conftest.py) so create_all is complete.
import app.audit.models  # noqa: E402,F401
import app.identity.models  # noqa: E402,F401
import app.menu.models  # noqa: E402,F401
import app.webhook.models  # noqa: E402,F401
import app.outbox.models  # noqa: E402,F401
import app.conversation.models  # noqa: E402,F401
import app.ordering.models  # noqa: E402,F401
import app.dispatch.models  # noqa: E402,F401
import app.sla.models  # noqa: E402,F401
import app.coupons.models  # noqa: E402,F401
import app.cod.models  # noqa: E402,F401
import app.marketing.models  # noqa: E402,F401
import app.predictions.models  # noqa: E402,F401
import app.partner.models  # noqa: E402,F401
import app.wallet.models  # noqa: E402,F401
import app.tickets.models  # noqa: E402,F401
import app.okf.models  # noqa: E402,F401
import app.catalog.models  # noqa: E402,F401

from app.cod.service import record_collection  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.dispatch.delivery import advance_delivery  # noqa: E402
from app.dispatch.models import RiderLocation  # noqa: E402
from app.dispatch.service import run_dispatch_engine  # noqa: E402
from app.identity.models import Restaurant, Rider  # noqa: E402
from app.menu.models import Dish, Menu  # noqa: E402
from app.ordering.fsm import OrderStatus  # noqa: E402
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem  # noqa: E402
from app.ordering.service import finalize_confirmation  # noqa: E402
from app.partner.integration import apply_partner_settings  # noqa: E402
from app.partner.orders_api import apply_partner_kitchen_status  # noqa: E402
from app.partner.webhooks.dispatch import flush_pending_partner_webhooks  # noqa: E402

WEBHOOK_PORT = int(os.environ.get("SIM_WEBHOOK_PORT", "8766"))
WEBHOOK_SECRET = "sim-secret"
POS_STORE_ID = "CRT-SIM-001"

received: list[dict] = []  # the fake POS fills this as webhooks arrive


class _PosHandler(BaseHTTPRequestHandler):
    """The pretend POS partner's single webhook receiver endpoint."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received.append(
            {
                "event": self.headers.get("X-Partner-Event"),
                "idem": self.headers.get("X-Partner-Idempotency-Key"),
                "signed": bool(
                    self.headers.get("X-Partner-Signature", "").startswith("sha256=")
                ),
                "body": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:  # noqa: A003 - silence default logging
        return


def _print_new_webhooks(seen: int) -> int:
    new = received[seen:]
    if not new:
        print("   (no webhook received at this step)")
    for hit in new:
        data = hit["body"]["data"] if hit["body"] else {}
        sig = "HMAC ok" if hit["signed"] else "UNSIGNED!"
        print(f"   >> POS received: {hit['event']:22s} [{sig}]  idem={hit['idem']}")
        for field in ("order_number", "status", "rider", "cod_collected", "coupon_code"):
            if data.get(field) is not None:
                val = data[field]
                if isinstance(val, dict):
                    val = val.get("name") or val
                print(f"        {field}: {val}")
    return len(received)


async def _reset_sim_database() -> None:
    """Create restaurant_sim if missing, then build a fresh schema from models."""
    admin = await asyncpg.connect(
        user="app", password="app", host="localhost", port=5433, database="restaurant"
    )
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'restaurant_sim'"
        )
        if not exists:
            await admin.execute("CREATE DATABASE restaurant_sim")
            print("   created database restaurant_sim")
    finally:
        await admin.close()

    engine = create_async_engine(os.environ["APP_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS postgis;")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("   schema rebuilt from models (drop_all + create_all)")


async def run() -> int:
    print("Preparing throwaway sim database...")
    await _reset_sim_database()

    server = HTTPServer(("127.0.0.1", WEBHOOK_PORT), _PosHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"0. Fake POS receiver on http://127.0.0.1:{WEBHOOK_PORT}/hooks/whatsapp\n")

    seen = 0
    async with async_session_factory() as session:
        rest = Restaurant(
            name="POS Lifecycle Sandbox",
            phone="+971509990002",
            password_hash="x",
            lat=25.2048,
            lng=55.2708,
            settings={"dispatch_engine": "greedy"},
        )
        session.add(rest)
        await session.flush()
        apply_partner_settings(
            rest,
            {
                "partner_enabled": True,
                "partner_webhook_url": f"http://127.0.0.1:{WEBHOOK_PORT}/hooks/whatsapp",
                "partner_webhook_secret": WEBHOOK_SECRET,
                "pos_store_id": POS_STORE_ID,
                "pos_order_push_mode": "webhook",
            },
        )
        await session.commit()
        print(f"1. Sandbox restaurant id={rest.id}, partner webhook -> local POS")

        menu = Menu(restaurant_id=rest.id, version=1, status="active", source_files=[])
        session.add(menu)
        await session.flush()
        dish = Dish(
            menu_id=menu.id,
            restaurant_id=rest.id,
            dish_number=110,
            name="Grill Mandi",
            price_aed=Decimal("100.00"),
            category="Main",
            is_available=True,
        )
        session.add(dish)

        rider = Rider(
            restaurant_id=rest.id,
            name="Ahmed",
            phone="+971500000111",
            status="available",
            performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
        )
        session.add(rider)
        await session.flush()
        session.add(
            RiderLocation(
                rider_id=rider.id,
                restaurant_id=rest.id,
                latitude=25.2048,
                longitude=55.2708,
                ts=datetime.now(timezone.utc),
            )
        )

        cust = Customer(restaurant_id=rest.id, phone="+971500000222", name="Sara")
        session.add(cust)
        await session.flush()
        addr = CustomerAddress(
            customer_id=cust.id,
            room_apartment="101",
            building="Tower A",
            receiver_name="Sara",
            latitude=25.20,
            longitude=55.30,
            confirmed=True,
        )
        session.add(addr)
        await session.flush()

        order = Order(
            restaurant_id=rest.id,
            customer_id=cust.id,
            order_number="SIM-0001",
            status=OrderStatus.PENDING_CONFIRMATION,
            address_id=addr.id,
            subtotal=Decimal("100.00"),
            delivery_fee_aed=Decimal("10.00"),
            total=Decimal("110.00"),
        )
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                dish_id=dish.id,
                dish_number=110,
                dish_name="Grill Mandi",
                price_aed=Decimal("100.00"),
                qty=1,
            )
        )
        await session.commit()
        print(f"2. Built order SIM-0001 (id={order.id}) in PENDING_CONFIRMATION\n")

        # STAGE 1 — customer confirms on WhatsApp -> order.created
        print("3. Customer CONFIRMS on WhatsApp  -> finalize_confirmation()")
        await finalize_confirmation(session, order=order, actor="customer")
        await session.commit()
        await flush_pending_partner_webhooks(session, restaurant_id=rest.id)
        seen = _print_new_webhooks(seen)
        print()

        order = await session.get(Order, order.id)
        order.sla_confirmed_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        order.sla_deadline = order.sla_confirmed_at + timedelta(minutes=40)
        order.promised_eta = order.sla_deadline
        await session.commit()

        # STAGE 2 — POS marks PREPARING (real POS entry point)
        print("4. POS taps PREPARING  -> apply_partner_kitchen_status('preparing')")
        await apply_partner_kitchen_status(
            session, restaurant=rest, order_id=order.id, pos_status="preparing"
        )
        await session.commit()
        await flush_pending_partner_webhooks(session, restaurant_id=rest.id)
        seen = _print_new_webhooks(seen)
        print()

        # STAGE 3 — POS marks READY -> MAIN ENGINE: dispatch assigns a rider
        print("5. POS taps READY  -> apply_partner_kitchen_status('ready')  [MAIN ENGINE]")
        await apply_partner_kitchen_status(
            session, restaurant=rest, order_id=order.id, pos_status="ready"
        )
        await session.commit()
        order = await session.get(Order, order.id)
        if order.rider_id is None:
            await run_dispatch_engine(session, restaurant_id=rest.id)
            await session.commit()
        await flush_pending_partner_webhooks(session, restaurant_id=rest.id)
        seen = _print_new_webhooks(seen)
        order = await session.get(Order, order.id)
        print(f"   order status now: {order.status}  rider_id={order.rider_id}\n")

        if order.rider_id is None:
            print("!! No rider assigned — dispatch could not place the order. Stopping.")
            server.shutdown()
            return 1

        # STAGE 4 — rider PICKUP -> order.picked_up
        print("6. Rider taps PICKUP  -> advance_delivery('picked_up')")
        await advance_delivery(session, order_id=order.id, to_status="picked_up")
        await session.commit()
        await flush_pending_partner_webhooks(session, restaurant_id=rest.id)
        seen = _print_new_webhooks(seen)
        print()

        # STAGE 5 — rider DELIVERED + COD -> order.delivered
        print("7. Rider taps DELIVERED + collects COD  -> advance_delivery + record_collection")
        await advance_delivery(session, order_id=order.id, to_status="arriving")
        await advance_delivery(session, order_id=order.id, to_status="delivered")
        await record_collection(
            session,
            restaurant_id=rest.id,
            order_id=order.id,
            rider_id=order.rider_id,
            amount=Decimal("110.00"),
        )
        await session.commit()
        await flush_pending_partner_webhooks(session, restaurant_id=rest.id)
        seen = _print_new_webhooks(seen)
        print()

    server.shutdown()

    events = [h["event"] for h in received]
    expected = ["order.created", "order.rider_assigned", "order.picked_up", "order.delivered"]
    print("=" * 62)
    print(f"POS received {len(received)} webhook(s): {events}")
    missing = [e for e in expected if e not in events]
    if missing:
        print(f"FAIL — missing expected events: {missing}")
        return 1
    print(f"All webhooks HMAC-signed: {all(h['signed'] for h in received)}")
    print("PASS - full POS order lifecycle round-tripped end to end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
