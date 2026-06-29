"""Utility-template management (manager JWT).

Submit the transactional utility templates (wallet credit, coupon, complaint
resolution) for Meta approval. Needed once per restaurant before out-of-window
notifications can be delivered in production.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.whatsapp.templates import UTILITY_TEMPLATES, register_utility_templates

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


@router.get("/utility")
async def list_utility_templates() -> dict:
    """The utility templates this platform uses (for reference)."""
    return {
        name: {"language": spec["language"], "category": spec["category"], "body": spec["body"]}
        for name, spec in UTILITY_TEMPLATES.items()
    }


@router.post("/utility/register", status_code=201)
async def register_utility(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Submit all utility templates for approval for this restaurant. Idempotent."""
    submitted = await register_utility_templates(session, restaurant_id=restaurant.id)
    await session.commit()
    return {"submitted": submitted}
