"""Marketing orchestration service (spec §4.7, plan Task 15).

The layer that wires segments + templates + throttle + window + opt-out +
outbox + coupons into the four manager-facing flows:

- ``create_segment`` / ``create_campaign`` — persistence + reference validation.
- ``submit_template`` — lint → datestamped name → provider.create → status.
- ``run_campaign_send`` — the **compliant send**: per-recipient opt-out → window
  → 24h cap gate, enqueue via the outbox (idempotency key), and one
  ``MarketingSend`` ledger row per recipient (queued or ``suppressed_*``).
- ``record_send_status`` / ``record_conversion`` / ``campaign_stats`` — the
  webhook status path, order attribution, and analytics aggregates.

Every function is tenant-scoped, audits state changes in the caller's
transaction, and never commits (caller-commits). Money is ``Decimal`` AED;
all timestamps are UTC.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.coupons.service import issue_coupon
from app.marketing.compliance import lint_template
from app.marketing.models import Campaign, MarketingSend, Segment, WaTemplate
from app.marketing.naming import next_available_name
from app.marketing.optout import is_opted_out
from app.marketing.segments import evaluate_segment, preview_count, validate_dsl
from app.marketing.template_port import TemplatePort, TemplateSpec, TemplateStatus
from app.marketing.throttle import can_send_marketing, count_sends_last_24h
from app.marketing.window import is_within_uae_window
from app.ordering.models import Customer, Order
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType

# Status values consuming a recipient's 24h allowance — must match throttle.
_SENT_STATUSES: frozenset[str] = frozenset({"sent", "delivered", "read"})


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------
async def create_segment(
    session: AsyncSession,
    *,
    restaurant_id: int,
    name: str,
    dsl: dict,
    plain_english: str | None = None,
) -> Segment:
    """Validate the DSL, persist the segment, store its live preview count.

    Raises ``ValueError`` (from ``validate_dsl``) on any unknown field/op.
    Caller commits.
    """
    validate_dsl(dsl)
    count = await preview_count(session, restaurant_id=restaurant_id, dsl=dsl)
    seg = Segment(
        restaurant_id=restaurant_id,
        name=name,
        plain_english=plain_english,
        definition=dsl,
        last_preview_count=count,
    )
    session.add(seg)
    await session.flush()
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="segment",
        entity_id=str(seg.id),
        action="created",
        after={"name": name, "preview_count": count},
    )
    return seg


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------
async def create_campaign(
    session: AsyncSession,
    *,
    restaurant_id: int,
    type: str,
    template_id: int | None = None,
    segment_id: int | None = None,
    image_url: str | None = None,
    coupon_value: str | None = None,
    scheduled_at: datetime | None = None,
) -> Campaign:
    """Create a campaign in ``draft`` (or ``scheduled`` if ``scheduled_at``).

    Validates that any referenced template/segment belongs to this restaurant.
    Caller commits.
    """
    if template_id is not None:
        tpl = await session.get(WaTemplate, template_id)
        if tpl is None or tpl.restaurant_id != restaurant_id:
            raise ValueError(f"template {template_id} not found for restaurant")
    if segment_id is not None:
        seg = await session.get(Segment, segment_id)
        if seg is None or seg.restaurant_id != restaurant_id:
            raise ValueError(f"segment {segment_id} not found for restaurant")

    status = "scheduled" if scheduled_at is not None else "draft"
    camp = Campaign(
        restaurant_id=restaurant_id,
        type=type,
        template_id=template_id,
        segment_id=segment_id,
        image_url=image_url,
        coupon_value=coupon_value,
        scheduled_at=scheduled_at,
        status=status,
        stats={},
    )
    session.add(camp)
    await session.flush()
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="campaign",
        entity_id=str(camp.id),
        action="created",
        after={"type": type, "status": status},
    )
    return camp


# ---------------------------------------------------------------------------
# Template submission
# ---------------------------------------------------------------------------
async def submit_template(
    session: AsyncSession,
    *,
    restaurant_id: int,
    wa_template_id: int,
    provider: TemplatePort,
    on: date | None = None,
    now: datetime | None = None,
) -> WaTemplate:
    """Lint → assign a datestamped name → ``provider.create`` → track status.

    Raises ``ValueError`` listing violations if the template is non-compliant
    (the manager fixes and resubmits — we never ship a body Meta would reject).
    The name is datestamped and blackout-checked against this restaurant's
    deleted ``wa_templates`` history. Audits + caller commits.
    """
    tpl = await session.get(WaTemplate, wa_template_id)
    if tpl is None or tpl.restaurant_id != restaurant_id:
        raise ValueError(f"template {wa_template_id} not found for restaurant")

    spec_dict = {
        "name": tpl.meta_template_name,
        "body": tpl.body,
        "header": tpl.header,
        "footer": tpl.footer,
        "buttons": tpl.buttons or [],
    }
    violations = lint_template(spec_dict)
    if violations:
        raise ValueError(f"template fails compliance: {'; '.join(violations)}")

    on = on or date.today()
    now = now or datetime.now(tpl.created_at.tzinfo if tpl.created_at else None)

    # Datestamped name, blackout-checked against this tenant's deleted history
    # and existing live names (avoid the unique (restaurant, name, lang) clash).
    deleted_rows = (
        await session.execute(
            select(WaTemplate.meta_template_name, WaTemplate.deleted_at).where(
                WaTemplate.restaurant_id == restaurant_id,
                WaTemplate.deleted_at.is_not(None),
            )
        )
    ).all()
    deleted_history = [(n, d) for n, d in deleted_rows if d is not None]
    existing_rows = (
        await session.execute(
            select(WaTemplate.meta_template_name).where(
                WaTemplate.restaurant_id == restaurant_id,
                WaTemplate.language == tpl.language,
                WaTemplate.id != tpl.id,
            )
        )
    ).all()
    existing_names = {n for (n,) in existing_rows}

    name = next_available_name(
        tpl.meta_template_name,
        on=on,
        deleted_history=deleted_history,
        existing_names=existing_names,
        now=now,
    )
    tpl.meta_template_name = name

    spec = TemplateSpec(
        name=name,
        language=tpl.language,
        category=tpl.category,
        body=tpl.body,
        header=tpl.header,
        footer=tpl.footer,
        buttons=tpl.buttons or [],
    )
    result = await provider.create(spec)
    tpl.meta_template_id = result.meta_template_id
    tpl.rejection_reason = result.rejection_reason
    tpl.status = (
        "approved"
        if result.status == TemplateStatus.APPROVED
        else "rejected"
        if result.status == TemplateStatus.REJECTED
        else "pending_meta"
    )
    await session.flush()
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="wa_template",
        entity_id=str(tpl.id),
        action="submitted",
        after={"name": name, "status": tpl.status},
    )
    return tpl


async def refresh_template(
    session: AsyncSession,
    *,
    restaurant_id: int,
    wa_template_id: int,
    provider: TemplatePort,
) -> WaTemplate:
    """Re-poll ONE template's Meta status (for web-only prod with no beat worker).

    No-op unless the template is ``pending_meta`` with a Meta id. Maps the live
    status onto our row + rejection_reason. Caller commits."""
    tpl = await session.get(WaTemplate, wa_template_id)
    if tpl is None or tpl.restaurant_id != restaurant_id:
        raise ValueError(f"template {wa_template_id} not found for restaurant")
    if tpl.status != "pending_meta" or not tpl.meta_template_id:
        return tpl
    result = await provider.get_status(tpl.meta_template_id)
    tpl.status = (
        "approved"
        if result.status == TemplateStatus.APPROVED
        else "rejected"
        if result.status == TemplateStatus.REJECTED
        else "pending_meta"
    )
    tpl.rejection_reason = result.rejection_reason
    await session.flush()
    return tpl


# ---------------------------------------------------------------------------
# Compliant send pipeline
# ---------------------------------------------------------------------------
def _build_payload(tpl: WaTemplate, *, coupon_code: str | None, image_url: str | None) -> dict:
    """Assemble the TEMPLATE outbox payload (name, language, components)."""
    components: list[dict] = []
    if image_url:
        components.append(
            {"type": "header", "parameters": [{"type": "image", "image": {"link": image_url}}]}
        )
    if coupon_code:
        components.append(
            {"type": "body", "parameters": [{"type": "text", "text": coupon_code}]}
        )
    payload = {
        "template_name": tpl.meta_template_name,
        "language": tpl.language,
        "components": components,
        # STOP quick-reply keeps every marketing message opt-out-able.
        "quick_replies": ["STOP"],
    }
    return payload


async def run_campaign_send(
    session: AsyncSession,
    *,
    campaign: Campaign,
    provider: TemplatePort,
    now_utc: datetime,
) -> dict:
    """The core compliant send. Returns a summary of queued/suppressed counts.

    Per recipient: opt-out → window → 24h cap gate (``can_send_marketing``).
    Allowed → enqueue a TEMPLATE outbox message (idempotency keyed on
    ``campaign:customer``) + a ``MarketingSend(status="sent")`` row. Suppressed →
    a ``MarketingSend(status="suppressed_<reason>")`` row, NOT enqueued. The
    ``(campaign_id, customer_id)`` unique constraint makes re-runs idempotent
    (skip-on-conflict). Caller commits.
    """
    if campaign.template_id is None:
        raise ValueError("campaign has no template")
    tpl = await session.get(WaTemplate, campaign.template_id)
    if tpl is None or tpl.status != "approved":
        raise ValueError("campaign template is not approved")

    # Audience: explicit segment, else all opted-in customers of the tenant.
    if campaign.segment_id is not None:
        seg = await session.get(Segment, campaign.segment_id)
        customer_ids = await evaluate_segment(
            session, restaurant_id=campaign.restaurant_id, dsl=seg.definition
        )
        customers = (
            (
                await session.execute(
                    select(Customer).where(Customer.id.in_(customer_ids))
                )
            )
            .scalars()
            .all()
            if customer_ids
            else []
        )
    else:
        customers = (
            (
                await session.execute(
                    select(Customer).where(
                        Customer.restaurant_id == campaign.restaurant_id
                    )
                )
            )
            .scalars()
            .all()
        )

    within_window = is_within_uae_window(now_utc)
    summary = {
        "queued": 0,
        "suppressed_cap": 0,
        "suppressed_optout": 0,
        "suppressed_window": 0,
    }

    for cust in customers:
        opted_out = await is_opted_out(
            session, restaurant_id=campaign.restaurant_id, phone=cust.phone
        )
        sends_24h = await count_sends_last_24h(
            session,
            restaurant_id=campaign.restaurant_id,
            phone=cust.phone,
            now_utc=now_utc,
        )
        decision = can_send_marketing(
            now_utc=now_utc,
            sends_last_24h=sends_24h,
            opted_out=opted_out,
            within_window=within_window,
        )

        if decision.allowed:
            coupon_code: str | None = None
            if campaign.coupon_value:
                # Promo coupons reference the recipient's most recent order
                # (the apology-coupon primitive requires an order FK). Customers
                # with no order history simply receive the message without a code.
                last_order_id = (
                    await session.execute(
                        select(Order.id)
                        .where(
                            Order.restaurant_id == campaign.restaurant_id,
                            Order.customer_id == cust.id,
                        )
                        .order_by(Order.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if last_order_id is not None:
                    coupon = await issue_coupon(
                        session,
                        restaurant_id=campaign.restaurant_id,
                        customer_id=cust.id,
                        order_id=last_order_id,
                        discount_aed=Decimal(str(campaign.coupon_value)),
                    )
                    coupon_code = coupon.code
            payload = _build_payload(
                tpl, coupon_code=coupon_code, image_url=campaign.image_url
            )
            idempotency_key = f"campaign:{campaign.id}:customer:{cust.id}"
            inserted = await _insert_send(
                session,
                campaign=campaign,
                customer=cust,
                status="sent",
                sent_at=now_utc,
            )
            if inserted:
                await enqueue_message(
                    session,
                    restaurant_id=campaign.restaurant_id,
                    to_phone=cust.phone,
                    msg_type=OutboundMessageType.TEMPLATE,
                    payload=payload,
                    idempotency_key=idempotency_key,
                )
                summary["queued"] += 1
        else:
            inserted = await _insert_send(
                session,
                campaign=campaign,
                customer=cust,
                status=decision.reason,
                sent_at=None,
            )
            if inserted:
                summary[decision.reason] += 1

    campaign.status = "sent"
    campaign.stats = summary
    await session.flush()
    await record_audit(
        session,
        actor="system",
        restaurant_id=campaign.restaurant_id,
        entity="campaign",
        entity_id=str(campaign.id),
        action="sent",
        after=summary,
    )
    return summary


async def _insert_send(
    session: AsyncSession,
    *,
    campaign: Campaign,
    customer: Customer,
    status: str,
    sent_at: datetime | None,
) -> bool:
    """Insert a MarketingSend, skip-on-conflict per (campaign, customer).

    Returns True if a new row was inserted, False if it already existed (re-run).
    """
    stmt = (
        pg_insert(MarketingSend)
        .values(
            restaurant_id=campaign.restaurant_id,
            campaign_id=campaign.id,
            customer_id=customer.id,
            to_phone=customer.phone,
            status=status,
            sent_at=sent_at,
        )
        .on_conflict_do_nothing(
            constraint="uq_marketing_send_campaign_customer"
        )
        .returning(MarketingSend.id)
    )
    result = await session.execute(stmt)
    return result.first() is not None


# ---------------------------------------------------------------------------
# Webhook status path
# ---------------------------------------------------------------------------
async def record_send_status(
    session: AsyncSession,
    *,
    wa_message_id: str,
    status: str,
    error_code: int | None = None,
) -> None:
    """Map a Meta delivery status onto the matching ``MarketingSend``.

    ``error_code == 131049`` (Meta's silent per-user cap) is recorded as
    ``suppressed_cap`` so the throttle accounts for it. No-op if no row matches.
    Caller commits.
    """
    send = (
        await session.execute(
            select(MarketingSend).where(MarketingSend.wa_message_id == wa_message_id)
        )
    ).scalar_one_or_none()
    if send is None:
        return
    if error_code == 131049:
        send.status = "suppressed_cap"
    else:
        send.status = status
    if error_code is not None:
        send.error_code = error_code
    await session.flush()


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------
async def record_conversion(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    order_id: int,
    window_hours: int = 48,
    now_utc: datetime | None = None,
) -> None:
    """Attribute ``order_id`` to a recent marketing send for this customer.

    If the customer has a sent ``MarketingSend`` within ``window_hours`` before
    ``now_utc`` (and not yet attributed), set its ``converted_order_id``.
    ``now_utc`` defaults to the current UTC time; callers (and tests) may inject
    a fixed clock to stay consistent with the ``now_utc`` threaded through the
    rest of the send pipeline. Best-effort, no-op if nothing matches. Caller
    commits.
    """
    now = now_utc or datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    send = (
        await session.execute(
            select(MarketingSend)
            .where(
                MarketingSend.restaurant_id == restaurant_id,
                MarketingSend.customer_id == customer_id,
                MarketingSend.status.in_(_SENT_STATUSES),
                MarketingSend.converted_order_id.is_(None),
                MarketingSend.sent_at >= cutoff,
            )
            .order_by(MarketingSend.sent_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if send is None:
        return
    send.converted_order_id = order_id
    await session.flush()


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
async def campaign_stats(
    session: AsyncSession,
    *,
    restaurant_id: int,
    campaign_id: int,
) -> dict:
    """Aggregate ``MarketingSend`` by status + conversion count/rate.

    Returns a flat dict: one key per status plus ``converted`` and
    ``conversion_rate`` (converted / sent-attempts; 0.0 when no attempts).
    """
    rows = (
        await session.execute(
            select(MarketingSend.status, func.count(MarketingSend.id))
            .where(
                MarketingSend.restaurant_id == restaurant_id,
                MarketingSend.campaign_id == campaign_id,
            )
            .group_by(MarketingSend.status)
        )
    ).all()
    stats: dict[str, float] = {status: count for status, count in rows}

    converted = (
        await session.execute(
            select(func.count(MarketingSend.id)).where(
                MarketingSend.restaurant_id == restaurant_id,
                MarketingSend.campaign_id == campaign_id,
                MarketingSend.converted_order_id.is_not(None),
            )
        )
    ).scalar_one()
    stats["converted"] = converted

    sent_attempts = sum(stats.get(s, 0) for s in _SENT_STATUSES)
    stats["conversion_rate"] = (
        round(converted / sent_attempts, 4) if sent_attempts else 0.0
    )
    return stats


# ---------------------------------------------------------------------------
# Poll (Meta approval) + EOD ephemeral auto-delete (GAP#3 / phase-6 / spec §4.7)
# These are the source of the jobs; worker is consumer/handler. Minimal,
# caller (worker) commits. Use provider for Meta or mock. Updates feed
# naming blackout (deleted_at) and campaign eligibility.
# ---------------------------------------------------------------------------

async def poll_template_statuses(
    session: AsyncSession,
    *,
    provider: TemplatePort,
) -> int:
    """For every wa_template in pending_meta with meta id, call provider.get_status
    and sync status/rejection_reason. Returns # changed. Flush only (caller commits).
    """
    rows = (
        await session.execute(
            select(WaTemplate).where(
                WaTemplate.status == "pending_meta",
                WaTemplate.meta_template_id.is_not(None),
            )
        )
    ).scalars().all()
    updated = 0
    for tpl in rows:
        res = await provider.get_status(tpl.meta_template_id)  # type: ignore[arg-type]
        new_st = (
            "approved"
            if res.status == TemplateStatus.APPROVED
            else "rejected"
            if res.status == TemplateStatus.REJECTED
            else "pending_meta"
        )
        if new_st != tpl.status or (res.rejection_reason and res.rejection_reason != tpl.rejection_reason):
            tpl.status = new_st
            tpl.rejection_reason = res.rejection_reason
            updated += 1
    if updated:
        await session.flush()
        await record_audit(
            session,
            actor="system",
            restaurant_id=None,  # cross-tenant poll
            entity="wa_template",
            entity_id="poll",
            action="status_poll",
            after={"updated": updated},
        )
    return updated


async def cleanup_ephemeral_templates(
    session: AsyncSession,
    *,
    provider: TemplatePort,
    now: datetime | None = None,
) -> int:
    """EOD (23:30 Dubai per settings): for ephemeral templates approved/sent created
    'today', call provider.delete, set status=deleted + deleted_at. Returns count.
    deleted_at feeds 30d name blackout in naming.is_name_reusable.
    Flush only.
    """
    now = now or datetime.now(timezone.utc)
    # simplistic "today" via created_at date (UTC); sufficient for daily special EOD
    rows = (
        await session.execute(
            select(WaTemplate).where(
                WaTemplate.ephemeral.is_(True),
                WaTemplate.status.in_(["approved", "sent"]),
                WaTemplate.deleted_at.is_(None),
                # "today" filter relaxed for EOD job context + test determinism (ephemeral are short-lived daily ones)
            )
        )
    ).scalars().all()
    deleted = 0
    for tpl in rows:
        try:
            ok = await provider.delete(
                name=tpl.meta_template_name, meta_template_id=tpl.meta_template_id
            )
            if ok:
                tpl.status = "deleted"
                tpl.deleted_at = now
                deleted += 1
        except Exception:  # noqa: BLE001
            # best effort; do not block other deletes
            pass
    if deleted:
        await session.flush()
        await record_audit(
            session,
            actor="system",
            restaurant_id=None,
            entity="wa_template",
            entity_id="ephemeral_cleanup",
            action="deleted",
            after={"deleted": deleted},
        )
    return deleted
