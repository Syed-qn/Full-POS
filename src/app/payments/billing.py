"""Restaurant billing fee settings + order total composition helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.identity.models import Restaurant
    from app.ordering.models import Order

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_DEFAULTS = {
    "service_charge_pct": 0.0,
    "packaging_charge_aed": 0.0,
    "min_order_aed": 0.0,
}


def get_billing_settings(restaurant: "Restaurant") -> dict[str, float]:
    settings = restaurant.settings if isinstance(restaurant.settings, dict) else {}
    raw = settings.get("billing") if isinstance(settings.get("billing"), dict) else {}
    return {
        "service_charge_pct": float(raw.get("service_charge_pct", _DEFAULTS["service_charge_pct"])),
        "packaging_charge_aed": float(
            raw.get("packaging_charge_aed", _DEFAULTS["packaging_charge_aed"])
        ),
        "min_order_aed": float(raw.get("min_order_aed", _DEFAULTS["min_order_aed"])),
    }


def set_billing_settings(restaurant: "Restaurant", body: dict[str, Any]) -> dict[str, float]:
    settings = dict(restaurant.settings) if isinstance(restaurant.settings, dict) else {}
    billing = dict(settings.get("billing") or {})
    for key in ("service_charge_pct", "packaging_charge_aed", "min_order_aed"):
        if key in body and body[key] is not None:
            billing[key] = float(body[key])
    settings["billing"] = billing
    restaurant.settings = settings
    return get_billing_settings(restaurant)


def apply_billing_fees(order: "Order", restaurant: "Restaurant") -> None:
    """Derive service charge, packaging, and min-order surcharge from settings.

    Mutates order fee columns (does not recompute total — caller runs recompute).
    """
    cfg = get_billing_settings(restaurant)
    subtotal = Decimal(order.subtotal or _ZERO).quantize(_CENT)
    pct = Decimal(str(cfg["service_charge_pct"]))
    order.service_charge_aed = (
        (subtotal * pct / Decimal("100")).quantize(_CENT) if pct > 0 else _ZERO
    )
    pack = Decimal(str(cfg["packaging_charge_aed"])).quantize(_CENT)
    order.packaging_charge_aed = max(pack, _ZERO)

    min_order = Decimal(str(cfg["min_order_aed"])).quantize(_CENT)
    if min_order > 0 and subtotal < min_order:
        order.min_order_surcharge_aed = (min_order - subtotal).quantize(_CENT)
    else:
        order.min_order_surcharge_aed = _ZERO
