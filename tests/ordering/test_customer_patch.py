# tests/ordering/test_customer_patch.py
from decimal import Decimal

import pytest

from app.ordering.models import Customer, CustomerAddress
from app.ordering.service import patch_customer, patch_address


async def _seed_customer_with_address(db_session, restaurant_id):
    customer = Customer(
        restaurant_id=restaurant_id, phone="+971502223333",
        name="Original Name", total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id, room_apartment="Room 1",
        building="Old Building", receiver_name="Original Name",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()
    return customer, addr


async def test_patch_customer_name(db_session, restaurant):
    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)

    updated = await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, name="New Name", phone=None, marketing_opted_in=None,
    )
    await db_session.commit()

    assert updated.name == "New Name"


async def test_patch_customer_phone(db_session, restaurant):
    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)

    updated = await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, name=None, phone="+971509998888", marketing_opted_in=None,
    )
    await db_session.commit()

    assert updated.phone == "+971509998888"


async def test_patch_customer_opt_out(db_session, restaurant):
    from app.marketing.optout import is_opted_out

    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)

    await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, name=None, phone=None, marketing_opted_in=False,
    )
    await db_session.commit()

    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone=customer.phone)


async def test_patch_customer_opt_in(db_session, restaurant):
    from app.marketing.optout import is_opted_out, record_opt_out

    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone=customer.phone)
    await db_session.commit()

    await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, name=None, phone=None, marketing_opted_in=True,
    )
    await db_session.commit()

    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone=customer.phone)


async def test_patch_customer_opt_out_targets_original_phone(db_session, restaurant):
    """When phone and marketing_opted_in=False sent together, opt-out targets original phone."""
    from app.marketing.optout import is_opted_out

    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)
    original_phone = customer.phone  # "+971502223333"

    await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id,
        name=None,
        phone="+971509990000",
        marketing_opted_in=False,
    )
    await db_session.commit()

    # Opt-out should target the ORIGINAL phone, not the new one
    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone=original_phone)


async def test_patch_customer_wrong_tenant_raises(db_session, restaurant):
    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)

    with pytest.raises(ValueError, match="Customer not found"):
        await patch_customer(
            db_session, restaurant_id=99999,
            customer_id=customer.id, name="X", phone=None, marketing_opted_in=None,
        )


async def test_patch_address_updates_fields(db_session, restaurant):
    customer, addr = await _seed_customer_with_address(db_session, restaurant.id)

    updated = await patch_address(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, address_id=addr.id,
        room_apartment="Suite 10", building="New Tower",
        receiver_name="Updated Name", additional_details="Ring bell",
    )
    await db_session.commit()

    assert updated.room_apartment == "Suite 10"
    assert updated.building == "New Tower"
    assert updated.receiver_name == "Updated Name"
    assert updated.additional_details == "Ring bell"


async def test_patch_address_wrong_customer_raises(db_session, restaurant):
    customer, addr = await _seed_customer_with_address(db_session, restaurant.id)

    with pytest.raises(ValueError, match="Address not found"):
        await patch_address(
            db_session, restaurant_id=restaurant.id,
            customer_id=99999, address_id=addr.id,
            room_apartment=None, building=None, receiver_name=None, additional_details=None,
        )
