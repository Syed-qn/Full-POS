"""AI menu translation (EN ↔ AR) with persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import MenuTranslation
from app.ai.text_gen import generate_narrative
from app.audit.service import record_audit

# Small built-in glossary for common restaurant words (deterministic offline).
_GLOSSARY_AR = {
    "chicken": "دجاج",
    "biryani": "برياني",
    "rice": "أرز",
    "lamb": "لحم ضأن",
    "beef": "لحم بقر",
    "fish": "سمك",
    "salad": "سلطة",
    "soup": "شوربة",
    "juice": "عصير",
    "water": "ماء",
    "bread": "خبز",
    "dessert": "حلوى",
    "spicy": "حار",
    "grilled": "مشوي",
    "fried": "مقلي",
    "kebab": "كباب",
    "shawarma": "شاورما",
}


def _heuristic_ar(text: str) -> str:
    if not text:
        return text
    out = text
    lower = text.lower()
    for en, ar in _GLOSSARY_AR.items():
        if en in lower:
            # append arabic gloss rather than mangling full sentence
            out = f"{text} ({ar})"
            break
    else:
        out = f"{text} [AR]"
    return out[:2000]


async def translate_dish(
    session: AsyncSession,
    *,
    restaurant_id: int,
    dish_id: int,
    target_lang: str = "ar",
    apply_to_dish: bool = True,
) -> MenuTranslation:
    from app.menu.models import Dish

    dish = await session.get(Dish, dish_id)
    if dish is None or dish.restaurant_id != restaurant_id:
        raise ValueError("dish not found")
    target_lang = (target_lang or "ar").lower()[:8]
    if target_lang == "ar":
        name_t = _heuristic_ar(dish.name)
        desc_t = _heuristic_ar(dish.description or "") if dish.description else None
    else:
        raw = await generate_narrative(
            "translation",
            {
                "name": dish.name,
                "description": dish.description,
                "target_lang": target_lang,
            },
        )
        parts = raw.split(" | ", 1)
        name_t = parts[0].replace(f"[{target_lang}] ", "").strip()
        desc_t = parts[1] if len(parts) > 1 else None

    existing = await session.scalar(
        select(MenuTranslation).where(
            MenuTranslation.restaurant_id == restaurant_id,
            MenuTranslation.dish_id == dish_id,
            MenuTranslation.target_lang == target_lang,
        )
    )
    if existing:
        existing.name = name_t
        existing.description = desc_t
        row = existing
    else:
        row = MenuTranslation(
            restaurant_id=restaurant_id,
            dish_id=dish_id,
            source_lang="en",
            target_lang=target_lang,
            name=name_t,
            description=desc_t,
        )
        session.add(row)
    if apply_to_dish and target_lang == "ar":
        dish.name_ar = name_t[:255]
        if desc_t:
            dish.description_ar = desc_t[:2000]
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="system",
        entity="menu_translation",
        entity_id=str(row.id),
        action="translate",
        after={"dish_id": dish_id, "target_lang": target_lang},
    )
    return row


async def translate_menu(
    session: AsyncSession, *, restaurant_id: int, target_lang: str = "ar", limit: int = 50
) -> list[MenuTranslation]:
    from app.menu.models import Dish

    dishes = list(
        (
            await session.scalars(
                select(Dish)
                .where(Dish.restaurant_id == restaurant_id, Dish.is_available.is_(True))
                .limit(min(max(limit, 1), 200))
            )
        ).all()
    )
    out = []
    for d in dishes:
        out.append(
            await translate_dish(
                session,
                restaurant_id=restaurant_id,
                dish_id=d.id,
                target_lang=target_lang,
                apply_to_dish=True,
            )
        )
    return out
