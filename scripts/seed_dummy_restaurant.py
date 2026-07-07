"""Seed a fully-populated dummy restaurant for local dashboard/desktop-app testing.

Unlike scripts/seed_dev.py (menu + one rider only), this seeds a broad spread of
data across every module so every dashboard screen has something real to show:
menu with variants, riders + locations, customers + addresses, orders in every
major status (delivered+COD, cancelled, resold, in-flight/dispatched, pending),
coupons, wallet entries, support tickets, marketing (template/segment/campaign/
automation/send), predictions (runs/model registry/manager override), SLA
breach events, a dispatch batch + assignment, and a rider shift reconciliation.

Idempotent at the restaurant level: if a restaurant with DUMMY_PHONE already
exists, the script exits without touching it (re-run after manually deleting
the restaurant row — cascades — to reseed fresh).

Run from repo root with the venv, against the real dev DB (docker compose up -d):

    APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/restaurant \\
      .venv/bin/python scripts/seed_dummy_restaurant.py
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("APP_LLM_PROVIDER", "fake")

from sqlalchemy import select  # noqa: E402

from app.cod.models import CodCollection, RiderShiftReconciliation  # noqa: E402
from app.coupons.models import Coupon  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation  # noqa: E402
from app.identity.auth import hash_password  # noqa: E402
from app.identity.models import Restaurant, Rider  # noqa: E402
from app.marketing.models import (  # noqa: E402
    Campaign,
    MarketingAutomation,
    MarketingSend,
    Segment,
    WaTemplate,
)
from app.menu.models import Dish, Menu  # noqa: E402
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem  # noqa: E402
from app.predictions.models import ManagerOverride, ModelRegistry, PredictionRun  # noqa: E402
from app.sla.models import SlaEvent  # noqa: E402
from app.tickets.models import Ticket  # noqa: E402
from app.wallet.models import WalletAccount, WalletEntry  # noqa: E402

DUMMY_PHONE = "+971500001234"
DUMMY_NAME = "Al Fanar Grill (Demo)"
LAT, LNG = 25.2048, 55.2708  # Downtown Dubai


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def main() -> None:
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(Restaurant).where(Restaurant.phone == DUMMY_PHONE)
        )
        if existing is not None:
            print(f"Dummy restaurant already exists (id={existing.id}, phone={DUMMY_PHONE}).")
            print("Delete that restaurant row (cascades) to reseed fresh. Exiting.")
            return

        # ---- Restaurant ----
        rest = Restaurant(
            name=DUMMY_NAME,
            phone=DUMMY_PHONE,
            password_hash=hash_password("Demo@1234"),
            lat=LAT,
            lng=LNG,
            settings={
                "max_orders_per_batch": 3,
                "max_items_per_order": 20,
                "radius_km": 10,
                "catalog_native_view": True,
            },
        )
        session.add(rest)
        await session.flush()
        print(f"Restaurant id={rest.id}  phone={DUMMY_PHONE}  password=Demo@1234")

        # ---- Menu ----
        menu = Menu(restaurant_id=rest.id, version=1, status="active", source_files=[])
        session.add(menu)
        await session.flush()

        dish_specs = [
            (101, "Chicken Shawarma", "18.00", "Sandwiches", "Grilled chicken, garlic sauce, pickles.", []),
            (102, "Beef Shawarma", "20.00", "Sandwiches", "Slow-roasted beef, tahini, pickles.", []),
            (110, "Mixed Grill Platter", "65.00", "Grills", "Kebab, shish tawook, kofta, rice.", [
                {"name": "Half", "price_aed": "38.00", "dish_number": None},
                {"name": "Full", "price_aed": "65.00", "dish_number": None},
            ]),
            (120, "Chicken Biryani", "28.00", "Biryani", "Basmati rice, spiced chicken, raita.", [
                {"name": "1 serve", "price_aed": "28.00", "dish_number": None},
                {"name": "4 serve", "price_aed": "95.00", "dish_number": None},
            ]),
            (121, "Mutton Biryani", "35.00", "Biryani", "Basmati rice, tender mutton, raita.", []),
            (130, "Hummus", "14.00", "Starters", "Chickpea dip, olive oil, pita.", []),
            (131, "Fattoush Salad", "16.00", "Starters", "Mixed greens, sumac, crispy bread.", []),
            (140, "Baklava (6pc)", "22.00", "Desserts", "Layered filo, pistachio, honey syrup.", []),
            (150, "Fresh Lime Mint", "10.00", "Drinks", "Fresh lime, mint, soda.", []),
            (151, "Mango Lassi", "12.00", "Drinks", "Yoghurt, mango pulp.", []),
        ]
        dishes: dict[int, Dish] = {}
        for number, name, price, category, desc, variants in dish_specs:
            d = Dish(
                menu_id=menu.id,
                restaurant_id=rest.id,
                dish_number=number,
                name=name,
                price_aed=Decimal(price),
                category=category,
                description=desc,
                is_available=True,
                name_normalized=name.lower(),
                variants=variants,
            )
            session.add(d)
            dishes[number] = d
        await session.flush()
        print(f"Menu id={menu.id}  {len(dish_specs)} dishes")

        # ---- Riders + locations ----
        rider_specs = [
            ("Ahmed Khan", "+971501110001", "available", 96.5, 22),
            ("Rashid Ali", "+971501110002", "on_delivery", 88.0, 27),
            ("Faisal Noor", "+971501110003", "off_shift", 92.0, 24),
        ]
        riders: list[Rider] = []
        for name, phone, status, on_time_pct, avg_min in rider_specs:
            r = Rider(
                restaurant_id=rest.id,
                name=name,
                phone=phone,
                status=status,
                performance={
                    "on_time_pct": on_time_pct,
                    "avg_delivery_min": avg_min,
                    "total_deliveries": 40,
                },
            )
            session.add(r)
            riders.append(r)
        await session.flush()
        for r in riders:
            session.add(
                RiderLocation(
                    rider_id=r.id, restaurant_id=rest.id,
                    latitude=LAT + 0.01, longitude=LNG + 0.01, ts=_now(),
                )
            )
        print(f"{len(riders)} riders seeded")

        # ---- Customers + addresses ----
        customer_specs = [
            ("Sara Ahmed", "+971502220001"),
            ("Mohammed Yusuf", "+971502220002"),
            ("Fatima Al Marzooqi", "+971502220003"),
            ("Khalid Rahman", "+971502220004"),
            ("Layla Haddad", "+971502220005"),
        ]
        customers: list[Customer] = []
        for name, phone in customer_specs:
            c = Customer(
                restaurant_id=rest.id, phone=phone, name=name,
                first_order_at=_now() - timedelta(days=30),
                last_order_at=_now() - timedelta(days=1),
                total_orders=12, total_spend=Decimal("540.00"),
            )
            session.add(c)
            customers.append(c)
        await session.flush()
        addresses: list[CustomerAddress] = []
        for i, c in enumerate(customers):
            a = CustomerAddress(
                customer_id=c.id,
                latitude=LAT + i * 0.005, longitude=LNG + i * 0.005,
                room_apartment=f"{100 + i}", building=f"Tower {chr(65 + i)}",
                receiver_name=c.name, confirmed=True, last_used_at=_now(),
            )
            session.add(a)
            addresses.append(a)
        await session.flush()
        print(f"{len(customers)} customers + addresses seeded")

        # ---- Order 1: DELIVERED, COD collected, on time ----
        o1 = Order(
            restaurant_id=rest.id, customer_id=customers[0].id, order_number="DEMO-0001",
            status="delivered", address_id=addresses[0].id, rider_id=riders[0].id,
            subtotal=Decimal("46.00"), delivery_fee_aed=Decimal("5.00"), total=Decimal("51.00"),
            distance_km=3.2, distance_source="haversine_fallback",
            sla_confirmed_at=_now() - timedelta(minutes=50),
            sla_deadline=_now() - timedelta(minutes=10),
            promised_eta=_now() - timedelta(minutes=10),
            delivered_at=_now() - timedelta(minutes=5), late=False,
        )
        session.add(o1)
        await session.flush()
        session.add(OrderItem(
            order_id=o1.id, dish_id=dishes[101].id, dish_number=101, dish_name="Chicken Shawarma",
            price_aed=Decimal("18.00"), qty=1,
        ))
        session.add(OrderItem(
            order_id=o1.id, dish_id=dishes[130].id, dish_number=130, dish_name="Hummus",
            price_aed=Decimal("14.00"), qty=1,
        ))
        session.add(OrderItem(
            order_id=o1.id, dish_id=dishes[150].id, dish_number=150, dish_name="Fresh Lime Mint",
            price_aed=Decimal("10.00"), qty=1,
        ))
        session.add(CodCollection(
            order_id=o1.id, rider_id=riders[0].id, restaurant_id=rest.id,
            amount_aed=Decimal("51.00"), collected_at=_now() - timedelta(minutes=5),
        ))

        # ---- Order 2: DELIVERED LATE -> breach coupon issued ----
        o2 = Order(
            restaurant_id=rest.id, customer_id=customers[1].id, order_number="DEMO-0002",
            status="delivered", address_id=addresses[1].id, rider_id=riders[0].id,
            subtotal=Decimal("65.00"), delivery_fee_aed=Decimal("10.00"), total=Decimal("75.00"),
            distance_km=6.1, distance_source="haversine_fallback",
            sla_confirmed_at=_now() - timedelta(minutes=90),
            sla_deadline=_now() - timedelta(minutes=50),
            promised_eta=_now() - timedelta(minutes=50),
            delivered_at=_now() - timedelta(minutes=42), late=True,
        )
        session.add(o2)
        await session.flush()
        session.add(OrderItem(
            order_id=o2.id, dish_id=dishes[110].id, dish_number=110, dish_name="Mixed Grill Platter",
            variant_name="Full", price_aed=Decimal("65.00"), qty=1,
        ))
        session.add(CodCollection(
            order_id=o2.id, rider_id=riders[0].id, restaurant_id=rest.id,
            amount_aed=Decimal("75.00"), collected_at=_now() - timedelta(minutes=42),
        ))
        session.add(SlaEvent(
            order_id=o2.id, restaurant_id=rest.id, type="yellow_30",
            ts=_now() - timedelta(minutes=60), notified={"customer": False, "manager": True},
        ))
        session.add(SlaEvent(
            order_id=o2.id, restaurant_id=rest.id, type="red_35",
            ts=_now() - timedelta(minutes=55), notified={"customer": False, "manager": True},
        ))
        session.add(SlaEvent(
            order_id=o2.id, restaurant_id=rest.id, type="breach_40",
            ts=_now() - timedelta(minutes=50), notified={"customer": True, "manager": True},
        ))
        breach_coupon = Coupon(
            restaurant_id=rest.id, customer_id=customers[1].id, order_id=o2.id,
            code="SORRY10", kind="single_use", discount_type="percent", percent=Decimal("10.00"),
            max_discount_aed=Decimal("20.00"), applies_to="whole_order", status="issued",
            expires_at=_now() + timedelta(days=30), created_by="system:sla_breach",
        )
        session.add(breach_coupon)

        # ---- Order 3: CANCELLED (before cooking) ----
        o3 = Order(
            restaurant_id=rest.id, customer_id=customers[2].id, order_number="DEMO-0003",
            status="cancelled", address_id=addresses[2].id,
            subtotal=Decimal("28.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("28.00"),
            cancellation_reason="Customer changed mind", cancelled_at=_now() - timedelta(hours=2),
        )
        session.add(o3)
        await session.flush()
        session.add(OrderItem(
            order_id=o3.id, dish_id=dishes[120].id, dish_number=120, dish_name="Chicken Biryani",
            variant_name="1 serve", price_aed=Decimal("28.00"), qty=1,
        ))

        # ---- Order 4: PENDING_CONFIRMATION (fresh, awaiting customer confirm) ----
        o4 = Order(
            restaurant_id=rest.id, customer_id=customers[3].id, order_number="DEMO-0004",
            status="pending_confirmation", address_id=addresses[3].id,
            subtotal=Decimal("34.00"), delivery_fee_aed=Decimal("5.00"), total=Decimal("39.00"),
        )
        session.add(o4)
        await session.flush()
        session.add(OrderItem(
            order_id=o4.id, dish_id=dishes[131].id, dish_number=131, dish_name="Fattoush Salad",
            price_aed=Decimal("16.00"), qty=1,
        ))
        session.add(OrderItem(
            order_id=o4.id, dish_id=dishes[151].id, dish_number=151, dish_name="Mango Lassi",
            price_aed=Decimal("12.00"), qty=1,
        ))

        # ---- Order 5: READY + ASSIGNED + PICKED_UP -> live dispatch batch ----
        o5 = Order(
            restaurant_id=rest.id, customer_id=customers[4].id, order_number="DEMO-0005",
            status="picked_up", address_id=addresses[4].id, rider_id=riders[1].id,
            subtotal=Decimal("35.00"), delivery_fee_aed=Decimal("5.00"), total=Decimal("40.00"),
            distance_km=4.0, distance_source="haversine_fallback",
            sla_confirmed_at=_now() - timedelta(minutes=15),
            sla_deadline=_now() + timedelta(minutes=25),
            promised_eta=_now() + timedelta(minutes=25),
        )
        session.add(o5)
        await session.flush()
        session.add(OrderItem(
            order_id=o5.id, dish_id=dishes[121].id, dish_number=121, dish_name="Mutton Biryani",
            price_aed=Decimal("35.00"), qty=1,
        ))
        batch = Batch(
            restaurant_id=rest.id, rider_id=riders[1].id, status="in_progress",
            route={"stops": [{"order_id": o5.id, "lat": LAT + 0.02, "lon": LNG + 0.02, "eta_min": 12}]},
            total_est_min=12,
        )
        session.add(batch)
        await session.flush()
        session.add(BatchOrder(batch_id=batch.id, order_id=o5.id, sequence=1))
        session.add(Assignment(
            order_id=o5.id, rider_id=riders[1].id, batch_id=batch.id, assigned_at=_now() - timedelta(minutes=10),
            algorithm_score={
                "distance_km": 1.8, "workload_score": 0.4, "area_score": 0.9,
                "on_time_pct": 88.0, "composite": 0.82,
            },
        ))

        # ---- Order 6: cancelled-after-cooking -> ON_RESALE ----
        o6 = Order(
            restaurant_id=rest.id, customer_id=customers[0].id, order_number="DEMO-0006",
            status="on_resale", address_id=addresses[0].id,
            subtotal=Decimal("65.00"), delivery_fee_aed=Decimal("5.00"), total=Decimal("70.00"),
            cancellation_reason="Customer unreachable", cancelled_at=_now() - timedelta(minutes=20),
            exclusion_hash="demo-exclusion-hash-0006",
        )
        session.add(o6)
        await session.flush()
        session.add(OrderItem(
            order_id=o6.id, dish_id=dishes[110].id, dish_number=110, dish_name="Mixed Grill Platter",
            variant_name="Full", price_aed=Decimal("65.00"), qty=1,
        ))

        await session.commit()
        print("6 demo orders seeded (delivered x2, cancelled, pending_confirmation, picked_up, on_resale)")

        # ---- Rider shift reconciliation ----
        session.add(RiderShiftReconciliation(
            rider_id=riders[0].id, restaurant_id=rest.id, shift_date=date.today(),
            expected_total_aed=Decimal("126.00"), collected_total_aed=Decimal("126.00"),
            variance_aed=Decimal("0.00"), status="balanced",
        ))

        # ---- Wallet ----
        wallet = WalletAccount(restaurant_id=rest.id, customer_id=customers[1].id, status="active")
        session.add(wallet)
        await session.flush()
        session.add(WalletEntry(
            account_id=wallet.id, restaurant_id=rest.id, amount_aed=Decimal("15.00"),
            type="refund_credit", status="posted", idempotency_key="demo-wallet-refund-0002",
            order_id=o2.id, reason_note="Late delivery goodwill credit", created_by="system:demo",
        ))

        # ---- Tickets ----
        session.add(Ticket(
            restaurant_id=rest.id, customer_id=customers[1].id, order_id=o2.id,
            source_message="Order arrived 40 minutes late, food was cold.",
            evidence=[], category="delivery", status="resolved",
            assigned_to="manager", resolution_action="wallet_refund",
            resolution_amount_aed=Decimal("15.00"),
            resolution_note="Issued AED 15 wallet credit + apology coupon.",
            resolved_at=_now() - timedelta(minutes=30),
        ))
        session.add(Ticket(
            restaurant_id=rest.id, customer_id=customers[2].id, order_id=o3.id,
            source_message="Wrong item was about to be sent, cancelled in time.",
            evidence=[], category="other", status="open", assigned_to="manager",
        ))

        # ---- Marketing: template, segment, campaign, automation, send ----
        template = WaTemplate(
            restaurant_id=rest.id, meta_template_name="demo_todays_special", language="en",
            category="marketing", header={"type": "text", "text": "Today's Special"},
            body="Hi {{1}}! Try our Mixed Grill Platter today — 15% off with code SPECIAL15.",
            footer="Reply STOP to opt out", buttons=[], status="approved", ephemeral=True,
            meta_template_id="demo-meta-tpl-001",
        )
        session.add(template)
        segment = Segment(
            restaurant_id=rest.id, name="Ordered biryani 2+ times (30d)",
            plain_english="customers who ordered biryani 2 or more times in the last 30 days",
            definition={"op": "and", "clauses": [
                {"field": "dish_category", "op": "eq", "value": "Biryani"},
                {"field": "order_count_30d", "op": "gte", "value": 2},
            ]},
            last_preview_count=len(customers),
        )
        session.add(segment)
        await session.flush()
        campaign = Campaign(
            restaurant_id=rest.id, type="todays_special", template_id=template.id,
            segment_id=segment.id, image_url=None, coupon_value="15%",
            scheduled_at=_now() - timedelta(hours=1), status="sent",
            stats={"sent": len(customers), "delivered": len(customers), "read": 3, "converted": 1},
        )
        session.add(campaign)
        automation = MarketingAutomation(
            restaurant_id=rest.id, preset_key="welcome", enabled=True, template_id=template.id,
            segment_id=None, config={"delay_hours": 1},
            stats={"sent": 12, "converted": 4}, last_run_at=_now() - timedelta(hours=3),
        )
        session.add(automation)
        await session.flush()
        for i, c in enumerate(customers):
            session.add(MarketingSend(
                restaurant_id=rest.id, campaign_id=campaign.id, customer_id=c.id,
                to_phone=c.phone, status="delivered" if i else "read",
                wa_message_id=f"demo-wamid-{i}", sent_at=_now() - timedelta(hours=1),
            ))

        # ---- Predictions ----
        for horizon in ("lunch", "dinner"):
            session.add(PredictionRun(
                restaurant_id=rest.id, horizon=horizon, target_date=date.today(),
                predicted={
                    "order_count": 42 if horizon == "lunch" else 68,
                    "revenue": 2100.0 if horizon == "lunch" else 3400.0,
                    "dish_demand": {"Chicken Shawarma": 15, "Mixed Grill Platter": 9},
                    "avg_distance_km": 4.2,
                },
                actual=None, accuracy=0.82, model_version="rolling-v1", adjusted=False,
            ))
        session.add(ModelRegistry(
            restaurant_id=rest.id, model_type="rolling", version="rolling-v1",
            metrics={"mape": 0.18, "n_samples": 180},
        ))
        session.add(ManagerOverride(
            restaurant_id=rest.id, text="Expect +20% dinner orders Friday due to a nearby event.",
            parsed_effect={"horizon": "dinner", "dow": 4, "order_count_mult": 1.2},
            active_from=_now(), active_to=_now() + timedelta(days=7), enabled=True,
        ))

        await session.commit()
        print("wallet, tickets, marketing, predictions, reconciliation seeded")

    print()
    print("=" * 60)
    print(f"Dummy restaurant ready: {DUMMY_NAME}")
    print(f"  phone:    {DUMMY_PHONE}")
    print("  password: Demo@1234")
    print("  6 orders across every FSM status, 3 riders, 5 customers,")
    print("  10 dishes, coupons, wallet, tickets, marketing, predictions.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
