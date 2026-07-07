from app.config import get_settings
from app.sms.mock import MockSmsGateway
from app.sms.port import SmsPort


def get_sms_port() -> SmsPort:
    """Provider chosen by ``APP_SMS_PROVIDER``. Only ``mock`` exists today —
    no real SMS vendor (e.g. Twilio) account exists yet, so this ships the
    abstraction only, same as ``payments/factory.py`` did before Stripe."""
    settings = get_settings()
    if settings.sms_provider == "mock":
        return MockSmsGateway()
    raise ValueError(f"unknown sms_provider: {settings.sms_provider!r}")
