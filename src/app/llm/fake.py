from app.llm.port import DishDraft, UploadedFile

_DEFAULT = [
    DishDraft(
        dish_number=110,
        name="Chicken Biryani",
        price_aed="22.00",
        category="Rice",
        description="Fragrant basmati rice with spiced chicken",
    ),
    DishDraft(
        dish_number=111,
        name="Special Chicken Biryani",
        price_aed="28.00",
        category="Rice",
        description="Premium cut chicken, saffron rice",
    ),
    DishDraft(
        dish_number=201,
        name="Mutton Karahi",
        price_aed="35.00",
        category="Curries",
        description=None,
    ),
]


class FakeExtractor:
    def __init__(self, canned: list[DishDraft] | None = None):
        self._canned = canned

    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]:
        return list(self._canned) if self._canned is not None else list(_DEFAULT)
