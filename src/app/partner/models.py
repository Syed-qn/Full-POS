from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class PartnerApiKey(Base, TimestampMixin):
    """An API key issued to a third-party partner (e.g. a POS) for read-only,
    tenant-scoped data pulls.

    Only the SHA-256 ``key_hash`` is stored — the full key is shown to the
    manager exactly once at creation and never persisted. ``key_prefix`` is a
    short, non-secret fragment kept for display ("which key is this?").
    Revocation is a soft delete (``revoked_at``) so the audit trail survives.
    """

    __tablename__ = "partner_api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    # Manager-facing name, e.g. "Acme POS".
    label: Mapped[str] = mapped_column(String(120))
    # Non-secret leading fragment shown in the dashboard, e.g. "rk_live_ab12cd".
    key_prefix: Mapped[str] = mapped_column(String(20))
    # SHA-256 hex of the full key; unique so a hash lookup resolves one row.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# Register webhook delivery model for Alembic metadata (table lives in webhooks/).
from app.partner.webhooks.models import PartnerWebhookDelivery  # noqa: F401,E402
