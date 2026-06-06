"""Rider conversation routing + live location updates (spec §4.4.1 / §4.4.6).

Schema adaptation vs the plan's sample code: the Rider model carries NO
``last_lat``/``last_lon``/``last_seen_at`` columns — rider position lives in the
``rider_locations`` time-series table (a row per ping), with a best-effort hot
copy to Redis GEO. So assertions are on ``RiderLocation`` rows, not Rider attrs.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.dispatch.models import RiderLocation
from app.identity.models import Restaurant, Rider
from app.whatsapp.port import InboundMessage, MessageType


async def _seed_rider(db_session):
    r = Restaurant(name="R", phone="+9712223333", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="Rider",
        phone="+971509990000",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.commit()
    return r, rider


async def test_rider_location_records_ping(db_session):
    r, rider = await _seed_rider(db_session)
    inbound = InboundMessage(
        wa_message_id="loc-1",
        from_phone=rider.phone,
        type=MessageType.LOCATION,
        payload={"latitude": 25.2100, "longitude": 55.2750},
        restaurant_phone=r.phone,
        timestamp=int(datetime.now(timezone.utc).timestamp()),
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()

    ping = await db_session.scalar(
        select(RiderLocation).where(RiderLocation.rider_id == rider.id)
    )
    assert ping is not None
    assert ping.latitude == 25.2100
    assert ping.longitude == 55.2750
    assert ping.restaurant_id == r.id
    assert ping.ts is not None


async def test_rider_conversation_counterpart_is_rider(db_session):
    r, rider = await _seed_rider(db_session)
    inbound = InboundMessage(
        wa_message_id="loc-2",
        from_phone=rider.phone,
        type=MessageType.LOCATION,
        payload={"latitude": 25.21, "longitude": 55.27},
        restaurant_phone=r.phone,
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.phone == rider.phone)
    )
    assert conv.counterpart == "rider"


async def test_unknown_phone_routed_as_customer(db_session):
    r, rider = await _seed_rider(db_session)
    inbound = InboundMessage(
        wa_message_id="cust-1",
        from_phone="+971508887777",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone=r.phone,
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.phone == "+971508887777")
    )
    assert conv.counterpart == "customer"
