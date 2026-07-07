from app.config import get_settings
from app.payments.credentials import get_restaurant_secret_key
from app.payments.mock import MockPaymentProcessor
from app.payments.port import PaymentPort


def get_payment_port(restaurant=None) -> PaymentPort:
    """Per-restaurant credentials (set via the gift-cards/settings GUI) take
    priority over the platform-wide env config, so each restaurant can bring
    its own PSP account instead of sharing one global key."""
    if restaurant is not None:
        provider = restaurant.settings.get("payment_provider", "mock")
        secret_key = get_restaurant_secret_key(restaurant)
        if provider == "stripe" and secret_key:
            from app.payments.stripe_gateway import StripeGateway

            return StripeGateway(secret_key=secret_key)

    settings = get_settings()
    if settings.payment_provider == "stripe" and settings.stripe_secret_key.get_secret_value():
        from app.payments.stripe_gateway import StripeGateway

        return StripeGateway(secret_key=settings.stripe_secret_key.get_secret_value())
    return MockPaymentProcessor()
