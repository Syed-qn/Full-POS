"""Partner integration API.

Two surfaces:
  * ``/api/v1/api-keys`` — manager-authed (JWT) key management (create/list/revoke).
  * ``/api/v1/partner``  — partner-authed (X-API-Key) read-only data pulls.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.ordering.models import Customer
from app.partner.deps import partner_authenticated_restaurant
from app.partner.health import get_partner_integration_health
from app.partner.keys import generate_api_key
from app.partner.models import PartnerApiKey
from app.partner.integration import apply_partner_settings, partner_settings
from app.partner.menu_api import (
    PartnerMenuItemInput,
    get_partner_menu_sync_status,
    patch_partner_menu_item,
    queue_pos_menu_pull,
    upsert_partner_menu_items,
)
from app.partner.delivery_api import (
    RateLimitError,
    get_partner_order_delivery,
    get_partner_rider_location,
)
from app.partner.orders_api import (
    ack_partner_order,
    apply_partner_kitchen_status,
    build_partner_order_data,
    list_partner_orders,
)
from app.partner.schemas import (
    ApiKeyCreatedOut,
    ApiKeyCreateIn,
    ApiKeyOut,
    PartnerConversationListOut,
    PartnerConversationOut,
    PartnerCustomerListOut,
    PartnerCustomerOut,
    PartnerMessageListOut,
    PartnerMessageOut,
    PartnerSendMessageIn,
    PartnerTakeoverIn,
    PartnerTakeoverOut,
    PartnerDeliveryOut,
    PartnerIntegrationConfigIn,
    PartnerIntegrationConfigOut,
    PartnerIntegrationHealthOut,
    PartnerMenuBulkIn,
    PartnerMenuChangedIn,
    PartnerMenuChangedOut,
    PartnerMenuItemOut,
    PartnerMenuPatchIn,
    PartnerMenuSyncStatusOut,
    PartnerMenuUpsertOut,
    PartnerOrderAckIn,
    PartnerOrderListOut,
    PartnerOrderOut,
    PartnerOrderStatusIn,
    PartnerOrderStatusOut,
    PartnerRiderLocationOut,
    PartnerRiderOut,
    PartnerRiderRosterItem,
    PartnerRiderRosterOut,
    PartnerStoreOut,
    PartnerWebhookTestOut,
)
from app.partner.webhooks.enqueue import enqueue_partner_webhook, schedule_partner_webhook_delivery

# ── Key management (manager JWT) ─────────────────────────────────────────────
keys_router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


@keys_router.post("", response_model=ApiKeyCreatedOut, status_code=201)
async def create_api_key(
    body: ApiKeyCreateIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreatedOut:
    """Mint a key for this restaurant. The full key is returned ONCE here and is
    never retrievable again — only its hash is stored."""
    full_key, prefix, key_hash = generate_api_key()
    row = PartnerApiKey(
        restaurant_id=restaurant.id,
        label=body.label.strip(),
        key_prefix=prefix,
        key_hash=key_hash,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ApiKeyCreatedOut(
        id=row.id,
        label=row.label,
        key_prefix=row.key_prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        api_key=full_key,
    )


@keys_router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyOut]:
    """List this restaurant's keys (active + revoked), newest first. Never the
    secret — only the display prefix."""
    rows = (
        await session.scalars(
            select(PartnerApiKey)
            .where(PartnerApiKey.restaurant_id == restaurant.id)
            .order_by(PartnerApiKey.id.desc())
        )
    ).all()
    return [
        ApiKeyOut(
            id=r.id,
            label=r.label,
            key_prefix=r.key_prefix,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            revoked_at=r.revoked_at,
        )
        for r in rows
    ]


@keys_router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke a key (soft delete). Idempotent — revoking an already-revoked key
    is a no-op."""
    row = await session.get(PartnerApiKey, key_id)
    if row is None or row.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Partner data pulls (X-API-Key) ───────────────────────────────────────────
partner_router = APIRouter(prefix="/api/v1/partner", tags=["partner"])

_MAX_PAGE = 500


@partner_router.get("/customers", response_model=PartnerCustomerListOut)
async def partner_list_customers(
    updated_since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerCustomerListOut:
    """Read-only customer pull for a partner POS, scoped to the key's restaurant.

    Supports incremental sync: pass ``updated_since`` (ISO 8601) to fetch only
    customers changed at/after that time, ordered oldest-change first. The
    response echoes ``next_updated_since`` (the newest ``updated_at`` in the
    page) so the POS can resume from there.
    """
    page = max(1, min(limit, _MAX_PAGE))
    stmt = select(Customer).where(Customer.restaurant_id == restaurant.id)
    if updated_since is not None:
        stmt = stmt.where(Customer.updated_at >= updated_since)
    rows = (
        await session.scalars(
            stmt.order_by(Customer.updated_at.asc(), Customer.id.asc())
            .limit(page)
            .offset(max(0, offset))
        )
    ).all()
    items = [
        PartnerCustomerOut(
            id=c.id,
            name=c.name,
            phone=c.phone,
            total_orders=c.total_orders,
            total_spend=c.total_spend,
            first_order_at=c.first_order_at,
            last_order_at=c.last_order_at,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in rows
    ]
    return PartnerCustomerListOut(
        items=items,
        limit=page,
        offset=max(0, offset),
        next_updated_since=items[-1].updated_at if items else None,
    )


def _partner_order_out(data: dict) -> PartnerOrderOut:
    return PartnerOrderOut(
        order_id=data["order_id"],
        order_number=data["order_number"],
        pos_store_id=data["pos_store_id"],
        status=data["status"],
        pos_order_id=data.get("pos_order_id"),
        pos_push_status=data.get("pos_push_status"),
        customer=data["customer"],
        items=data["items"],
        additional_details=data.get("additional_details"),
        address=data.get("address"),
        subtotal=data["subtotal"],
        delivery_fee=data["delivery_fee"],
        wallet_applied=data["wallet_applied"],
        total=data["total"],
        cod_due=data["cod_due"],
        payment=data.get("payment", "COD"),
        distance_km=data.get("distance_km"),
        promised_eta=data.get("promised_eta"),
        sla_deadline=data.get("sla_deadline"),
        created_at=data.get("created_at"),
    )


@partner_router.get("/orders", response_model=PartnerOrderListOut)
async def partner_list_orders(
    status: str | None = "confirmed",
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    unacked_only: bool = True,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerOrderListOut:
    """Poll new confirmed orders (backup when POS cannot receive webhooks)."""
    page = max(1, min(limit, 500))
    orders = await list_partner_orders(
        session,
        restaurant=restaurant,
        status=status,
        since=since,
        unacked_only=unacked_only,
        limit=page,
        offset=offset,
    )
    items = [
        _partner_order_out(
            await build_partner_order_data(session, order=o, restaurant=restaurant)
        )
        for o in orders
    ]
    return PartnerOrderListOut(items=items, limit=page, offset=max(0, offset))


@partner_router.get("/orders/{order_id}", response_model=PartnerOrderOut)
async def partner_get_order(
    order_id: int,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerOrderOut:
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    data = await build_partner_order_data(session, order=order, restaurant=restaurant)
    return _partner_order_out(data)


@partner_router.post("/orders/{order_id}/status", response_model=PartnerOrderStatusOut)
async def partner_update_order_status(
    order_id: int,
    body: PartnerOrderStatusIn,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerOrderStatusOut:
    """POS kitchen update — preparing / ready triggers same path as dashboard advance."""
    try:
        order = await apply_partner_kitchen_status(
            session,
            restaurant=restaurant,
            order_id=order_id,
            pos_status=body.status,
            reason=body.reason,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Order not found":
            raise HTTPException(status.HTTP_404_NOT_FOUND, msg) from exc
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg) from exc

    # Kitchen transition already committed. Customer/manager notification delivery
    # is best-effort — a WhatsApp send/render failure must not 500 the POS's action.
    from app.outbox.service import deliver_pending

    try:
        await deliver_pending(session, restaurant.id)
    except Exception:  # noqa: BLE001 - notifications are best-effort
        import logging

        logging.getLogger(__name__).exception(
            "partner status: deliver_pending failed (restaurant_id=%s, order_id=%s)",
            restaurant.id,
            order_id,
        )
    try:
        from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

        await flush_pending_partner_webhooks(session, restaurant_id=restaurant.id)
    except Exception:  # noqa: BLE001 - webhooks are best-effort
        import logging

        logging.getLogger(__name__).exception(
            "partner status: webhook flush failed (restaurant_id=%s, order_id=%s)",
            restaurant.id,
            order_id,
        )
    return PartnerOrderStatusOut(
        order_id=order.id,
        order_number=order.order_number,
        status=order.status,
        rider_assigned=order.rider_id is not None,
    )


def _partner_delivery_out(data: dict) -> PartnerDeliveryOut:
    rider_raw = data.get("rider")
    rider = PartnerRiderOut(**rider_raw) if rider_raw else None
    return PartnerDeliveryOut(
        order_id=data["order_id"],
        order_number=data["order_number"],
        pos_store_id=data["pos_store_id"],
        pos_order_id=data.get("pos_order_id"),
        status=data["status"],
        rider=rider,
        batch_id=data.get("batch_id"),
        eta_minutes=data.get("eta_minutes"),
        promised_eta=data.get("promised_eta"),
        delivered_at=data.get("delivered_at"),
        late=data.get("late", False),
        cod_due=data["cod_due"],
        cod_collected=data.get("cod_collected"),
    )


@partner_router.get("/orders/{order_id}/delivery", response_model=PartnerDeliveryOut)
async def partner_order_delivery(
    order_id: int,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerDeliveryOut:
    """Poll backup: rider assignment, ETA, delivery status, COD collected."""
    data = await get_partner_order_delivery(
        session, restaurant=restaurant, order_id=order_id
    )
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return _partner_delivery_out(data)


@partner_router.get("/riders", response_model=PartnerRiderRosterOut)
async def partner_list_riders(
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerRiderRosterOut:
    """Full rider roster for the store (every rider, not just those on delivery)."""
    from app.identity.models import Rider

    riders = (
        await session.scalars(
            select(Rider)
            .where(Rider.restaurant_id == restaurant.id)
            .order_by(Rider.name.asc(), Rider.id.asc())
        )
    ).all()
    return PartnerRiderRosterOut(
        items=[
            PartnerRiderRosterItem(
                id=r.id,
                name=r.name,
                phone=r.phone,
                status=r.status,
                on_duty=r.on_duty,
                total_deliveries=int((r.performance or {}).get("total_deliveries", 0)),
            )
            for r in riders
        ]
    )


@partner_router.get(
    "/riders/{rider_id}/location",
    response_model=PartnerRiderLocationOut | None,
)
async def partner_rider_location(
    rider_id: int,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerRiderLocationOut | None:
    """Read-only latest rider GPS (rate-limited: 1 req / 10s per rider)."""
    try:
        result = await get_partner_rider_location(
            session, restaurant=restaurant, rider_id=rider_id
        )
    except RateLimitError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    if result is False:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    if result is None:
        return None
    return PartnerRiderLocationOut(**result)


@partner_router.post("/orders/{order_id}/ack", response_model=PartnerOrderOut)
async def partner_ack_order(
    order_id: int,
    body: PartnerOrderAckIn,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerOrderOut:
    """POS stores its order id after receiving ``order.created``."""
    order = await ack_partner_order(
        session,
        restaurant=restaurant,
        order_id=order_id,
        pos_order_id=body.pos_order_id,
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    await session.commit()
    data = await build_partner_order_data(session, order=order, restaurant=restaurant)
    return _partner_order_out(data)


@partner_router.put("/menu/items", response_model=PartnerMenuUpsertOut)
async def partner_upsert_menu_items(
    body: PartnerMenuBulkIn,
    publish: bool = True,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerMenuUpsertOut:
    """Bulk upsert menu items by ``pos_id`` (push path — real-time menu sync)."""
    from decimal import Decimal

    inputs = [
        PartnerMenuItemInput(
            pos_id=i.pos_id,
            dish_number=i.dish_number,
            name=i.name,
            price_aed=Decimal(str(i.price)),
            category=i.category,
            description=i.description,
            is_available=i.is_available,
        )
        for i in body.items
    ]
    result = await upsert_partner_menu_items(
        session, restaurant_id=restaurant.id, items=inputs, publish=publish
    )
    await session.commit()
    return PartnerMenuUpsertOut(
        created=result.created,
        updated=result.updated,
        images=result.images,
        errors=result.errors or [],
    )


@partner_router.patch("/menu/items/{pos_id}", response_model=PartnerMenuItemOut)
async def partner_patch_menu_item(
    pos_id: str,
    body: PartnerMenuPatchIn,
    publish: bool = True,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerMenuItemOut:
    """Fast sold-out / price update for one POS item."""
    from decimal import Decimal

    try:
        dish = await patch_partner_menu_item(
            session,
            restaurant_id=restaurant.id,
            pos_id=pos_id,
            price_aed=Decimal(str(body.price)) if body.price is not None else None,
            is_available=body.is_available,
            name=body.name,
            publish=publish,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if dish is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    await session.commit()
    return PartnerMenuItemOut(
        pos_id=dish.pos_product_id or pos_id,
        dish_number=dish.dish_number,
        name=dish.name,
        price=float(dish.price_aed),
        category=dish.category,
        is_available=dish.is_available,
    )


@partner_router.post("/events/menu-changed", response_model=PartnerMenuChangedOut)
async def partner_menu_changed(
    body: PartnerMenuChangedIn | None = None,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
) -> PartnerMenuChangedOut:
    """Signal that POS menu changed — queues a full POS pull (Path B)."""
    _ = body
    out = queue_pos_menu_pull(restaurant.id)
    return PartnerMenuChangedOut(**out)


@partner_router.get("/menu/sync-status", response_model=PartnerMenuSyncStatusOut)
async def partner_menu_sync_status(
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerMenuSyncStatusOut:
    data = await get_partner_menu_sync_status(session, restaurant=restaurant)
    return PartnerMenuSyncStatusOut(**data)


@partner_router.get("/store", response_model=PartnerStoreOut)
async def partner_store(
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
) -> PartnerStoreOut:
    """Store identity + integration flags for the POS (API-key authed)."""
    cfg = partner_settings(restaurant)
    return PartnerStoreOut(
        restaurant_id=restaurant.id,
        name=restaurant.name,
        phone=restaurant.phone,
        pos_store_id=cfg["pos_store_id"],
        partner_enabled=cfg["partner_enabled"],
        pos_order_push_mode=cfg["pos_order_push_mode"],
    )


# ── Partner chat (WhatsApp conversation) ─────────────────────────────────────
@partner_router.get("/conversations", response_model=PartnerConversationListOut)
async def partner_list_conversations(
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerConversationListOut:
    """WhatsApp threads for this store (newest activity first), each with a
    last-message preview and unread flag. The POS matches ``phone`` to an order's
    customer phone to open that customer's chat."""
    from app.conversation.service import list_dashboard_conversations

    rows = await list_dashboard_conversations(session, restaurant_id=restaurant.id)
    return PartnerConversationListOut(
        items=[PartnerConversationOut(**row) for row in rows]
    )


@partner_router.get(
    "/conversations/{conversation_id}/messages",
    response_model=PartnerMessageListOut,
)
async def partner_get_conversation_messages(
    conversation_id: int,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerMessageListOut:
    """Full message history for one thread, oldest-first (POS polls this for live chat)."""
    from app.conversation.models import Conversation
    from app.conversation.service import get_dashboard_messages, message_display_text

    messages = await get_dashboard_messages(
        session, restaurant_id=restaurant.id, conversation_id=conversation_id
    )
    if messages is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    conv = await session.get(Conversation, conversation_id)
    return PartnerMessageListOut(
        conversation_id=conversation_id,
        phone=conv.phone if conv else "",
        counterpart=conv.counterpart if conv else "",
        manual_takeover=bool(conv.manual_takeover) if conv else False,
        items=[
            PartnerMessageOut(
                id=m.id,
                direction=m.direction,
                type=m.type,
                text=message_display_text(m.payload or {}),
                ts=m.ts,
            )
            for m in messages
        ],
    )


@partner_router.post(
    "/conversations/{conversation_id}/messages",
    response_model=PartnerMessageOut,
    status_code=201,
)
async def partner_send_conversation_message(
    conversation_id: int,
    body: PartnerSendMessageIn,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerMessageOut:
    """POS agent sends a WhatsApp reply. By default this also takes the thread over
    from the bot so the two don't both answer."""
    from app.conversation.service import (
        message_display_text,
        send_manual_message,
        set_manual_takeover,
    )

    result = await send_manual_message(
        session,
        restaurant_id=restaurant.id,
        conversation_id=conversation_id,
        text=body.text,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    msg, _outbox_id = result
    if body.take_over:
        await set_manual_takeover(
            session,
            conversation_id=conversation_id,
            taken_over_by=restaurant.id,
            active=True,
            restaurant_id=restaurant.id,
        )
    await session.commit()

    # Deliver the queued WhatsApp send (sync in-request on free tier, else Celery).
    from app.outbox.service import deliver_pending

    try:
        await deliver_pending(session, restaurant.id)
    except Exception:  # noqa: BLE001 - delivery failure must not 500 the POS action
        import logging

        logging.getLogger(__name__).exception(
            "partner chat: deliver_pending failed (restaurant_id=%s, conversation_id=%s)",
            restaurant.id,
            conversation_id,
        )
    return PartnerMessageOut(
        id=msg.id,
        direction=msg.direction,
        type=msg.type,
        text=message_display_text(msg.payload or {}),
        ts=msg.ts,
    )


@partner_router.post(
    "/conversations/{conversation_id}/takeover",
    response_model=PartnerTakeoverOut,
)
async def partner_set_conversation_takeover(
    conversation_id: int,
    body: PartnerTakeoverIn,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerTakeoverOut:
    """Take a thread over from the bot (``active=true``) or hand it back (``false``)."""
    from app.conversation.service import set_manual_takeover

    ok = await set_manual_takeover(
        session,
        conversation_id=conversation_id,
        taken_over_by=restaurant.id,
        active=body.active,
        restaurant_id=restaurant.id,
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    await session.commit()
    return PartnerTakeoverOut(
        conversation_id=conversation_id, manual_takeover=body.active
    )


# ── Manager integration config (JWT) ─────────────────────────────────────────
integration_router = APIRouter(prefix="/api/v1/partner-integration", tags=["partner-integration"])


def _config_out(restaurant: Restaurant) -> PartnerIntegrationConfigOut:
    cfg = partner_settings(restaurant)
    return PartnerIntegrationConfigOut(
        partner_enabled=cfg["partner_enabled"],
        partner_webhook_url=cfg["partner_webhook_url"],
        partner_webhook_secret_set=bool(cfg["partner_webhook_secret"]),
        pos_store_id=cfg["pos_store_id"],
        pos_order_push_mode=cfg["pos_order_push_mode"],
    )


@integration_router.get("/config", response_model=PartnerIntegrationConfigOut)
async def get_partner_integration_config(
    restaurant: Restaurant = Depends(current_restaurant),
) -> PartnerIntegrationConfigOut:
    return _config_out(restaurant)


@integration_router.get("/health", response_model=PartnerIntegrationHealthOut)
async def get_partner_integration_health_endpoint(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerIntegrationHealthOut:
    """Integration health: last webhook delivery, pending count, menu sync."""
    data = await get_partner_integration_health(session, restaurant=restaurant)
    return PartnerIntegrationHealthOut(**data)


@integration_router.patch("/config", response_model=PartnerIntegrationConfigOut)
async def patch_partner_integration_config(
    body: PartnerIntegrationConfigIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerIntegrationConfigOut:
    patch = body.model_dump(exclude_unset=True)
    apply_partner_settings(restaurant, patch)
    await session.commit()
    await session.refresh(restaurant)
    return _config_out(restaurant)


@integration_router.post("/webhooks/test", response_model=PartnerWebhookTestOut)
async def test_partner_webhook(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> PartnerWebhookTestOut:
    """Enqueue a test ``integration.ping`` webhook and deliver it (sync or Celery)."""
    cfg = partner_settings(restaurant)
    if not cfg["partner_enabled"] or not cfg["partner_webhook_url"]:
        return PartnerWebhookTestOut(
            queued=False,
            detail="Enable partner integration and set partner_webhook_url first.",
        )

    import uuid

    idem = f"test-ping-{restaurant.id}-{uuid.uuid4().hex[:12]}"
    row = await enqueue_partner_webhook(
        session,
        restaurant=restaurant,
        event_type="integration.ping",
        data={"message": "Webhook test from WhatsApp ordering platform"},
        idempotency_key=idem,
    )
    if row is None:
        return PartnerWebhookTestOut(queued=False, detail="Failed to enqueue (duplicate?).")
    await session.commit()
    await schedule_partner_webhook_delivery(row.id)
    return PartnerWebhookTestOut(
        queued=True,
        delivery_id=row.id,
        detail="Test webhook queued for delivery.",
    )
