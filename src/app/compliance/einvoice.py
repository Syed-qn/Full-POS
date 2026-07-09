"""E-invoicing ASP port + mock UAE MoF transmission readiness."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.compliance.models import EInvoiceTransmission
from app.compliance.tax_settings import tax_settings
from app.ordering.tax import build_structured_einvoice_payload, build_tax_invoice


class EInvoiceASPPort(Protocol):
    async def transmit(self, payload: dict, *, api_key: str | None = None) -> dict:
        """Send structured invoice to ASP; return {success, external_id, raw}."""
        ...


class MockEInvoiceASP:
    """Development/test ASP — accepts any payload and returns a fake UID."""

    async def transmit(self, payload: dict, *, api_key: str | None = None) -> dict:
        uid = f"MOCK-AE-{uuid.uuid4().hex[:16].upper()}"
        return {
            "success": True,
            "external_id": uid,
            "raw": {
                "status": "accepted",
                "uuid": uid,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "profile": payload.get("profile"),
                "api_key_present": bool(api_key),
            },
        }


def get_asp(provider: str = "mock") -> EInvoiceASPPort:
    # Real ASP adapters (ClearTax, Pagero, etc.) plug in here when credentials exist.
    return MockEInvoiceASP()


async def transmit_order_einvoice(
    session: AsyncSession,
    *,
    restaurant,
    order_id: int,
    document_type: str | None = None,
    buyer_trn: str | None = None,
) -> EInvoiceTransmission:
    invoice = await build_tax_invoice(
        session,
        order_id=order_id,
        restaurant_id=restaurant.id,
        document_type=document_type,
        buyer_trn=buyer_trn,
    )
    structured = build_structured_einvoice_payload(invoice)
    cfg = tax_settings(restaurant.settings)
    provider_name = cfg.get("asp_provider") or "mock"
    asp = get_asp(provider_name)

    row = EInvoiceTransmission(
        restaurant_id=restaurant.id,
        order_id=order_id,
        document_type=invoice.get("document_type") or "tax_invoice",
        status="queued",
        asp_provider=provider_name,
        payload=structured,
    )
    session.add(row)
    await session.flush()

    try:
        result = await asp.transmit(structured, api_key=cfg.get("asp_api_key"))
        if result.get("success"):
            row.status = "accepted"
            row.external_id = result.get("external_id")
            row.response = result.get("raw") or {}
            row.transmitted_at = datetime.now(timezone.utc)
        else:
            row.status = "rejected"
            row.error = str(result.get("error") or "rejected")
            row.response = result.get("raw") or {}
    except Exception as exc:  # noqa: BLE001
        row.status = "failed"
        row.error = str(exc)[:1000]

    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant.id,
        actor="system",
        entity="e_invoice",
        entity_id=str(row.id),
        action=f"transmit_{row.status}",
        after={"order_id": order_id, "external_id": row.external_id},
    )
    return row


async def list_transmissions(
    session: AsyncSession, *, restaurant_id: int, limit: int = 50
) -> list[EInvoiceTransmission]:
    return list(
        (
            await session.scalars(
                select(EInvoiceTransmission)
                .where(EInvoiceTransmission.restaurant_id == restaurant_id)
                .order_by(EInvoiceTransmission.id.desc())
                .limit(min(max(limit, 1), 100))
            )
        ).all()
    )


def einvoice_readiness(restaurant_settings: dict | None) -> dict:
    cfg = tax_settings(restaurant_settings)
    missing = []
    if not cfg.get("trn"):
        missing.append("trn")
    if not cfg.get("legal_name") and not cfg.get("legal_name_ar"):
        missing.append("legal_name")
    ready = len(missing) == 0
    return {
        "ready": ready,
        "e_invoice_enabled": cfg["e_invoice_enabled"],
        "asp_provider": cfg["asp_provider"],
        "asp_credentials_configured": bool(cfg.get("asp_api_key"))
        or cfg["asp_provider"] == "mock",
        "structured_profile": "PINT-AE-JSON-v1",
        "missing_fields": missing,
        "notes": (
            "Mock ASP accepts transmissions without live MoF credentials. "
            "Set asp_provider + asp_api_key when an accredited provider is contracted."
        ),
    }
