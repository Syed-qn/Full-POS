from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=8)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class LoginIn(BaseModel):
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=1)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    lat: float
    lng: float
    settings: dict


class RiderIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=7, max_length=32)


class RiderPatch(BaseModel):
    """Partial rider update — change status, or edit name/phone profile fields."""

    status: Literal["available", "on_delivery", "off_shift", "deactivated"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=7, max_length=32)


class RiderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    status: str
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
    batch_expedite_radius_km: float | None = Field(default=None, gt=0, le=10)
    # Greedy batching geometry. max_detour_km = 0 turns corridor batching OFF.
    batch_proximity_km: float | None = Field(default=None, gt=0, le=10)
    batch_window_minutes: int | None = Field(default=None, ge=0, le=60)
    sla_buffer_per_order_minutes: int | None = Field(default=None, ge=0, le=30)
    batch_max_detour_km: float | None = Field(default=None, ge=0, le=10)
    # Batching hold window: seconds to defer a lone fresh order so a neighbour can
    # join its batch. 0 = off. Capped at 600s (10 min) to stay well under the SLA.
    batch_hold_seconds: int | None = Field(default=None, ge=0, le=600)
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
        if enabled and template_id is None:
            raise ValueError("select an approved template before enabling Today's Special")
        return {
            "enabled": enabled,
            "template_id": template_id,
            "lead_minutes": lead,
            "default_time": f"{h:02d}:{m:02d}",
        }

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
