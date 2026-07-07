from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ComboIn(BaseModel):
    name: str
    price_aed: Decimal
    dish_ids: list[int]


class ComboOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price_aed: Decimal
    is_available: bool
    dish_ids: list[int]

    @classmethod
    def from_combo(cls, combo) -> "ComboOut":
        return cls(
            id=combo.id,
            name=combo.name,
            price_aed=combo.price_aed,
            is_available=combo.is_available,
            dish_ids=[item.dish_id for item in combo.items],
        )
