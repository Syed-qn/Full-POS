from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class CatalogProduct(Base, TimestampMixin):
    """A product mirrored from the restaurant's Meta Commerce catalogue.

    Populated by the OPS "Sync from Meta" action (catalog mode only), which reads
    GET /{catalog_id}/products with a system-user catalog_management token. This is
    the catalogue source of truth for chat injection in catalog mode — independent of
    the text-menu ``dishes`` table. One row per (restaurant, retailer_id).
    """

    __tablename__ = "catalog_products"
    __table_args__ = (UniqueConstraint("restaurant_id", "retailer_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    # Meta product identifiers.
    retailer_id: Mapped[str] = mapped_column(String(128), index=True)
    meta_product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    # Price in AED (Meta returns e.g. "AED30.00" — parsed to a Decimal here).
    price_aed: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Whether this product is shown in the chat catalogue (manager can hide locally
    # without deleting it in Meta). Defaults true.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Full raw product JSON from Meta, for fields we don't model yet.
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
