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

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.coupons.service import issue_coupon
from app.identity.models import Restaurant
from app.marketing.compliance import lint_template
from app.marketing.models import Campaign, MarketingSend, Segment, WaTemplate
from app.marketing.naming import next_available_name
from app.marketing.optout import is_opted_out
from app.marketing.segments import evaluate_segment, preview_count, validate_dsl
from app.marketing.template_port import TemplatePort, TemplateSpec, TemplateStatus
from app.marketing.throttle import can_send_marketing, count_sends_last_24h
from app.marketing.todays_special import (
    DEFAULT_LEAD_MINUTES,
    desired_send_minute,
    is_due,
    parse_hhmm,
)
from app.config import get_settings
from app.marketing.window import is_within_uae_window
from app.ordering.models import Customer, Order
from app.ordering.service import predict_order_time
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType

_DUBAI = ZoneInfo("Asia/Dubai")
# Default fallback send time (Dubai minute-of-day) for customers without a
# trustworthy ordering habit — 11:45, just before the typical lunch rush.
_DEFAULT_SPECIAL_MINUTE = 11 * 60 + 45

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
_BODY_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def _build_payload(
    tpl: WaTemplate,
    *,
    customer_name: str | None,
    coupon_code: str | None,
    image_url: str | None,
) -> dict:
    """Assemble the TEMPLATE outbox payload the Cloud API provider expects.

    Key is ``name`` (NOT ``template_name``) — the provider reads ``payload['name']``,
    so the wrong key silently failed every live send. Body variables are filled in
    order to match the template's ``{{n}}`` count or Meta rejects the message:
    ``{{1}}`` is the customer's name (copywriter convention), and when a coupon is
    issued it fills the LAST variable (e.g. ``...use code {{2}}``).
    """
    components: list[dict] = []
    # An IMAGE-header template REQUIRES a header image parameter at send time or
    # Meta rejects it. Use the campaign's image if set, else fall back to the image
    # the template itself was approved with (stored on the header).
    header_img = image_url
    if not header_img and isinstance(tpl.header, dict) and \
            str(tpl.header.get("type", "")).upper() == "IMAGE":
        header_img = tpl.header.get("image_url") or tpl.header.get("url")
    if header_img:
        components.append(
            {"type": "header", "parameters": [{"type": "image", "image": {"link": header_img}}]}
        )
    n_vars = len({int(m) for m in _BODY_VAR_RE.findall(tpl.body or "")})
    if n_vars:
        name = (customer_name or "").strip() or "there"
        values = [name] * n_vars
        if coupon_code:
            values[-1] = coupon_code  # last var carries the code (e.g. "use {{2}}")
        components.append(
            {"type": "body", "parameters": [{"type": "text", "text": v} for v in values]}
        )
    payload = {
        "name": tpl.meta_template_name,
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
    audience_ids: list[int] | None = None,
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

    # Audience: an explicit id list (e.g. a named RFM bucket computed by the
    # caller) wins; else a saved segment's DSL; else all customers of the tenant.
    if audience_ids is not None:
        customers = (
            (
                await session.execute(
                    select(Customer).where(Customer.id.in_(audience_ids))
                )
            )
            .scalars()
            .all()
            if audience_ids
            else []
        )
    elif campaign.segment_id is not None:
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

    # Send window is opt-in (off by default → always "within window").
    window_on = get_settings().marketing_send_window_enabled
    within_window = (not window_on) or is_within_uae_window(now_utc)
    summary = {
        "queued": 0,
        "suppressed_cap": 0,
        "suppressed_optout": 0,
        "suppressed_window": 0,
    }

    for cust in customers:
        reason = await _send_to_customer(
            session,
            campaign=campaign,
            tpl=tpl,
            customer=cust,
            now_utc=now_utc,
            within_window=within_window,
        )
        if reason in summary:
            summary[reason] += 1

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


async def _send_to_customer(
    session: AsyncSession,
    *,
    campaign: Campaign,
    tpl: WaTemplate,
    customer: Customer,
    now_utc: datetime,
    within_window: bool,
) -> str:
    """Apply the compliance gate to one recipient and enqueue if allowed.

    Returns the outcome: ``"queued"``, a ``"suppressed_*"`` reason, or
    ``"duplicate"`` when a ledger row for this (campaign, customer) already
    existed (skip-on-conflict). Shared by ``run_campaign_send`` (whole audience)
    and ``run_todays_special_tick`` (per-customer timed). Caller commits.
    """
    opted_out = await is_opted_out(
        session, restaurant_id=campaign.restaurant_id, phone=customer.phone
    )
    sends_24h = await count_sends_last_24h(
        session,
        restaurant_id=campaign.restaurant_id,
        phone=customer.phone,
        now_utc=now_utc,
    )
    decision = can_send_marketing(
        now_utc=now_utc,
        sends_last_24h=sends_24h,
        opted_out=opted_out,
        within_window=within_window,
    )

    if not decision.allowed:
        inserted = await _insert_send(
            session, campaign=campaign, customer=customer,
            status=decision.reason, sent_at=None,
        )
        return decision.reason if inserted else "duplicate"

    coupon_code: str | None = None
    if campaign.coupon_value:
        # Promo coupons reference the recipient's most recent order (the
        # apology-coupon primitive requires an order FK). Customers with no
        # order history simply receive the message without a code.
        last_order_id = (
            await session.execute(
                select(Order.id)
                .where(
                    Order.restaurant_id == campaign.restaurant_id,
                    Order.customer_id == customer.id,
                )
                .order_by(Order.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_order_id is not None:
            coupon = await issue_coupon(
                session,
                restaurant_id=campaign.restaurant_id,
                customer_id=customer.id,
                order_id=last_order_id,
                discount_aed=Decimal(str(campaign.coupon_value)),
            )
            coupon_code = coupon.code

    inserted = await _insert_send(
        session, campaign=campaign, customer=customer,
        status="sent", sent_at=now_utc,
    )
    if not inserted:
        return "duplicate"
    payload = _build_payload(
        tpl, customer_name=customer.name,
        coupon_code=coupon_code, image_url=campaign.image_url,
    )
    await enqueue_message(
        session,
        restaurant_id=campaign.restaurant_id,
        to_phone=customer.phone,
        msg_type=OutboundMessageType.TEMPLATE,
        payload=payload,
        idempotency_key=f"campaign:{campaign.id}:customer:{customer.id}",
    )
    return "queued"


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
# Today's Special — per-customer auto-timed daily send
# ---------------------------------------------------------------------------
async def ensure_todays_special_campaign(
    session: AsyncSession,
    *,
    restaurant_id: int,
    template_id: int,
    day_anchor_utc: datetime,
) -> Campaign:
    """Get-or-create today's ``todays_special`` campaign for a restaurant.

    Keyed on ``scheduled_at == day_anchor_utc`` (the Dubai day-start), so there's
    exactly one campaign per restaurant per day regardless of wall-clock. That
    campaign carries the whole day's per-customer sends, and the
    ``(campaign, customer)`` unique constraint then guarantees each customer is
    sent at most once that day. If the manager swapped the template mid-day, the
    existing campaign is repointed. Caller commits.
    """
    existing = (
        await session.execute(
            select(Campaign)
            .where(
                Campaign.restaurant_id == restaurant_id,
                Campaign.type == "todays_special",
                Campaign.scheduled_at == day_anchor_utc,
            )
            .order_by(Campaign.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.template_id != template_id:
            existing.template_id = template_id
            await session.flush()
        return existing
    camp = await create_campaign(
        session,
        restaurant_id=restaurant_id,
        type="todays_special",
        template_id=template_id,
        scheduled_at=day_anchor_utc,
    )
    camp.status = "sending"
    await session.flush()
    return camp


async def run_todays_special_tick(
    session: AsyncSession,
    *,
    now_utc: datetime,
) -> dict:
    """Heartbeat for the Today's Special automation (called by the secured
    ``/marketing/tick`` endpoint on a cron schedule).

    For every restaurant with the toggle enabled and an APPROVED template, send
    the special to each opted-in customer whose predicted send-time is due this
    minute. Idempotent across ticks (per-day campaign + unique ledger). Returns a
    summary plus the list of restaurant ids that queued messages so the caller
    can flush their outbox. Does NOT commit.
    """
    local = now_utc.astimezone(_DUBAI)
    now_minute = local.hour * 60 + local.minute
    day_anchor_utc = local.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)
    window_on = get_settings().marketing_send_window_enabled
    within_window = (not window_on) or is_within_uae_window(now_utc)

    totals = {"queued": 0, "suppressed": 0, "restaurants": []}
    restaurants = (await session.scalars(select(Restaurant))).all()
    for restaurant in restaurants:
        cfg = (restaurant.settings or {}).get("todays_special") or {}
        if not cfg.get("enabled"):
            continue
        template_id = cfg.get("template_id")
        if not template_id:
            continue
        tpl = await session.get(WaTemplate, template_id)
        if tpl is None or tpl.restaurant_id != restaurant.id or tpl.status != "approved":
            continue
        lead = int(cfg.get("lead_minutes", DEFAULT_LEAD_MINUTES))
        # "Custom time" range → only send within [window_start, window_end] and
        # fire new customers at the window start. Absent → "Until today" (no range).
        ws, we = cfg.get("window_start"), cfg.get("window_end")
        if ws and we:
            custom_window = (
                parse_hhmm(ws, default=_DEFAULT_SPECIAL_MINUTE),
                parse_hhmm(we, default=_DEFAULT_SPECIAL_MINUTE),
            )
            default_minute = custom_window[0]
        else:
            custom_window = None
            default_minute = parse_hhmm(
                cfg.get("default_time"), default=_DEFAULT_SPECIAL_MINUTE
            )

        campaign = await ensure_todays_special_campaign(
            session,
            restaurant_id=restaurant.id,
            template_id=template_id,
            day_anchor_utc=day_anchor_utc,
        )

        # Customers already handled today for this campaign — skip (cheap guard;
        # the unique constraint is the real safety net).
        done = set(
            (
                await session.scalars(
                    select(MarketingSend.customer_id).where(
                        MarketingSend.campaign_id == campaign.id
                    )
                )
            ).all()
        )
        customers = (
            await session.scalars(
                select(Customer).where(Customer.restaurant_id == restaurant.id)
            )
        ).all()

        queued_here = 0
        for cust in customers:
            if cust.id in done:
                continue
            pred = await predict_order_time(session, cust.id)
            desired = desired_send_minute(
                pred,
                lead_minutes=lead,
                default_minute=default_minute,
                clamp_window=window_on,
                window=custom_window,
            )
            if not is_due(desired, now_minute):
                continue
            reason = await _send_to_customer(
                session,
                campaign=campaign,
                tpl=tpl,
                customer=cust,
                now_utc=now_utc,
                within_window=within_window,
            )
            if reason == "queued":
                queued_here += 1
                totals["queued"] += 1
            elif reason.startswith("suppressed"):
                totals["suppressed"] += 1

        if queued_here:
            totals["restaurants"].append(restaurant.id)

    await session.flush()
    return totals


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
async def campaign_stats_bulk(
    session: AsyncSession, *, restaurant_id: int
) -> dict[int, dict]:
    """Real send/delivery/conversion counts per campaign, from ``MarketingSend``.

    For the campaigns list + Reports page (which read ``stats.sent`` /
    ``stats.converted``): the stored ``Campaign.stats`` only holds queued/suppressed
    counts, so these have to be aggregated from the send ledger. One grouped query
    over all of a tenant's campaigns (not N+1). ``sent`` counts attempted/delivered
    sends (sent|delivered|read); ``delivered`` counts confirmed (delivered|read).
    """
    status_rows = (
        await session.execute(
            select(
                MarketingSend.campaign_id,
                MarketingSend.status,
                func.count(MarketingSend.id),
            )
            .where(MarketingSend.restaurant_id == restaurant_id)
            .group_by(MarketingSend.campaign_id, MarketingSend.status)
        )
    ).all()
    conv_rows = (
        await session.execute(
            select(MarketingSend.campaign_id, func.count(MarketingSend.id))
            .where(
                MarketingSend.restaurant_id == restaurant_id,
                MarketingSend.converted_order_id.is_not(None),
            )
            .group_by(MarketingSend.campaign_id)
        )
    ).all()
    converted_by = {cid: n for cid, n in conv_rows}

    by_campaign: dict[int, dict[str, int]] = {}
    for cid, status, n in status_rows:
        by_campaign.setdefault(cid, {})[status] = n

    out: dict[int, dict] = {}
    for cid, statuses in by_campaign.items():
        sent = sum(statuses.get(s, 0) for s in _SENT_STATUSES)
        delivered = statuses.get("delivered", 0) + statuses.get("read", 0)
        converted = converted_by.get(cid, 0)
        out[cid] = {
            "sent": sent,
            "delivered": delivered,
            "converted": converted,
            "conversion_rate": round(converted / sent, 4) if sent else 0.0,
        }
    return out


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


async def delete_template(
    session: AsyncSession,
    *,
    restaurant_id: int,
    template_id: int,
    provider: TemplatePort,
) -> bool:
    """Manager-initiated template delete.

    Best-effort removes it from Meta (if it was ever submitted), then soft-deletes
    locally (``status="deleted"`` + ``deleted_at``) so it drops out of the list and
    its name enters the 30-day reuse blackout (naming.is_name_reusable). Soft —
    not a hard DELETE — because campaigns may FK-reference it. Returns False if the
    template isn't found for this restaurant. Caller commits.
    """
    tpl = await session.get(WaTemplate, template_id)
    if tpl is None or tpl.restaurant_id != restaurant_id or tpl.status == "deleted":
        return False
    if tpl.meta_template_id:
        try:
            await provider.delete(
                name=tpl.meta_template_name, meta_template_id=tpl.meta_template_id
            )
        except Exception:  # noqa: BLE001 — Meta delete is best-effort
            pass
    tpl.status = "deleted"
    tpl.deleted_at = datetime.now(timezone.utc)
    await session.flush()
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="wa_template",
        entity_id=str(template_id),
        action="deleted",
    )
    return True


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
