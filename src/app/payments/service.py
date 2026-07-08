import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.models import CreditNote, PaymentTransaction
from app.payments.port import PaymentPort

_GATEWAY_TENDERS = {"card", "apple_pay", "google_pay"}
_CREDIT_NOTE_LOCK_CLASS = 4_919_003
_logger = logging.getLogger(__name__)


class InsufficientPaymentError(Exception):
    pass


class PaymentFailedError(Exception):
    pass


class DuplicateChargeError(Exception):
    """A charge with the same order_id + amount_aed was already made within
    the duplicate-detection window (cashier double-tap protection). This is
    distinct from the idempotency-key mechanism in app.idempotency — that
    guards against network retries carrying an explicit key; this guards
    against two genuinely separate charge requests fired moments apart."""

    pass


async def detect_duplicate_charge(
    session: AsyncSession, *, restaurant_id: int, order_id: int, amount_aed: Decimal,
    window_seconds: int = 30,
) -> bool:
    """True if a non-failed PaymentTransaction with the same order_id + amount_aed
    was created within the last ``window_seconds``."""
    # PaymentTransaction.created_at (TimestampMixin) is TIMESTAMP WITHOUT TIME
    # ZONE — compare against a naive UTC datetime or asyncpg raises "can't
    # subtract offset-naive and offset-aware datetimes". DB convention here is
    # UTC-naive storage (see project conventions), so drop tzinfo after
    # computing the cutoff in UTC.
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).replace(tzinfo=None)
    existing = await session.scalar(
        select(PaymentTransaction.id)
        .where(
            PaymentTransaction.restaurant_id == restaurant_id,
            PaymentTransaction.order_id == order_id,
            PaymentTransaction.amount_aed == amount_aed,
            PaymentTransaction.status.in_(("pending", "succeeded")),
            PaymentTransaction.created_at >= cutoff,
        )
        .limit(1)
    )
    return existing is not None


async def charge_tender(
    session: AsyncSession, *, restaurant_id: int, order_id: int, tender_type: str,
    amount_aed: Decimal, tip_aed: Decimal, gateway: PaymentPort,
) -> PaymentTransaction:
    if await detect_duplicate_charge(
        session, restaurant_id=restaurant_id, order_id=order_id, amount_aed=amount_aed,
    ):
        raise DuplicateChargeError(
            f"duplicate charge detected for order {order_id}, amount {amount_aed}"
        )
    txn = PaymentTransaction(
        restaurant_id=restaurant_id, order_id=order_id, tender_type=tender_type,
        amount_aed=amount_aed, tip_aed=tip_aed, status="pending",
    )
    if tender_type in _GATEWAY_TENDERS:
        result = await gateway.charge(
            amount_aed=amount_aed + tip_aed, tender_type=tender_type, reference=f"order:{order_id}",
        )
        txn.provider = "stripe" if type(gateway).__name__ != "MockPaymentProcessor" else "mock"
        if not result.success:
            txn.status = "failed"
            session.add(txn)
            await session.flush()
            raise PaymentFailedError(result.error or "payment failed")
        txn.provider_charge_id = result.provider_charge_id
        txn.status = "succeeded"
    else:
        # cash / wallet — no external gateway call, settled immediately.
        txn.provider = tender_type
        txn.status = "succeeded"
    session.add(txn)
    await session.flush()
    return txn


async def total_paid(session: AsyncSession, *, order_id: int) -> Decimal:
    val = await session.scalar(
        select(func.coalesce(func.sum(PaymentTransaction.amount_aed - PaymentTransaction.refunded_amount_aed), Decimal("0.00")))
        .where(PaymentTransaction.order_id == order_id, PaymentTransaction.status.in_(("succeeded", "refunded")))
    )
    return Decimal(val)


async def refund_transaction(
    session: AsyncSession, *, transaction_id: int, restaurant_id: int, amount_aed: Decimal, gateway: PaymentPort,
) -> PaymentTransaction:
    txn = await session.get(PaymentTransaction, transaction_id)
    if txn is None or txn.restaurant_id != restaurant_id:
        raise ValueError(f"transaction {transaction_id} not found")
    remaining = txn.amount_aed - txn.refunded_amount_aed
    if amount_aed > remaining:
        raise InsufficientPaymentError(f"cannot refund {amount_aed}, only {remaining} available")

    if txn.tender_type in _GATEWAY_TENDERS and txn.provider_charge_id:
        result = await gateway.refund(provider_charge_id=txn.provider_charge_id, amount_aed=amount_aed)
        if not result.success:
            raise PaymentFailedError(result.error or "refund failed")

    txn.refunded_amount_aed += amount_aed
    txn.status = "refunded" if txn.refunded_amount_aed >= txn.amount_aed else "partially_refunded"
    await session.flush()
    return txn


async def _next_credit_note_seq(session: AsyncSession, restaurant_id: int) -> int:
    """Next per-tenant credit-note sequence = 1 + the highest numeric suffix
    currently in use. Same gap-proof approach as _next_order_seq in
    app.ordering.service — never a plain count() + 1."""
    prefix = f"CN-{restaurant_id}-"
    numbers = (
        await session.scalars(
            select(CreditNote.credit_note_number).where(CreditNote.restaurant_id == restaurant_id)
        )
    ).all()
    max_seq = 0
    for number in numbers:
        if number.startswith(prefix):
            suffix = number[len(prefix):]
            if suffix.isdigit():
                max_seq = max(max_seq, int(suffix))
    return max_seq + 1


async def issue_credit_note(
    session: AsyncSession, *, restaurant_id: int, order_id: int, transaction_id: int,
    amount_aed: Decimal, reason: str | None = None,
) -> CreditNote:
    """Issue a formal credit-note artifact, e.g. alongside/instead of a cash
    refund. Number allocation reuses the exact advisory-lock + max-suffix-scan
    + SAVEPOINT-retry pattern from create_draft_order (app.ordering.service).

    Guarded against over-issuance (double-spend of a refund): the referenced
    transaction must actually have been refunded, and the sum of all credit
    notes issued against it can never exceed its refunded_amount_aed."""
    from sqlalchemy import text

    txn = await session.get(PaymentTransaction, transaction_id)
    if txn is None or txn.restaurant_id != restaurant_id:
        raise PaymentFailedError(f"transaction {transaction_id} not found")
    if txn.status not in ("refunded", "partially_refunded"):
        raise PaymentFailedError(
            f"cannot issue a credit note against transaction {transaction_id}: "
            f"status is {txn.status!r}, expected 'refunded' or 'partially_refunded'"
        )

    already_issued = await session.scalar(
        select(func.coalesce(func.sum(CreditNote.amount_aed), Decimal("0.00")))
        .where(CreditNote.transaction_id == transaction_id)
    )
    already_issued = Decimal(already_issued)
    if already_issued + amount_aed > txn.refunded_amount_aed:
        raise PaymentFailedError(
            f"credit note amount {amount_aed} would push total issued for "
            f"transaction {transaction_id} to {already_issued + amount_aed}, "
            f"exceeding refunded amount {txn.refunded_amount_aed}"
        )

    try:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:c, :o)"),
            {"c": _CREDIT_NOTE_LOCK_CLASS, "o": restaurant_id},
        )
    except Exception:  # noqa: BLE001 — non-Postgres backend; proceed without the lock
        _logger.debug("advisory credit-note-number lock unavailable; proceeding unserialized")

    base_seq = await _next_credit_note_seq(session, restaurant_id)

    last_error: IntegrityError | None = None
    for attempt in range(5):
        credit_note_number = f"CN-{restaurant_id}-{base_seq + attempt:04d}"
        note = CreditNote(
            restaurant_id=restaurant_id,
            order_id=order_id,
            transaction_id=transaction_id,
            amount_aed=amount_aed,
            reason=reason,
            credit_note_number=credit_note_number,
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

    raise RuntimeError(
        f"could not allocate a unique credit note number for restaurant {restaurant_id}"
    ) from last_error


async def charge_deposit(
    session: AsyncSession, *, restaurant_id: int, order_id: int, amount_aed: Decimal,
    gateway: PaymentPort,
) -> PaymentTransaction:
    """Charge a partial deposit/advance payment on a (typically scheduled/pre-)
    order before it is fully prepared. Reuses charge_tender with a distinct
    tender_type so the transaction ledger records it as a deposit, then mirrors
    the running total onto Order.deposit_paid_aed."""
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError(f"order {order_id} not found")

    txn = await charge_tender(
        session, restaurant_id=restaurant_id, order_id=order_id, tender_type="deposit",
        amount_aed=amount_aed, tip_aed=Decimal("0.00"), gateway=gateway,
    )
    order.deposit_paid_aed = (order.deposit_paid_aed or Decimal("0.00")) + amount_aed
    await session.flush()
    return txn


async def enable_house_account(
    session: AsyncSession, *, restaurant_id: int, customer_id: int,
) -> "Customer":  # noqa: F821 — forward ref, imported lazily below
    """Turn on tab/run-a-tab billing for a VIP/corporate customer."""
    from app.ordering.models import Customer

    customer = await session.get(Customer, customer_id)
    if customer is None or customer.restaurant_id != restaurant_id:
        raise ValueError(f"customer {customer_id} not found")
    customer.house_account_enabled = True
    await session.flush()
    return customer


async def charge_to_house_account(
    session: AsyncSession, *, restaurant_id: int, customer_id: int, order_id: int,
    amount_aed: Decimal,
) -> Decimal:
    """Add an order's amount to the customer's house-account tab. Returns the
    new running balance. Raises ValueError if the account isn't enabled, or if
    the charge would push the balance above house_account_credit_limit_aed
    (null limit = unbounded).

    The balance mutation is a single atomic in-DB UPDATE ... SET balance =
    balance + :amt (not a Python-side read-modify-write) so two concurrent
    charges against the same customer can't lose an update.

    The credit-limit check reads the balance under SELECT ... FOR UPDATE so a
    second concurrent charge blocks until the first one's transaction commits
    (or rolls back), preventing two charges from both passing the limit check
    against the same stale balance."""
    from app.ordering.models import Customer

    customer = await session.scalar(
        select(Customer).where(Customer.id == customer_id).with_for_update()
    )
    if customer is None or customer.restaurant_id != restaurant_id:
        raise ValueError(f"customer {customer_id} not found")
    if not customer.house_account_enabled:
        raise ValueError(f"house account not enabled for customer {customer_id}")

    limit = customer.house_account_credit_limit_aed
    if limit is not None:
        current_balance = customer.house_account_balance_aed or Decimal("0.00")
        if current_balance + amount_aed > limit:
            raise ValueError(
                f"charge of {amount_aed} would push house account balance to "
                f"{current_balance + amount_aed}, exceeding credit limit {limit} "
                f"for customer {customer_id}"
            )

    new_balance = await session.scalar(
        update(Customer)
        .where(Customer.id == customer_id)
        .values(
            house_account_balance_aed=func.coalesce(Customer.house_account_balance_aed, Decimal("0.00"))
            + amount_aed
        )
        .returning(Customer.house_account_balance_aed)
    )
    await session.flush()
    session.expire(customer, ["house_account_balance_aed"])
    return new_balance


async def settle_house_account(
    session: AsyncSession, *, restaurant_id: int, customer_id: int, amount_aed: Decimal,
) -> Decimal:
    """Pay down the house-account tab. Floors at zero (never goes negative).

    Uses the same atomic in-DB UPDATE pattern as charge_to_house_account to
    avoid a lost-update race between concurrent settlements/charges."""
    from app.ordering.models import Customer

    customer = await session.get(Customer, customer_id)
    if customer is None or customer.restaurant_id != restaurant_id:
        raise ValueError(f"customer {customer_id} not found")

    new_balance = await session.scalar(
        update(Customer)
        .where(Customer.id == customer_id)
        .values(
            house_account_balance_aed=func.greatest(
                func.coalesce(Customer.house_account_balance_aed, Decimal("0.00")) - amount_aed,
                Decimal("0.00"),
            )
        )
        .returning(Customer.house_account_balance_aed)
    )
    await session.flush()
    session.expire(customer, ["house_account_balance_aed"])
    return new_balance
