from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_email(v: str) -> str:
    v = (v or "").strip().lower()
    if "@" not in v or "." not in v.split("@")[-1]:
        raise ValueError("enter a valid email address")
    return v


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8)
    # Optional: the real WhatsApp number is set when the restaurant connects Meta,
    # so the signup form never asks for it. Accepted here only for seeding/tests.
    phone: str | None = Field(default=None, max_length=32)
    # Optional at signup — location is pinned during onboarding. Defaulted so the
    # signup form doesn't need to ask for coordinates.
    lat: float = Field(default=0.0, ge=-90, le=90)
    lng: float = Field(default=0.0, ge=-180, le=180)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    phone: str | None = None  # WhatsApp number — set on Meta connect, null until then
    lat: float
    lng: float
    settings: dict


class OnboardingStatusOut(BaseModel):
    complete: bool
    has_location: bool
    has_menu: bool
    has_catalog_id: bool
    catalog_synced: bool
    has_meta: bool = False


class MetaConfigIn(BaseModel):
    """Onboarding page → save this restaurant's Meta/WhatsApp connection."""

    wa_phone_number_id: str | None = Field(default=None, max_length=64)
    wa_business_account_id: str | None = Field(default=None, max_length=64)
    wa_access_token: str | None = Field(default=None, max_length=1024)
    catalog_id: str | None = Field(default=None, max_length=64)


class MetaConfigOut(BaseModel):
    """Never returns the access token — only whether one is set."""

    wa_phone_number_id: str
    wa_business_account_id: str
    wa_access_token_set: bool
    catalog_id: str
    connected: bool


class MetaEmbedConfigOut(BaseModel):
    """Public-to-the-manager config the frontend needs to launch the ES popup."""

    enabled: bool
    app_id: str
    config_id: str
    graph_version: str


class MetaConnectIn(BaseModel):
    """Embedded Signup popup result → exchange the code, store per-restaurant creds."""

    code: str = Field(min_length=1, max_length=2048)
    phone_number_id: str = Field(min_length=1, max_length=64)
    waba_id: str = Field(min_length=1, max_length=64)


class RiderIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=7, max_length=32)


class RiderPatch(BaseModel):
    """Partial rider update — change status/duty, or edit name/phone profile fields."""

    status: Literal["available", "on_delivery", "off_shift", "deactivated"] | None = None
    # Shared On duty / Off duty flag (manager side of the same switch the rider has
    # in their app). One control, both sides.
    on_duty: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=7, max_length=32)


class RiderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    status: str
    # Rider's own On duty / Off duty switch (native app). Off duty = receives no new
    # assignments (keeps any active run). Surfaced here so the OPS rider list shows it.
    on_duty: bool = True
    # Delivery tallies (default 0 so create/update responses, which don't compute
    # them, stay valid). Populated by list_riders: 08:00→08:00 shift + lifetime.
    delivered_24h: int = 0
    delivered_lifetime: int = 0
    # Latest known position (most recent WhatsApp location ping). None until the
    # rider has ever shared a location. Populated by list_riders only.
    last_lat: float | None = None
    last_lng: float | None = None
    last_location_at: datetime | None = None


class RiderLocationOut(BaseModel):
    """A rider's most recent location ping — for the dashboard live-tracking map."""

    model_config = ConfigDict(from_attributes=True)

    lat: float
    lng: float
    ts: datetime


class SettingsPatch(BaseModel):
    max_orders_per_batch: int | None = Field(default=None, ge=1, le=6)
    max_items_per_order: int | None = Field(default=None, ge=1, le=100)
    # Single-line quantity above which the bot escalates to a human (anomaly guard).
    max_item_qty: int | None = Field(default=None, ge=1, le=100000)
    delivery_fee_tiers: list[dict] | None = None
    open_hours: dict | None = None
    # Dispatch engine + kitchen-timing tunables (per-restaurant; defaults in
    # DEFAULT_SETTINGS). All optional so a PATCH only touches what it sends.
    dispatch_engine: Literal["greedy", "ortools"] | None = None
    prep_handling_minutes: int | None = Field(default=None, ge=0, le=30)
    batch_safety_minutes: int | None = Field(default=None, ge=0, le=30)
    default_prep_minutes: int | None = Field(default=None, ge=1, le=180)
    # Minutes before prep_deadline when a preparing order enters the dispatch pool.
    prep_dispatch_lead_min: int | None = Field(default=None, ge=1, le=30)
    batch_expedite_radius_km: float | None = Field(default=None, gt=0, le=10)
    # Greedy batching geometry. max_detour_km = 0 turns corridor batching OFF.
    batch_proximity_km: float | None = Field(default=None, gt=0, le=10)
    batch_window_minutes: int | None = Field(default=None, ge=0, le=60)
    sla_buffer_per_order_minutes: int | None = Field(default=None, ge=0, le=30)
    batch_max_detour_km: float | None = Field(default=None, ge=0, le=10)
    # Batching hold window: seconds to defer a lone fresh order so a neighbour can
    # join its batch. 0 = off. Capped at 600s (10 min) to stay well under the SLA.
    batch_hold_seconds: int | None = Field(default=None, ge=0, le=600)
    # Manual delivery zones for batching (spec §5.3).
    delivery_zones: list[dict] | None = None
    # Abandoned-cart recovery. reminder toggles the nudge; recovery = minutes quiet
    # before the nudge; expiry = minutes quiet before the draft cart is auto-cleared.
    cart_reminder_enabled: bool | None = None
    cart_recovery_minutes: int | None = Field(default=None, ge=1, le=1440)
    cart_expiry_minutes: int | None = Field(default=None, ge=1, le=1440)
    # WhatsApp catalog ordering (separate flow).
    catalog_id: str | None = Field(default=None, max_length=64)
    catalog_ordering_enabled: bool | None = None
    # Today's Special automation (marketing). Sent as a whole object by the UI.
    todays_special: dict | None = None
    # Loyalty program config — sent as a whole object by the Loyalty settings tab.
    # Every value here is restaurant-editable; defaults live in DEFAULT_SETTINGS.
    loyalty: dict | None = None
    # Resale config (cancelled-after-cooking → fast discounted offer to next customer).
    resale: dict | None = None

    @field_validator("resale")
    @classmethod
    def _validate_resale(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("resale must be an object")
        if "enabled" in v and not isinstance(v["enabled"], bool):
            raise ValueError("resale.enabled must be a boolean")
        if "discount_type" in v and v["discount_type"] not in ("percent", "fixed"):
            raise ValueError("resale.discount_type must be 'percent' or 'fixed'")
        for k in ("discount_value", "max_age_minutes"):
            if k in v and v[k] is not None:
                if not isinstance(v[k], (int, float)) or v[k] < 0:
                    raise ValueError(f"resale.{k} must be >= 0")
        if v.get("discount_type") == "percent" and v.get("discount_value", 0) > 100:
            raise ValueError("resale percent discount cannot exceed 100")
        return v

    @field_validator("delivery_zones")
    @classmethod
    def _validate_delivery_zones(cls, v: list[dict] | None) -> list[dict] | None:
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("delivery_zones must be a list")
        for zone in v:
            if not isinstance(zone, dict):
                raise ValueError("each delivery zone must be an object")
            for key in ("name", "center_lat", "center_lng", "radius_km"):
                if key not in zone:
                    raise ValueError(f"delivery zone missing {key}")
            if not isinstance(zone["name"], str) or not zone["name"].strip():
                raise ValueError("delivery zone name must be a non-empty string")
            for coord in ("center_lat", "center_lng", "radius_km"):
                if not isinstance(zone[coord], (int, float)):
                    raise ValueError(f"delivery zone {coord} must be numeric")
            if zone["radius_km"] <= 0 or zone["radius_km"] > 10:
                raise ValueError("delivery zone radius_km must be between 0 and 10")
        return v

    @field_validator("loyalty")
    @classmethod
    def _validate_loyalty(cls, v: dict | None) -> dict | None:
        """Validate the loyalty config the UI sends. All numbers are non-negative;
        earn_rate is a 0..1 fraction; tiers/rewards are objects keyed by tier name.
        This is what lets a restaurant edit thresholds/discounts without a deploy."""
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("loyalty must be an object")
        if "enabled" in v and not isinstance(v["enabled"], bool):
            raise ValueError("loyalty.enabled must be a boolean")
        if "earn_rate" in v:
            r = v["earn_rate"]
            if not isinstance(r, (int, float)) or not (0 <= r <= 1):
                raise ValueError("loyalty.earn_rate must be a fraction between 0 and 1")
        for num_key in ("earn_max_per_order_aed", "credit_ttl_days", "demotion_grace_days"):
            if num_key in v and v[num_key] is not None:
                if not isinstance(v[num_key], (int, float)) or v[num_key] < 0:
                    raise ValueError(f"loyalty.{num_key} must be >= 0")
        if "scope_includes_catalog" in v and not isinstance(v["scope_includes_catalog"], bool):
            raise ValueError("loyalty.scope_includes_catalog must be a boolean")
        tiers = v.get("tiers")
        if tiers is not None:
            if not isinstance(tiers, dict):
                raise ValueError("loyalty.tiers must be an object")
            for name, tcfg in tiers.items():
                if name not in ("gold", "silver", "bronze"):
                    raise ValueError(f"unknown loyalty tier {name!r}")
                if not isinstance(tcfg, dict):
                    raise ValueError(f"loyalty.tiers.{name} must be an object")
                for k in ("min_orders", "min_spend_aed", "max_recency_days"):
                    if k in tcfg and tcfg[k] is not None:
                        if not isinstance(tcfg[k], (int, float)) or tcfg[k] < 0:
                            raise ValueError(f"loyalty.tiers.{name}.{k} must be >= 0")
        rewards = v.get("tier_rewards")
        if rewards is not None:
            if not isinstance(rewards, dict):
                raise ValueError("loyalty.tier_rewards must be an object")
            for name, rcfg in rewards.items():
                if name not in ("gold", "silver", "bronze"):
                    raise ValueError(f"unknown loyalty tier reward {name!r}")
                if rcfg is None:
                    continue
                if not isinstance(rcfg, dict):
                    raise ValueError(f"loyalty.tier_rewards.{name} must be an object or null")
                for k in ("discount_aed", "every_n_orders"):
                    if k in rcfg and rcfg[k] is not None:
                        if not isinstance(rcfg[k], (int, float)) or rcfg[k] < 0:
                            raise ValueError(f"loyalty.tier_rewards.{name}.{k} must be >= 0")
        return v

    @field_validator("todays_special")
    @classmethod
    def _validate_todays_special(cls, v: dict | None) -> dict | None:
        """Validate the auto-special config: ``{enabled: bool, template_id: int|null,
        lead_minutes: 0..120, default_time: "HH:MM"}``. Keeps the cron-driven
        sender from reading a broken config."""
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("todays_special must be an object")
        enabled = v.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("todays_special.enabled must be a boolean")
        template_id = v.get("template_id")
        if template_id is not None and not isinstance(template_id, int):
            raise ValueError("todays_special.template_id must be an integer or null")
        fallback_template_id = v.get("fallback_template_id")
        if fallback_template_id is not None and not isinstance(fallback_template_id, int):
            raise ValueError("todays_special.fallback_template_id must be an integer or null")
        lead = v.get("lead_minutes", 15)
        if not isinstance(lead, int) or not (0 <= lead <= 120):
            raise ValueError("todays_special.lead_minutes must be 0..120")
        default_time = v.get("default_time", "11:45")
        try:
            hh, mm = str(default_time).split(":")
            h, m = int(hh), int(mm)
        except (ValueError, AttributeError) as exc:
            raise ValueError("todays_special.default_time must be 'HH:MM'") from exc
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("todays_special.default_time must be valid 24h 'HH:MM'")
        if enabled and template_id is None and fallback_template_id is None:
            raise ValueError(
                "select a primary or fallback template before enabling Today's Special"
            )
        out = {
            "enabled": enabled,
            "template_id": template_id,
            "fallback_template_id": fallback_template_id,
            "lead_minutes": lead,
            "default_time": f"{h:02d}:{m:02d}",
        }
        for key in ("window_start", "window_end"):
            if key in v:
                out[key] = v[key]
        return out

    @field_validator("open_hours")
    @classmethod
    def _validate_open_hours(cls, v: dict | None) -> dict | None:
        """Opening hours: ``{"tz": str, "days": {"0".."6": ["HH:MM","HH:MM"]}}``.

        0=Mon .. 6=Sun. An empty/absent ``days`` map = always open. Each present
        day needs valid 24h times with close strictly after open (no cross-midnight).
        Mirrors app.conversation.hours so what the manager saves is what the bot
        reads — fully dynamic, no hardcoded timings.
        """
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("open_hours must be an object")
        tz = v.get("tz")
        if tz is not None and not isinstance(tz, str):
            raise ValueError("open_hours.tz must be a string")
        days = v.get("days") or {}
        if not isinstance(days, dict):
            raise ValueError("open_hours.days must be an object keyed by weekday")
        for key, window in days.items():
            if str(key) not in {"0", "1", "2", "3", "4", "5", "6"}:
                raise ValueError("day keys must be '0'..'6' (0=Mon)")
            if not (isinstance(window, (list, tuple)) and len(window) == 2):
                raise ValueError("each day must be a [open, close] pair")
            mins = []
            for t in window:
                try:
                    hh, mm = str(t).split(":")
                    h, m = int(hh), int(mm)
                except (ValueError, AttributeError) as exc:
                    raise ValueError("times must be 'HH:MM'") from exc
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError("times must be valid 24h 'HH:MM'")
                mins.append(h * 60 + m)
            if mins[1] <= mins[0]:
                raise ValueError("close time must be after open time")
        return v

    @field_validator("delivery_fee_tiers")
    @classmethod
    def _validate_tiers(cls, v: list[dict] | None) -> list[dict] | None:
        """Each tier needs a positive ascending ``max_km`` and a non-negative
        ``fee_aed`` — so the dynamic fee/radius config can't be saved broken."""
        if v is None:
            return v
        if not v:
            raise ValueError("delivery_fee_tiers must have at least one tier")
        prev_km = 0.0
        for tier in v:
            if not isinstance(tier, dict) or "max_km" not in tier or "fee_aed" not in tier:
                raise ValueError("each tier needs 'max_km' and 'fee_aed'")
            try:
                km = float(tier["max_km"])
                fee = float(tier["fee_aed"])
            except (TypeError, ValueError) as exc:
                raise ValueError("max_km and fee_aed must be numbers") from exc
            if km <= prev_km:
                raise ValueError("tiers must be ascending with positive max_km")
            if fee < 0:
                raise ValueError("fee_aed must be >= 0")
            prev_km = km
        return v


class ProfilePatch(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
