import copy
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin

DEFAULT_SETTINGS: dict = {
    "max_orders_per_batch": 3,
    "max_items_per_order": 20,
    # Quantity of a SINGLE line above which the bot treats the request as an
    # anomaly (e.g. "100000 lemon mints") and hands the chat to a human to confirm
    # instead of auto-adding it. Manager-editable in OPS Settings; read via .get().
    "max_item_qty": 10,
    "delivery_fee_tiers": [
        {"max_km": 3, "fee_aed": 0},
        {"max_km": 5, "fee_aed": 5},
        {"max_km": 10, "fee_aed": 10},
    ],
    "max_radius_km": 10,
    # Dispatch engine per restaurant (spec §4.3). "greedy" = proximity batching
    # (default, safe). "ortools" = SLA-first VRP route optimizer (opt-in pilot).
    # Existing rows without this key read as "greedy" via .get() in the service.
    "dispatch_engine": "greedy",
    # Kitchen prep deadline tuning (minutes), read via .get() with these defaults.
    # handling = pickup/hand-off slack reserved for the rider at the restaurant;
    # batch_safety = margin so an order that later joins a batch (extra inter-stop
    # drive) still makes the SLA. Both subtracted from the drive budget — not hardcoded.
    "prep_handling_minutes": 5,
    "batch_safety_minutes": 5,
    # Greedy batching geometry (per-restaurant; read via .get() with these defaults).
    # proximity = how close two DROP-OFFS must be to share a rider trip; window =
    # readiness spread allowed within a batch; sla_buffer = minutes added per extra
    # stop. max_detour > 0 turns on "on-the-way" (corridor) batching: an order joins
    # when inserting its stop adds at most this many km of detour to the route (it is
    # then visited in nearest-first order). 0 = corridor off (pure proximity).
    "batch_proximity_km": 1.0,
    "batch_window_minutes": 10,
    # Per-extra-stop safety margin in the batching SLA gate. Kept at 0 so realistic
    # mid-range orders actually batch (a higher value reserves time and blocks
    # batching for orders more than a few km out); the 40-min customer SLA + the
    # predictive-breach alert remain the real safety net. Not exposed in the UI.
    "sla_buffer_per_order_minutes": 0,
    "batch_max_detour_km": 0,
    # Batching "hold window": seconds to defer a freshly-ready LONE order so a nearby
    # order can join its batch before a rider is committed. 0 = off (assign at once).
    # An order is never held if it already has a batch-mate, is priority, or is under
    # SLA pressure. Released by the periodic dispatch sweep once it matures.
    "batch_hold_seconds": 0,
    # Fallback cook time (minutes) for a dish with no prep_minutes set — used to estimate
    # an order's "start cooking by" time.
    "default_prep_minutes": 15,
    # Today's Special automation (marketing). When enabled, every opted-in customer
    # is sent the chosen APPROVED template ~lead_minutes before their predicted usual
    # order time (clamped to the UAE 9am-6pm window). Customers without a clear habit
    # get default_time. Driven by the cron-pinged POST /marketing/tick. See
    # app.marketing.todays_special.
    "todays_special": {
        "enabled": False,
        "template_id": None,
        "lead_minutes": 15,
        "default_time": "11:45",
    },
    # Abandoned-cart recovery (per-restaurant; read via .get() with these defaults).
    # cart_reminder_enabled toggles the one-time "you still have items" WhatsApp nudge.
    # cart_recovery_minutes = minutes of silence before that nudge fires. After
    # cart_expiry_minutes of silence the draft cart is auto-cleared. A customer who
    # returns while the cart still exists is asked Continue vs Start new (always on).
    "cart_reminder_enabled": True,
    "cart_recovery_minutes": 15,
    "cart_expiry_minutes": 60,
    # WhatsApp catalog ordering (SEPARATE flow). catalog_id is the Meta Commerce
    # catalog connected to this restaurant's WhatsApp number; when a customer sends a
    # cart from it, the catalog flow turns it into an order. Empty = not configured.
    "catalog_id": "",
    "catalog_ordering_enabled": True,
    # False until signup onboarding (menu upload + Meta sync) is finished.
    "onboarding_complete": False,
    # Resale of cancelled-after-cooking orders (spec §3). When the kitchen has
    # already started an order that then gets cancelled, the food is offered to the
    # NEXT customer as a fast, discounted delivery. All values manager-editable.
    "resale": {
        "enabled": True,
        "discount_type": "percent",   # percent | fixed
        "discount_value": 30,          # 30% off (or AED off if fixed)
        "max_age_minutes": 30,         # don't offer resale food older than this
    },
    # Loyalty program (per-restaurant, fully manager-editable; read via .get()).
    # Tiers (Phase 1) map RFM+Monetary cohorts to reward coupons; earning (Phase 2)
    # credits a % of food subtotal to the customer's wallet on delivery. NOTHING is
    # hardcoded — every threshold/rate below is editable from the Loyalty settings tab.
    "loyalty": {
        "enabled": False,
        # Phase 2 earning
        "earn_rate": 0.05,                 # fraction of subtotal -> wallet credit
        "earn_max_per_order_aed": 20.0,    # per-order cap (catering/abuse guard)
        "credit_ttl_days": 90,             # earned-credit expiry; 0 = never
        # Phase 1 tiers — thresholds the restaurant controls
        "tiers": {
            "gold": {"min_orders": 5, "min_spend_aed": 300, "max_recency_days": 30},
            "silver": {"min_orders": 3, "min_spend_aed": 120, "max_recency_days": 60},
            "bronze": {"min_orders": 2, "min_spend_aed": 0, "max_recency_days": 90},
        },
        # Perk = a coupon issued on tier entry (welcome) AND every N delivered orders.
        "tier_rewards": {
            "gold": {"discount_aed": 25, "every_n_orders": 5},
            "silver": {"discount_aed": 10, "every_n_orders": 6},
            "bronze": None,
        },
        "demotion_grace_days": 30,         # anti-thrash before dropping a tier
        "scope_includes_catalog": True,    # earn/tier on catalog orders too
    },
}


def catalog_mode_enabled(settings: dict | None) -> bool:
    """True only when catalogue ordering is BOTH switched on AND a Meta catalogue is
    connected (``catalog_id`` set). The flag alone is not enough: with no catalog_id
    there are no product cards to send, so the conversation must stay in text-menu
    mode. ``catalog_ordering_enabled`` now defaults to True, so this catalog_id guard
    is what keeps a freshly-created restaurant on the text menu until its catalogue is
    wired up (catalog_id comes from the environment / onboarding)."""
    s = settings or {}
    return bool(s.get("catalog_ordering_enabled") and (s.get("catalog_id") or "").strip())


class Restaurant(Base, TimestampMixin):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    settings: Mapped[dict] = mapped_column(JSONB, default=lambda: copy.deepcopy(DEFAULT_SETTINGS))


class Rider(Base, TimestampMixin):
    __tablename__ = "riders"
    __table_args__ = (UniqueConstraint("restaurant_id", "phone"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="available")
    # available | on_delivery | off_shift | deactivated
    # Rider-controlled duty flag (the in-app On duty / Off duty switch). Independent
    # of the operational `status` above: a rider can flip OFF mid-delivery and will
    # simply receive no NEW assignments once their current run completes (the dispatch
    # eligible set requires on_duty=True). True so every existing/new rider starts on.
    on_duty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    # Native rider app (Android) auth: the rider pairs ONCE with a short code sent
    # via WhatsApp; the app then stores `device_token` (long-lived bearer) and
    # streams background GPS. pairing_code is the one-time, expiring pairing code.
    device_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    pairing_code: Mapped[str | None] = mapped_column(String(12), index=True, nullable=True)
    pairing_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Expo push token (native app) — set by the app after it registers for
    # notifications, used to wake the rider when a delivery is assigned.
    push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Rolling delivery performance (Phase 4) — feeds dispatch scoring.
    performance: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {
            "on_time_pct": 100.0,
            "avg_delivery_min": 25,
            "total_deliveries": 0,
        },
    )
