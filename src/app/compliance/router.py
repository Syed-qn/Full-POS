"""HTTP surface for Cat 13 UAE compliance."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.accountant_export import build_accountant_export
from app.compliance.einvoice import (
    einvoice_readiness,
    list_transmissions,
    transmit_order_einvoice,
)
from app.compliance.refund_notes import (
    build_refund_note_document,
    issue_refund_note,
    list_refund_notes,
)
from app.compliance.retention import list_retention_runs, run_data_retention
from app.compliance.tax_settings import merge_tax_settings, tax_settings
from app.db import get_session
from app.identity.deps import current_restaurant
from app.ordering.tax import build_structured_einvoice_payload, build_tax_invoice
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])


class TaxSettingsPatch(BaseModel):
    trn: str | None = Field(default=None, max_length=32)
    legal_name: str | None = None
    legal_name_ar: str | None = None
    tax_pricing_mode: str | None = None
    default_vat_rate: float | None = None
    simplified_invoice_threshold_aed: float | None = None
    data_retention_days: int | None = Field(default=None, ge=30, le=3650)
    buyer_trn_required_for_b2b: bool | None = None
    e_invoice_enabled: bool | None = None
    asp_provider: str | None = None
    asp_api_key: str | None = None


class RefundNoteIn(BaseModel):
    order_id: int
    amount_aed: Decimal = Field(gt=0)
    transaction_id: int | None = None
    reason: str | None = Field(default=None, max_length=256)
    vat_amount_aed: Decimal | None = None


class EInvoiceTransmitIn(BaseModel):
    order_id: int
    document_type: str | None = None
    buyer_trn: str | None = None


class RetentionIn(BaseModel):
    dry_run: bool = True
    retention_days: int | None = Field(default=None, ge=30, le=3650)


def _serialize_settings(cfg: dict) -> dict:
    out = dict(cfg)
    for k in ("default_vat_rate", "simplified_invoice_threshold_aed"):
        if k in out and out[k] is not None:
            out[k] = str(out[k])
    # never echo api key raw — only presence
    if "asp_api_key" in out:
        out["asp_api_key_set"] = bool(out.pop("asp_api_key"))
    return out


@router.get("/tax-settings")
async def get_tax_settings(
    restaurant=Depends(current_restaurant),
):
    return _serialize_settings(tax_settings(restaurant.settings))


@router.patch("/tax-settings")
async def patch_tax_settings(
    body: TaxSettingsPatch,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    patch = body.model_dump(exclude_unset=True)
    cfg = merge_tax_settings(restaurant, patch)
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(restaurant, "settings")
    await session.commit()
    await session.refresh(restaurant)
    return _serialize_settings(cfg)


@router.get("/invoices/{order_id}")
async def get_invoice(
    order_id: int,
    document_type: str | None = Query(default=None),
    buyer_trn: str | None = Query(default=None),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        inv = await build_tax_invoice(
            session,
            order_id=order_id,
            restaurant_id=restaurant.id,
            document_type=document_type,
            buyer_trn=buyer_trn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return inv


@router.get("/invoices/{order_id}/structured")
async def get_structured_invoice(
    order_id: int,
    document_type: str | None = Query(default=None),
    buyer_trn: str | None = Query(default=None),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        inv = await build_tax_invoice(
            session,
            order_id=order_id,
            restaurant_id=restaurant.id,
            document_type=document_type,
            buyer_trn=buyer_trn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_structured_einvoice_payload(inv)


@router.post("/refund-notes", status_code=status.HTTP_201_CREATED)
async def create_refund_note(
    body: RefundNoteIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        note = await issue_refund_note(
            session,
            restaurant_id=restaurant.id,
            order_id=body.order_id,
            amount_aed=body.amount_aed,
            transaction_id=body.transaction_id,
            reason=body.reason,
            vat_amount_aed=body.vat_amount_aed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": note.id,
        "refund_note_number": note.refund_note_number,
        "order_id": note.order_id,
        "amount_aed": str(note.amount_aed),
        "vat_amount_aed": str(note.vat_amount_aed),
        "reason": note.reason,
        "issued_at": note.issued_at.isoformat() if note.issued_at else None,
    }


@router.get("/refund-notes")
async def get_refund_notes(
    limit: int = Query(default=50, ge=1, le=100),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    notes = await list_refund_notes(session, restaurant_id=restaurant.id, limit=limit)
    return [
        {
            "id": n.id,
            "refund_note_number": n.refund_note_number,
            "order_id": n.order_id,
            "amount_aed": str(n.amount_aed),
            "vat_amount_aed": str(n.vat_amount_aed),
            "reason": n.reason,
            "issued_at": n.issued_at.isoformat() if n.issued_at else None,
        }
        for n in notes
    ]


@router.get("/refund-notes/{note_id}")
async def get_refund_note_doc(
    note_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await build_refund_note_document(
            session, restaurant_id=restaurant.id, note_id=note_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/e-invoice/readiness")
async def get_einvoice_readiness(restaurant=Depends(current_restaurant)):
    return einvoice_readiness(restaurant.settings)


@router.post("/e-invoice/transmit", status_code=status.HTTP_201_CREATED)
async def transmit_einvoice(
    body: EInvoiceTransmitIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await transmit_order_einvoice(
            session,
            restaurant=restaurant,
            order_id=body.order_id,
            document_type=body.document_type,
            buyer_trn=body.buyer_trn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": row.id,
        "order_id": row.order_id,
        "status": row.status,
        "asp_provider": row.asp_provider,
        "external_id": row.external_id,
        "document_type": row.document_type,
        "error": row.error,
        "transmitted_at": row.transmitted_at.isoformat() if row.transmitted_at else None,
    }


@router.get("/e-invoice/transmissions")
async def get_transmissions(
    limit: int = Query(default=50, ge=1, le=100),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_transmissions(session, restaurant_id=restaurant.id, limit=limit)
    return [
        {
            "id": r.id,
            "order_id": r.order_id,
            "status": r.status,
            "asp_provider": r.asp_provider,
            "external_id": r.external_id,
            "document_type": r.document_type,
            "error": r.error,
            "transmitted_at": r.transmitted_at.isoformat() if r.transmitted_at else None,
        }
        for r in rows
    ]


@router.post("/retention/run")
async def retention_run(
    body: RetentionIn | None = None,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    body = body or RetentionIn()
    run = await run_data_retention(
        session,
        restaurant=restaurant,
        dry_run=body.dry_run,
        retention_days=body.retention_days,
    )
    await session.commit()
    return {
        "id": run.id,
        "status": run.status,
        "retention_days": run.retention_days,
        "purged_counts": run.purged_counts,
        "notes": run.notes,
    }


@router.get("/retention/runs")
async def retention_runs(
    limit: int = Query(default=20, ge=1, le=100),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    runs = await list_retention_runs(session, restaurant_id=restaurant.id, limit=limit)
    return [
        {
            "id": r.id,
            "status": r.status,
            "retention_days": r.retention_days,
            "purged_counts": r.purged_counts,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in runs
    ]


@router.get("/accountant-export")
async def accountant_export(
    start_date: date = Query(...),
    end_date: date = Query(...),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    return await build_accountant_export(
        session,
        restaurant=restaurant,
        start_date=start_date,
        end_date=end_date,
        format=format,
    )
