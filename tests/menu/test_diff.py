from decimal import Decimal

from app.llm.port import DishDraft
from app.menu.diff import diff_menus
from app.menu.models import Dish


def _dish(number, name, price):
    return Dish(dish_number=number, name=name, price_aed=Decimal(price))


def _draft(number, name, price):
    return DishDraft(dish_number=number, name=name, price_aed=Decimal(price))


def test_price_change_detected_by_number_and_name():
    old = [_dish(110, "Chicken Biryani", "22.00")]
    new = [_draft(110, "Chicken Biryani", "25.00")]
    report = diff_menus(old, new)
    assert report.price_changes == [
        {"dish_number": 110, "name": "Chicken Biryani",
         "old_price": Decimal("22.00"), "new_price": Decimal("25.00")}
    ]


def test_added_and_removed():
    old = [_dish(110, "Chicken Biryani", "22.00")]
    new = [_draft(201, "Mutton Karahi", "35.00")]
    report = diff_menus(old, new)
    assert report.added[0].name == "Mutton Karahi"
    assert report.removed[0]["name"] == "Chicken Biryani"


def test_same_number_different_name_flagged():
    old = [_dish(110, "Chicken Biryani", "22.00")]
    new = [_draft(110, "Beef Biryani", "22.00")]
    report = diff_menus(old, new)
    assert report.conflicts == [
        {"dish_number": 110, "old_name": "Chicken Biryani", "new_name": "Beef Biryani"}
    ]


def test_unchanged_not_reported():
    old = [_dish(110, "Chicken Biryani", "22.00")]
    new = [_draft(110, "Chicken Biryani", "22.00")]
    report = diff_menus(old, new)
    assert not report.price_changes and not report.added
    assert not report.removed and not report.conflicts


async def test_reupload_reports_diff_vs_active(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    m1 = (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()
    await client.post(f"/api/v1/menus/{m1['id']}/activate", headers=auth_headers)

    # bump a price on active menu so re-upload (same fake drafts) shows a change
    dish = next(d for d in m1["dishes"] if d["dish_number"] == 110)
    await client.patch(
        f"/api/v1/menus/{m1['id']}/dishes/{dish['id']}",
        json={"price_aed": "19.00"}, headers=auth_headers,
    )

    m2 = (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()
    changes = m2["diff_vs_active"]["price_changes"]
    assert changes == [{
        "dish_number": 110, "name": "Chicken Biryani",
        "old_price": "19.00", "new_price": "22.00",
    }]
