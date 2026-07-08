from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class Menu(Base, TimestampMixin):
    __tablename__ = "menus"
    __table_args__ = (UniqueConstraint("restaurant_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending_confirmation")
    # pending_confirmation | pending_approval | active | superseded
    # pending_approval is the menu-approval-workflow gate (submit_menu_for_approval /
    # approve_menu in service.py): a manager pushes a reviewed draft into this state and
    # a (role-gated) approver flips it to active. It is DISTINCT from
    # pending_confirmation, which is the post-upload/diff-review state before a manager
    # has looked at the extraction at all — reusing pending_confirmation for both would
    # conflate "just extracted" with "reviewed, awaiting sign-off".
    approved_by: Mapped[str | None] = mapped_column(String(255))
    source_files: Mapped[list] = mapped_column(JSONB, default=list)

    dishes: Mapped[list["Dish"]] = relationship(
        back_populates="menu", cascade="all, delete-orphan", lazy="selectin"
    )


class Dish(Base, TimestampMixin):
    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    dish_number: Mapped[int | None] = mapped_column(Integer)  # null = extraction gap, must fix before activate
    name: Mapped[str] = mapped_column(String(255))
    price_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    category: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(2000))
    # KDS station routing: explicit per-dish override; falls back to a
    # category-level default, then a restaurant's auto-created "Main" station.
    station_id: Mapped[int | None] = mapped_column(ForeignKey("kitchen_stations.id"))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    # Seasonal menu scheduling window (both nullable = always available once
    # is_available=True). Checked by menu/service.py:is_dish_currently_available and
    # wired into the ordering-facing availability lookups (matching.py, place_manual_order,
    # upsell, marketing segment compile) so a dish outside its window is excluded from
    # orders even while is_available itself stays True.
    available_from: Mapped[date | None] = mapped_column(Date)
    available_until: Mapped[date | None] = mapped_column(Date)
    # Optional serving-size variants, e.g. Chicken Biryani → 1 serve / 4 serve, each
    # with its own price. Empty list = flat dish (today's behaviour, base price_aed
    # applies). Element shape: {"name": str, "price_aed": decimal-string, "dish_number": int|null}.
    # Prices are stored as strings (JSONB has no Decimal); the schema layer coerces.
    variants: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    name_normalized: Mapped[str | None] = mapped_column(String(256))
    # WhatsApp catalog product "Content ID" (retailer id) this dish maps to, so a cart
    # sent from the catalog can be matched back to the dish. Null = not linked to the
    # catalog. Used only by the SEPARATE catalog flow; the conversation engine ignores it.
    catalog_retailer_id: Mapped[str | None] = mapped_column(String(128), index=True)
    # Estimated cook time for one portion (minutes). Null = unknown -> the order's cook
    # estimate falls back to the restaurant's default_prep_minutes setting.
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    # ── Meta Commerce catalogue product fields ───────────────────────────────────
    # These mirror the fields on Meta's "Add product" form so a dish pushed to the
    # WhatsApp catalogue carries a real photo and the optional commerce metadata.
    # Title=name, Description=description, Price=price_aed, Availability=is_available,
    # Website link=auto, Content ID=catalog_retailer_id (above) — those reuse existing
    # columns. The rest are stored here:
    #   image_url           — Images (Meta REQUIRES one; falls back to a shared
    #                         placeholder only when a dish has none).
    #   sale_price_aed      — Sale price (optional; shown struck-through in Meta).
    #   fb_product_category — Facebook product category (optional; Meta taxonomy).
    #   condition           — new | refurbished | used (Meta default "new").
    #   meta_status         — active | archived (maps to Meta visibility).
    #   brand               — Brand override (optional; defaults to restaurant name).
    image_url: Mapped[str | None] = mapped_column(String(512))
    sale_price_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    fb_product_category: Mapped[str | None] = mapped_column(String(128))
    condition: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    meta_status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    brand: Mapped[str | None] = mapped_column(String(100))
    # Manager's per-dish WhatsApp switch. True (default) → the dish is published to the
    # Meta catalogue and can show on WhatsApp (subject to the image being processed).
    # False → the manager has turned it OFF: it is unpublished from Meta and never linked
    # or shown on WhatsApp, regardless of availability/processing state.
    whatsapp_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # External POS product id (e.g. Cratis posProductId) when this dish is mirrored from a
    # POS. Null for manually-managed dishes. The POS sync owns ONLY dishes with this set;
    # it never touches manual dishes. Stable match key across syncs.
    pos_product_id: Mapped[str | None] = mapped_column(String(64), index=True)

    menu: Mapped["Menu"] = relationship(back_populates="dishes", lazy="raise_on_sql")


class MenuFile(Base, TimestampMixin):
    __tablename__ = "menu_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    menu_id: Mapped[int | None] = mapped_column(ForeignKey("menus.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str | None] = mapped_column(String(512))
