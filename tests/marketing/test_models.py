import pytest
from sqlalchemy.exc import IntegrityError

from app.marketing.models import (
    Campaign,
    MarketingSend,
    Segment,
    WaTemplate,
)
from app.ordering.models import Customer


async def _customer(db_session, restaurant, phone="+971500000001") -> Customer:
    row = Customer(restaurant_id=restaurant.id, phone=phone)
    db_session.add(row)
    await db_session.flush()
    return row


async def test_wa_template_roundtrip(db_session, restaurant):
    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name="todays_special_20260606",
        body="Today only: 20% off biryani.",
        header={"format": "image", "image_url": "https://x/i.jpg"},
        buttons=[{"type": "url", "url": "https://x"}],
        footer="Reply STOP to opt out",
    )
    db_session.add(tpl)
    await db_session.flush()
    await db_session.refresh(tpl)

    assert tpl.id is not None
    assert tpl.language == "en"
    assert tpl.category == "marketing"
    assert tpl.status == "draft"
    assert tpl.ephemeral is True
    assert tpl.header["format"] == "image"


async def test_segment_roundtrip(db_session, restaurant):
    seg = Segment(
        restaurant_id=restaurant.id,
        name="Lapsed VIPs",
        plain_english="Spent over 500 AED, no order in 30 days",
        definition={"total_spend_gte": 500, "days_since_order_gte": 30},
    )
    db_session.add(seg)
    await db_session.flush()
    await db_session.refresh(seg)

    assert seg.id is not None
    assert seg.definition["total_spend_gte"] == 500
    assert seg.last_preview_count is None


async def test_campaign_roundtrip(db_session, restaurant):
    camp = Campaign(restaurant_id=restaurant.id, type="todays_special")
    db_session.add(camp)
    await db_session.flush()
    await db_session.refresh(camp)

    assert camp.id is not None
    assert camp.status == "draft"
    assert camp.stats == {}
    assert camp.template_id is None
    assert camp.segment_id is None


async def test_marketing_send_roundtrip(db_session, restaurant):
    camp = Campaign(restaurant_id=restaurant.id, type="todays_special")
    cust = await _customer(db_session, restaurant)
    db_session.add(camp)
    await db_session.flush()

    send = MarketingSend(
        restaurant_id=restaurant.id,
        campaign_id=camp.id,
        customer_id=cust.id,
        to_phone=cust.phone,
    )
    db_session.add(send)
    await db_session.flush()
    await db_session.refresh(send)

    assert send.id is not None
    assert send.status == "queued"
    assert send.wa_message_id is None
    assert send.converted_order_id is None


async def test_wa_template_unique_name_lang(db_session, restaurant):
    common = dict(
        restaurant_id=restaurant.id,
        meta_template_name="todays_special_20260606",
        language="en",
        body="x",
    )
    db_session.add(WaTemplate(**common))
    await db_session.flush()
    db_session.add(WaTemplate(**common))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_marketing_send_unique_campaign_customer(db_session, restaurant):
    camp = Campaign(restaurant_id=restaurant.id, type="todays_special")
    cust = await _customer(db_session, restaurant)
    db_session.add(camp)
    await db_session.flush()

    common = dict(
        restaurant_id=restaurant.id,
        campaign_id=camp.id,
        customer_id=cust.id,
        to_phone=cust.phone,
    )
    db_session.add(MarketingSend(**common))
    await db_session.flush()
    db_session.add(MarketingSend(**common))
    with pytest.raises(IntegrityError):
        await db_session.flush()
