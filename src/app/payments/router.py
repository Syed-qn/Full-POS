from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.payments.billing import get_billing_settings, set_billing_settings
from app.payments.credentials import clear_credentials, get_credentials_status, set_credentials
from app.payments.factory import get_payment_port
from app.payments.models import PaymentTransaction
from app.payments.schemas import (
    BillingSettingsIn,
    ChargeIn,
    CreditNoteIn,
    CredentialsIn,
    DepositIn,
    DiscountIn,
    HouseAccountChargeIn,
    HouseAccountSettleIn,
    PayLaterIn,
    PaymentLinkCompleteIn,
    PaymentLinkIn,
    RefundIn,
    SettlementImportIn,
    WalletSessionIn,
)
from app.payments.service import (
    DuplicateChargeError,
    InsufficientPaymentError,
    PaymentFailedError,
    apply_order_discount,
    charge_deposit,
    charge_tender,
    charge_to_house_account,
    complete_payment_link,
    create_payment_link,
    enable_house_account,
    get_payment_link,
    import_settlement,
    issue_credit_note,
    list_order_transactions,
    list_payment_links,
    mark_pay_later,
    reconciliation_report,
    refund_transaction,
    settle_house_account,
    total_paid,
)
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])
customers_router = APIRouter(prefix="/api/v1/customers", tags=["payments"])
orders_router = APIRouter(prefix="/api/v1/orders", tags=["payments"])
public_router = APIRouter(prefix="/api/v1/public/pay", tags=["payments-public"])


def _txn_out(txn: PaymentTransaction, total: object | None = None) -> dict:
    body = {
        "id": txn.id,
        "order_id": txn.order_id,
        "status": txn.status,
        "provider": txn.provider,
        "tender_type": txn.tender_type,
        "amount_aed": str(txn.amount_aed),
        "tip_aed": str(txn.tip_aed),
        "channel": txn.channel,
        "reference_meta": txn.reference_meta,
        "wallet_session_id": txn.wallet_session_id,
        "provider_charge_id": txn.provider_charge_id,
        "refunded_amount_aed": str(txn.refunded_amount_aed),
    }
    if total is not None:
        body["order_total_paid_aed"] = str(total)
    return body


@router.post("/charge", status_code=status.HTTP_201_CREATED)
async def charge(
    body: ChargeIn,
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    gateway = get_payment_port(restaurant)
    meta = body.room_number or body.terminal_id
    try:
        txn = await charge_tender(
            session,
            restaurant_id=restaurant.id,
            order_id=body.order_id,
            tender_type=body.tender_type,
            amount_aed=body.amount_aed,
            tip_aed=body.tip_aed,
            gateway=gateway,
            channel=body.channel,
            reference_meta=meta,
            wallet_session_id=body.wallet_session_id,
        )
    except DuplicateChargeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    await session.commit()
    total = await total_paid(session, order_id=body.order_id)
    # On-premise orders (dine-in/takeaway/drive-thru) close on full payment —
    # this drops them from the open-bills list and frees their table. No-op for
    # delivery/online (they close when the rider marks delivered) and partials.
    from app.ordering.service import settle_on_premise_if_paid

    await settle_on_premise_if_paid(
        session, order_id=body.order_id, restaurant_id=restaurant.id, actor="cashier"
    )
    await session.commit()
    return _txn_out(txn, total)


@router.post("/wallet-session", status_code=status.HTTP_201_CREATED)
async def wallet_session(
    body: WalletSessionIn,
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    """Mint Apple Pay / Google Pay / Tap-to-Pay client session (PaymentIntent)."""
    if body.tender_type not in ("apple_pay", "google_pay", "tap_to_pay"):
        raise HTTPException(status_code=422, detail="tender_type must be apple_pay|google_pay|tap_to_pay")
    gateway = get_payment_port(restaurant)
    create = getattr(gateway, "create_wallet_session", None)
    if create is None:
        raise HTTPException(status_code=501, detail="wallet sessions not supported by gateway")
    result = await create(
        amount_aed=body.amount_aed,
        tender_type=body.tender_type,
        reference=f"order:{body.order_id}",
    )
    if result.get("error"):
        raise HTTPException(status_code=402, detail=result["error"])
    return result


@router.post("/{transaction_id}/refund")
async def refund(
    transaction_id: int,
    body: RefundIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    gateway = get_payment_port(restaurant)
    try:
        txn = await refund_transaction(
            session,
            transaction_id=transaction_id,
            restaurant_id=restaurant.id,
            amount_aed=body.amount_aed,
            gateway=gateway,
        )
    except InsufficientPaymentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": txn.id,
        "status": txn.status,
        "refunded_amount_aed": str(txn.refunded_amount_aed),
    }


@router.post("/{transaction_id}/credit-note", status_code=status.HTTP_201_CREATED)
async def create_credit_note(
    transaction_id: int,
    body: CreditNoteIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    txn = await session.get(PaymentTransaction, transaction_id)
    if txn is None or txn.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail=f"transaction {transaction_id} not found")

    try:
        note = await issue_credit_note(
            session,
            restaurant_id=restaurant.id,
            order_id=txn.order_id,
            transaction_id=txn.id,
            amount_aed=body.amount_aed,
            reason=body.reason,
        )
    except PaymentFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": note.id,
        "credit_note_number": note.credit_note_number,
        "order_id": note.order_id,
        "transaction_id": note.transaction_id,
        "amount_aed": str(note.amount_aed),
        "reason": note.reason,
        "issued_at": note.issued_at.isoformat(),
    }


@router.get("/credentials")
async def get_credentials(restaurant=Depends(current_restaurant)):
    return get_credentials_status(restaurant)


@router.put("/credentials")
async def put_credentials(
    body: CredentialsIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await set_credentials(
        session, restaurant=restaurant, provider=body.provider, secret_key=body.secret_key
    )
    await session.commit()
    return get_credentials_status(restaurant)


@router.delete("/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credentials(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await clear_credentials(session, restaurant=restaurant)
    await session.commit()


@router.get("/billing-settings")
async def billing_settings_get(restaurant=Depends(current_restaurant)):
    return get_billing_settings(restaurant)


@router.put("/billing-settings")
async def billing_settings_put(
    body: BillingSettingsIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    result = set_billing_settings(restaurant, body.model_dump(exclude_unset=True))
    session.add(restaurant)
    await session.commit()
    return result


@router.post("/links", status_code=status.HTTP_201_CREATED)
async def create_link(
    body: PaymentLinkIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        link = await create_payment_link(
            session,
            restaurant_id=restaurant.id,
            order_id=body.order_id,
            amount_aed=body.amount_aed,
            expires_hours=body.expires_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": link.id,
        "order_id": link.order_id,
        "token": link.token,
        "amount_aed": str(link.amount_aed),
        "status": link.status,
        "expires_at": link.expires_at.isoformat(),
        "url": f"/api/v1/public/pay/{link.token}",
    }


@router.get("/links")
async def list_links(
    status_filter: str | None = Query(default=None, alias="status"),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_payment_links(
        session, restaurant_id=restaurant.id, status=status_filter
    )
    return [
        {
            "id": r.id,
            "order_id": r.order_id,
            "token": r.token,
            "amount_aed": str(r.amount_aed),
            "status": r.status,
            "expires_at": r.expires_at.isoformat(),
            "url": f"/api/v1/public/pay/{r.token}",
        }
        for r in rows
    ]


@router.post("/reconciliation/import", status_code=status.HTTP_201_CREATED)
async def recon_import(
    body: SettlementImportIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    settlement = await import_settlement(
        session,
        restaurant_id=restaurant.id,
        provider=body.provider,
        provider_payout_id=body.provider_payout_id,
        amount_aed=body.amount_aed,
        settled_at=body.settled_at,
        lines=[ln.model_dump() for ln in body.lines],
        notes=body.notes,
    )
    await session.commit()
    return {
        "id": settlement.id,
        "status": settlement.status,
        "matched_txn_count": settlement.matched_txn_count,
        "provider_payout_id": settlement.provider_payout_id,
        "amount_aed": str(settlement.amount_aed),
    }


@router.get("/reconciliation/report")
async def recon_report(
    start: datetime | None = None,
    end: datetime | None = None,
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    return await reconciliation_report(
        session, restaurant_id=restaurant.id, start_date=start, end_date=end
    )


@public_router.get("/{token}")
async def public_link_get(token: str, session: AsyncSession = Depends(get_session)):
    link = await get_payment_link(session, token=token)
    if link is None:
        raise HTTPException(status_code=404, detail="payment link not found")
    return {
        "token": link.token,
        "order_id": link.order_id,
        "amount_aed": str(link.amount_aed),
        "status": link.status,
        "expires_at": link.expires_at.isoformat(),
    }


@public_router.post("/{token}/complete")
async def public_link_complete(
    token: str,
    body: PaymentLinkCompleteIn,
    session: AsyncSession = Depends(get_session),
):
    from app.identity.models import Restaurant

    link = await get_payment_link(session, token=token)
    if link is None:
        raise HTTPException(status_code=404, detail="payment link not found")
    restaurant = await session.get(Restaurant, link.restaurant_id)
    gateway = get_payment_port(restaurant)
    try:
        txn = await complete_payment_link(
            session, token=token, tender_type=body.tender_type, gateway=gateway
        )
    except DuplicateChargeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return _txn_out(txn)


@orders_router.post("/{order_id}/deposit", status_code=status.HTTP_201_CREATED)
async def deposit(
    order_id: int,
    body: DepositIn,
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    gateway = get_payment_port(restaurant)
    try:
        txn = await charge_deposit(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            amount_aed=body.amount_aed,
            gateway=gateway,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateChargeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    await session.commit()
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    return {
        "id": txn.id,
        "status": txn.status,
        "amount_aed": str(txn.amount_aed),
        "deposit_paid_aed": str(order.deposit_paid_aed),
    }


@orders_router.post("/{order_id}/pay-later", status_code=status.HTTP_201_CREATED)
async def pay_later(
    order_id: int,
    body: PayLaterIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    gateway = get_payment_port(restaurant)
    try:
        txn = await mark_pay_later(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            amount_aed=body.amount_aed,
            due_at=body.due_at,
            gateway=gateway,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return _txn_out(txn)


@orders_router.post("/{order_id}/discounts", status_code=status.HTTP_201_CREATED)
async def order_discount(
    order_id: int,
    body: DiscountIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    from app.staff.approvals import (
        InvalidManagerPinError,
        approve_with_pin,
        create_approval_request,
        discount_requires_pin,
        raise_suspicious,
    )

    # Discount approval trail always. PIN required when amount ≥ threshold
    # (dual-control for large comps); optional PIN always accepted when sent.
    approval_id = None
    needs_pin = discount_requires_pin(body.amount_aed)
    if body.manager_pin:
        try:
            approval = await approve_with_pin(
                session,
                restaurant=restaurant,
                action_type="discount",
                pin=body.manager_pin,
                order_id=order_id,
                amount_aed=body.amount_aed,
                reason=body.reason,
                requested_by_staff_id=body.staff_id,
                payload={"discount_type": body.discount_type},
            )
            approval_id = approval.id
        except InvalidManagerPinError as exc:
            await raise_suspicious(
                session,
                restaurant_id=restaurant.id,
                alert_type="failed_discount_pin",
                severity="high",
                staff_id=body.staff_id,
                detail={"order_id": order_id, "amount_aed": str(body.amount_aed)},
            )
            await session.commit()
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    elif needs_pin:
        raise HTTPException(
            status_code=403,
            detail="manager_pin required for discounts ≥ AED 20",
        )
    else:
        approval = await create_approval_request(
            session,
            restaurant_id=restaurant.id,
            action_type="discount",
            order_id=order_id,
            amount_aed=body.amount_aed,
            reason=body.reason,
            requested_by_staff_id=body.staff_id,
            status="approved",
            payload={"discount_type": body.discount_type, "via": "role_gate"},
        )
        approval_id = approval.id

    if body.amount_aed >= Decimal("100.00"):
        await raise_suspicious(
            session,
            restaurant_id=restaurant.id,
            alert_type="large_discount",
            severity="medium",
            staff_id=body.staff_id,
            detail={"order_id": order_id, "amount_aed": str(body.amount_aed)},
        )

    try:
        order = await apply_order_discount(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            discount_type=body.discount_type,
            amount_aed=body.amount_aed,
            reason=body.reason,
            staff_id=body.staff_id,
            approved_by="manager",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {
        "order_id": order.id,
        "total": str(order.total),
        "manager_discount_aed": str(order.manager_discount_aed),
        "staff_discount_aed": str(order.staff_discount_aed),
        "approval_id": approval_id,
    }


@orders_router.get("/{order_id}/payments")
async def order_payments(
    order_id: int,
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_order_transactions(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    paid = await total_paid(session, order_id=order_id)
    return {
        "order_id": order_id,
        "total_paid_aed": str(paid),
        "transactions": [_txn_out(t) for t in rows],
    }


@orders_router.post("/{order_id}/charge-to-house-account")
async def charge_order_to_house_account(
    order_id: int,
    body: HouseAccountChargeIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")

    try:
        balance = await charge_to_house_account(
            session,
            restaurant_id=restaurant.id,
            customer_id=order.customer_id,
            order_id=order_id,
            amount_aed=body.amount_aed,
        )
        # Also record a house_account tender so split/total_paid sees it.
        gateway = get_payment_port(restaurant)
        await charge_tender(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            tender_type="house_account",
            amount_aed=body.amount_aed,
            tip_aed=Decimal("0.00"),
            gateway=gateway,
            channel="till",
            reference_meta=f"customer:{order.customer_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DuplicateChargeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    await session.commit()
    return {"customer_id": order.customer_id, "house_account_balance_aed": str(balance)}


@customers_router.post("/{customer_id}/house-account/enable")
async def enable_house_account_endpoint(
    customer_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        customer = await enable_house_account(
            session, restaurant_id=restaurant.id, customer_id=customer_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "customer_id": customer.id,
        "house_account_enabled": customer.house_account_enabled,
    }


@customers_router.post("/{customer_id}/house-account/settle")
async def settle_house_account_endpoint(
    customer_id: int,
    body: HouseAccountSettleIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        balance = await settle_house_account(
            session,
            restaurant_id=restaurant.id,
            customer_id=customer_id,
            amount_aed=body.amount_aed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"customer_id": customer_id, "house_account_balance_aed": str(balance)}
