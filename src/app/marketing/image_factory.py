"""Factory for PromoImageGeneratorPort — env-driven like template_factory."""
from functools import lru_cache

from app.config import get_settings
from app.marketing.image_placeholder import PlaceholderPromoImageGenerator
from app.marketing.image_port import PromoImageGeneratorPort


@lru_cache
def _get_placeholder_generator() -> PlaceholderPromoImageGenerator:
    return PlaceholderPromoImageGenerator()


def get_promo_image_generator() -> PromoImageGeneratorPort:
    settings = get_settings()
    if settings.marketing_image_provider == "openai":
        key = settings.openai_api_key.get_secret_value()
        if key:
            from app.marketing.image_openai import OpenAIPromoImageGenerator

            return OpenAIPromoImageGenerator()
        # Fall back when key missing (locked P5-Q1 default).
        return _get_placeholder_generator()
    if settings.marketing_image_provider == "placeholder":
        return _get_placeholder_generator()
    raise ValueError(
        f"Unknown marketing_image_provider: {settings.marketing_image_provider!r}"
    )