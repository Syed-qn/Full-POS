"""Extraction auto-assigns dish numbers (spec: number mandatory) — printed numbers are
kept, gaps/nulls are filled, and auto-assigned numbers never collide with numbers already
in the upload or with the restaurant's existing dishes."""
from sqlalchemy import select

from app.llm.fake import FakeExtractor
from app.llm.port import DishDraft, UploadedFile
from app.menu import service
from app.menu.models import Dish


def _file(name="m.jpg"):
    return [UploadedFile(filename=name, content=b"\xff\xd8", mime="image/jpeg")]


async def _numbers_by_name(db_session, menu_id):
    dishes = (
        await db_session.scalars(select(Dish).where(Dish.menu_id == menu_id))
    ).all()
    return {d.name: d.dish_number for d in dishes}


async def test_extraction_fills_missing_numbers_and_keeps_printed(db_session, restaurant):
    drafts = [
        DishDraft(dish_number=5, name="Printed Five", price_aed="10.00", category="A"),
        DishDraft(dish_number=None, name="No Number A", price_aed="12.00", category="A"),
        DishDraft(dish_number=None, name="No Number B", price_aed="8.00", category="B"),
    ]
    menu = await service.create_menu_from_upload(
        db_session, restaurant_id=restaurant.id, files=_file(),
        extractor=FakeExtractor(canned=drafts),
    )
    nums = await _numbers_by_name(db_session, menu.id)

    assert nums["Printed Five"] == 5                       # printed number preserved
    assert None not in nums.values()                        # every dish now has a number
    assert nums["No Number A"] != 5 and nums["No Number B"] != 5  # no collision w/ printed
    assert nums["No Number A"] != nums["No Number B"]       # unique within the upload


async def test_autoassigned_numbers_skip_existing_restaurant_dishes(db_session, restaurant):
    # First menu owns numbers 1 and 2.
    await service.create_menu_from_upload(
        db_session, restaurant_id=restaurant.id, files=_file("first.jpg"),
        extractor=FakeExtractor(canned=[
            DishDraft(dish_number=1, name="Old One", price_aed="5.00"),
            DishDraft(dish_number=2, name="Old Two", price_aed="6.00"),
        ]),
    )
    # Second upload, all null → must not reuse 1 or 2.
    second = await service.create_menu_from_upload(
        db_session, restaurant_id=restaurant.id, files=_file("second.jpg"),
        extractor=FakeExtractor(canned=[
            DishDraft(dish_number=None, name="New A", price_aed="7.00"),
            DishDraft(dish_number=None, name="New B", price_aed="8.00"),
        ]),
    )
    nums = await _numbers_by_name(db_session, second.id)

    assert nums["New A"] not in (1, 2)
    assert nums["New B"] not in (1, 2)
    assert nums["New A"] != nums["New B"]
