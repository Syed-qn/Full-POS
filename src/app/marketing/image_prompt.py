"""Build prompts for AI promo header images."""
from __future__ import annotations


def build_promo_image_prompt(
    *,
    restaurant_name: str,
    prompt: str | None = None,
    describe: str | None = None,
) -> str:
    """Compose a food-photography prompt from manager input."""
    offer = (prompt or describe or "").strip()
    if not offer:
        offer = "seasonal restaurant promotion"
    return (
        f"Restaurant: {restaurant_name.strip() or 'Restaurant'}\n"
        f"Offer: {offer}\n"
        "Style: appetizing food photography, clean, no text overlay, "
        "no alcohol bottles unless offer mentions it, square 1:1"
    )