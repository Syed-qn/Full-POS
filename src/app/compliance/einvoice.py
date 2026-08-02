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


class EInvoiceDisabledError(RuntimeError):
    """Transmission attempted while the restaurant has e-invoicing switched off."""


class UnknownASPError(RuntimeError):
    """No adapter exists for the configured e-invoicing provider."""


# Real ASP adapters (ClearTax, Pagero, etc.) register here when they are written.
# Only "mock" exists today, and it files nothing with the FTA.
_ASP_REGISTRY: dict[str, type] = {"mock": MockEInvoiceASP}

#: Providers whose transmissions are real legal filings. Empty until one is built.
LIVE_ASP_PROVIDERS: frozenset[str] = frozenset()


def get_asp(provider: str = "mock") -> EInvoiceASPPort:
    """Resolve the adapter for `provider`, or refuse.

    This used to take the provider name and return MockEInvoiceASP regardless.
    The failure mode was silent and expensive: set asp_provider to a real ASP
    the day one is contracted, and every transmission would still go to the
    mock while the row recorded that provider's name, status "accepted", and a
    fabricated MOCK-AE reference. Nothing filed, everything looking filed.
    An unknown provider is now a refusal, not a fake success.
    """
    key = (provider or "mock").strip().lower()
    impl = _ASP_REGISTRY.get(key)
    if impl is None:
        raise UnknownASPError(
            f"No e-invoicing adapter is built for provider '{provider}'. "
            f"Available: {', '.join(sorted(_ASP_REGISTRY))}. "
            "Nothing was transmitted."
        )
    return impl()


async def transmit_order_einvoice(
    session: AsyncSession,
    *,
    restaurant,
    order_id: int,
    document_type: str | None = None,
    buyer_trn: str | None = None,
) -> EInvoiceTransmission:
    cfg = tax_settings(restaurant.settings)
    # The switch on Tax profile was read in exactly one place — the readiness
    # panel — and echoed back for display. Nothing checked it here, so ticking or
    # unticking it changed nothing about what this endpoint did. Harmless against
    # the mock provider; once an accredited ASP is contracted a transmission is a
    # legal filing to the FTA, and an off switch that does not switch anything off
    # is the kind of control someone relies on during an incident.
    if not cfg.get("e_invoice_enabled"):
        raise EInvoiceDisabledError(
            "E-invoicing is switched off for this restaurant. "
            "Enable it on the Tax profile tab before transmitting."
        )

    # Resolve the route before building anything. If no adapter exists for the
    # configured provider there is nowhere to send, and the caller should hear
    # that rather than a complaint about the order.
    provider_name = cfg.get("asp_provider") or "mock"
    asp = get_asp(provider_name)

    invoice = await build_tax_invoice(
        session,
        order_id=order_id,
        restaurant_id=restaurant.id,
        document_type=document_type,
        buyer_trn=buyer_trn,
    )
    structured = build_structured_einvoice_payload(invoice)

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
    """What is stopping this restaurant from filing, in words a manager reads.

    The machine-readable fields (`ready`, `missing_fields`) are kept for callers
    that already use them. `blockers` and `summary` are the same facts written
    as sentences, because "Ready: no / Missing: trn, legal_name" is a debug dump,
    not an instruction.
    """
    cfg = tax_settings(restaurant_settings)
    provider = cfg["asp_provider"]
    enabled = cfg["e_invoice_enabled"]

    missing: list[str] = []
    blockers: list[str] = []
    if not cfg.get("trn"):
        missing.append("trn")
        blockers.append("Add your TRN on the Tax profile tab.")
    if not cfg.get("legal_name") and not cfg.get("legal_name_ar"):
        missing.append("legal_name")
        blockers.append("Add your registered legal name on the Tax profile tab.")
    if not enabled:
        blockers.append("Switch e-invoicing on under Tax profile.")
    if provider not in _ASP_REGISTRY:
        blockers.append(
            f"No adapter is built for provider '{provider}', so nothing can be sent."
        )

    ready = len(missing) == 0
    is_live = provider in LIVE_ASP_PROVIDERS

    if blockers:
        summary = "Not ready to send yet."
    elif is_live:
        summary = f"Ready. Invoices are filed through {provider}."
    else:
        summary = (
            "Ready to run, but this is the test provider: transmissions are "
            "recorded here and nothing reaches the Federal Tax Authority."
        )

    return {
        "ready": ready,
        "e_invoice_enabled": enabled,
        "asp_provider": provider,
        "asp_credentials_configured": bool(cfg.get("asp_api_key")) or provider == "mock",
        "structured_profile": "PINT-AE-JSON-v1",
        "missing_fields": missing,
        "is_live": is_live,
        "blockers": blockers,
        "summary": summary,
        "notes": (
            "Mock ASP accepts transmissions without live MoF credentials. "
            "Set asp_provider + asp_api_key when an accredited provider is contracted."
        ),
    }
