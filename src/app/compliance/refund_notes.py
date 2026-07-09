"""Refund note document issuance (UAE compliance)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.models import RefundNote
from app.ordering.receipt_i18n import invoice_labels
from app.payments.models import PaymentTransaction

_logger = logging.getLogger(__name__)
_REF_LOCK = 4_919_013


async def _next_seq(session: AsyncSession, restaurant_id: int) -> int:
    rows = (
        await session.scalars(
            select(RefundNote.refund_note_number).where(
                RefundNote.restaurant_id == restaurant_id
            )
        )
    ).all()
    best = 0
    for num in rows:
        try:
            best = max(best, int(str(num).rsplit("-", 1)[-1]))
        except ValueError:
            continue
    return best + 1


async def issue_refund_note(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    amount_aed: Decimal,
    transaction_id: int | None = None,
    reason: str | None = None,
    vat_amount_aed: Decimal | None = None,
) -> RefundNote:
    if transaction_id is not None:
        txn = await session.get(PaymentTransaction, transaction_id)
        if txn is None or txn.restaurant_id != restaurant_id:
            raise ValueError("transaction not found")
        if txn.refunded_amount_aed <= 0 and txn.status not in (
            "refunded",
            "partially_refunded",
        ):
            raise ValueError("transaction has not been refunded")

    try:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:c, :o)"),
            {"c": _REF_LOCK, "o": restaurant_id},
        )
    except Exception:  # noqa: BLE001
        _logger.debug("advisory refund-note lock unavailable")

    base = await _next_seq(session, restaurant_id)
    vat = vat_amount_aed
    if vat is None:
        vat = (amount_aed * Decimal("0.05") / Decimal("1.05")).quantize(Decimal("0.01"))

    last_error: IntegrityError | None = None
    for attempt in range(5):
        number = f"RN-{restaurant_id}-{base + attempt:04d}"
        note = RefundNote(
            restaurant_id=restaurant_id,
            order_id=order_id,
            transaction_id=transaction_id,
            amount_aed=amount_aed,
            vat_amount_aed=vat,
            reason=reason,
            refund_note_number=number,
            issued_at=datetime.now(timezone.utc),
        )
        session.add(note)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as exc:
            if note in session:
                session.expunge(note)
            last_error = exc
            continue
        return note
    raise RuntimeError("could not allocate refund note number") from last_error


async def build_refund_note_document(
    session: AsyncSession, *, restaurant_id: int, note_id: int
) -> dict:
    from app.identity.models import Restaurant
    from app.ordering.models import Order
    from app.compliance.tax_settings import tax_settings

    note = await session.get(RefundNote, note_id)
    if note is None or note.restaurant_id != restaurant_id:
        raise ValueError("refund note not found")
    restaurant = await session.get(Restaurant, restaurant_id)
    order = await session.get(Order, note.order_id)
    cfg = tax_settings(restaurant.settings if restaurant else None)
    labels = invoice_labels("refund_note")
    return {
        "document_type": "refund_note",
        "refund_note_number": note.refund_note_number,
        "order_number": order.order_number if order else None,
        "amount_aed": str(note.amount_aed),
        "vat_amount_aed": str(note.vat_amount_aed),
        "reason": note.reason,
        "issued_at": note.issued_at.isoformat() if note.issued_at else None,
        "trn": cfg.get("trn"),
        "restaurant_name": restaurant.name if restaurant else "",
        "legal_name_ar": cfg.get("legal_name_ar"),
        "labels": labels,
        "labels_ar": labels["ar"],
        "labels_en": labels["en"],
    }


async def list_refund_notes(
    session: AsyncSession, *, restaurant_id: int, limit: int = 50
) -> list[RefundNote]:
    return list(
        (
            await session.scalars(
                select(RefundNote)
                .where(RefundNote.restaurant_id == restaurant_id)
                .order_by(RefundNote.id.desc())
                .limit(min(max(limit, 1), 100))
            )
        ).all()
    )
