"""Per-restaurant UAE tax / compliance settings helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

DEFAULT_VAT_RATE = Decimal("0.0500")
# UAE simplified vs full tax invoice heuristic threshold (B2C under this often simplified).
DEFAULT_SIMPLIFIED_THRESHOLD_AED = Decimal("10000.00")
DEFAULT_RETENTION_DAYS = 2555  # ~7 years


def tax_settings(restaurant_settings: dict | None) -> dict[str, Any]:
    s = restaurant_settings or {}
    mode = (s.get("tax_pricing_mode") or "exclusive").lower()
    if mode not in ("inclusive", "exclusive"):
        mode = "exclusive"
    rate = s.get("default_vat_rate")
    try:
        vat_rate = Decimal(str(rate if rate is not None else DEFAULT_VAT_RATE))
    except Exception:  # noqa: BLE001
        vat_rate = DEFAULT_VAT_RATE
    thr = s.get("simplified_invoice_threshold_aed")
    try:
        threshold = Decimal(str(thr if thr is not None else DEFAULT_SIMPLIFIED_THRESHOLD_AED))
    except Exception:  # noqa: BLE001
        threshold = DEFAULT_SIMPLIFIED_THRESHOLD_AED
    retention = int(s.get("data_retention_days") or DEFAULT_RETENTION_DAYS)
    return {
        "trn": (s.get("trn") or "").strip() or None,
        "legal_name": s.get("legal_name"),
        "legal_name_ar": s.get("legal_name_ar"),
        "tax_pricing_mode": mode,
        "default_vat_rate": vat_rate,
        "simplified_invoice_threshold_aed": threshold,
        "data_retention_days": max(30, retention),
        "buyer_trn_required_for_b2b": bool(s.get("buyer_trn_required_for_b2b", True)),
        "e_invoice_enabled": bool(s.get("e_invoice_enabled", False)),
        "asp_provider": (s.get("asp_provider") or "mock").lower(),
        "asp_api_key": s.get("asp_api_key"),
    }


def merge_tax_settings(restaurant, patch: dict[str, Any]) -> dict[str, Any]:
    settings = dict(restaurant.settings) if isinstance(restaurant.settings, dict) else {}
    allowed = {
        "trn",
        "legal_name",
        "legal_name_ar",
        "tax_pricing_mode",
        "default_vat_rate",
        "simplified_invoice_threshold_aed",
        "data_retention_days",
        "buyer_trn_required_for_b2b",
        "e_invoice_enabled",
        "asp_provider",
        "asp_api_key",
    }
    for k, v in patch.items():
        if k not in allowed:
            continue
        if v is None:
            settings.pop(k, None)
        else:
            settings[k] = v
    restaurant.settings = settings
    return tax_settings(settings)
