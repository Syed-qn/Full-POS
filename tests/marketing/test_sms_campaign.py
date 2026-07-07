import pytest

from app.marketing.service import send_sms_campaign
from app.sms.mock import MockSmsGateway


@pytest.mark.anyio
async def test_send_sms_campaign_sends_to_customer_phone(db_session, restaurant):
    from app.ordering.models import Customer

    cust = Customer(
        restaurant_id=restaurant.id, phone="+971500000601", name="SMS Test"
    )
    db_session.add(cust)
    await db_session.flush()

    gateway = MockSmsGateway()
    message_id = await send_sms_campaign(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        body="Your order is ready for pickup!",
        gateway=gateway,
    )

    assert isinstance(message_id, str)
    assert message_id
    assert len(gateway.sent) == 1
    assert gateway.sent[0]["to_phone"] == "+971500000601"
    assert gateway.sent[0]["body"] == "Your order is ready for pickup!"
    assert gateway.sent[0]["message_id"] == message_id


@pytest.mark.anyio
async def test_send_sms_campaign_raises_for_unknown_customer(db_session, restaurant):
    gateway = MockSmsGateway()
    with pytest.raises(ValueError):
        await send_sms_campaign(
            db_session,
            restaurant_id=restaurant.id,
            customer_id=999999,
            body="hi",
            gateway=gateway,
        )


@pytest.mark.anyio
async def test_send_sms_campaign_raises_for_customer_of_other_restaurant(
    db_session, restaurant
):
    from app.identity.models import Restaurant
    from app.ordering.models import Customer

    other = Restaurant(
        name="Other Restaurant",
        phone="+97149997777",
        password_hash="x",
        lat=25.2,
        lng=55.2,
    )
    db_session.add(other)
    await db_session.flush()

    cust = Customer(restaurant_id=other.id, phone="+971500000602", name="Other Cust")
    db_session.add(cust)
    await db_session.flush()

    gateway = MockSmsGateway()
    with pytest.raises(ValueError):
        await send_sms_campaign(
            db_session,
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            body="hi",
            gateway=gateway,
        )
