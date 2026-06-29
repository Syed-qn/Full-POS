"""Utility WhatsApp templates + window-aware customer notifications.

WhatsApp only allows free-form ("session") messages within 24h of the customer's
last inbound message. Outside that window only PRE-APPROVED templates may be sent.
Transactional notices (wallet credit, coupon, complaint resolution) can land
outside the window, so they must fall back to an approved UTILITY template.

``notify_customer`` is the single entry point: it sends a session text when the
customer is inside the 24h window, else the matching utility template — both via
the outbox (idempotent), so dev/mock keeps working and prod stays compliant.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType

_WINDOW_SECONDS = 24 * 60 * 60


# Utility template registry. {{1}}, {{2}}… are positional body variables, filled
# from the ``variables`` list passed to notify_customer (order matters).
UTILITY_TEMPLATES: dict[str, dict] = {
    "wallet_credit_added": {
        "language": "en",
        "category": "utility",
        "body": (
            "Good news! AED {{1}} has been added to your wallet at {{2}}. "
            "It'll be applied automatically on your next order."
        ),
        "var_count": 2,  # amount, restaurant_name
    },
    "coupon_issued": {
        "language": "en",
        "category": "utility",
        "body": (
            "Here's a coupon for you from {{1}}: {{2}} — AED {{3}} off your next order."
        ),
        "var_count": 3,  # restaurant_name, code, amount
    },
    "ticket_resolution": {
        "language": "en",
        "category": "utility",
        "body": "Update on your recent issue at {{1}}: {{2}}",
        "var_count": 2,  # restaurant_name, summary
    },
    "complaint_received": {
        "language": "en",
        "category": "utility",
        "body": (
            "Thanks for reaching out to {{1}}. We've logged your concern and our "
            "team will get back to you shortly."
        ),
        "var_count": 1,  # restaurant_name
    },
}


async def _within_window(session: AsyncSession, *, restaurant_id: int, phone: str) -> bool:
    """True if the customer messaged within the last 24h (session messages allowed)."""
    from app.conversation.models import Conversation, Message

    conv = await session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant_id,
            Conversation.phone == phone,
            Conversation.counterpart == "customer",
        )
    )
    if conv is None:
        return False
    last_in_ts = await session.scalar(
        select(Message.ts)
        .where(Message.conversation_id == conv.id, Message.direction == "inbound")
        .order_by(Message.id.desc())
        .limit(1)
    )
    if not last_in_ts:
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    return (now - int(last_in_ts)) <= _WINDOW_SECONDS


def _template_components(variables: list[str]) -> list:
    return [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in variables],
        }
    ]


async def notify_customer(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
    session_text: str,
    template_key: str,
    variables: list[str],
    idempotency_key: str,
) -> None:
    """Send a customer notification, window-aware. Inside 24h → session text;
    outside → the matching approved utility template. Idempotent via the outbox.
    """
    spec = UTILITY_TEMPLATES.get(template_key)
    if spec is None:
        raise ValueError(f"unknown utility template {template_key!r}")

    if await _within_window(session, restaurant_id=restaurant_id, phone=phone):
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": session_text},
            idempotency_key=idempotency_key,
        )
        return

    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=phone,
        msg_type=OutboundMessageType.TEMPLATE,
        payload={
            "name": template_key,
            "language": spec["language"],
            "components": _template_components(variables),
        },
        idempotency_key=idempotency_key,
    )


async def register_utility_templates(
    session: AsyncSession, *, restaurant_id: int
) -> list[str]:
    """Submit all utility templates for Meta approval (idempotent per tenant).

    Persists a non-ephemeral WaTemplate row per template and calls the template
    provider (Mock auto-approves in dev; Meta in prod). Returns the names submitted
    or already present. Caller commits.
    """
    from app.marketing.models import WaTemplate
    from app.marketing.template_factory import get_template_provider
    from app.marketing.template_port import TemplateSpec

    provider = get_template_provider()
    submitted: list[str] = []
    for name, spec in UTILITY_TEMPLATES.items():
        existing = await session.scalar(
            select(WaTemplate).where(
                WaTemplate.restaurant_id == restaurant_id,
                WaTemplate.meta_template_name == name,
                WaTemplate.language == spec["language"],
            )
        )
        if existing is not None:
            submitted.append(name)
            continue
        tpl = WaTemplate(
            restaurant_id=restaurant_id,
            meta_template_name=name,
            language=spec["language"],
            category="utility",
            body=spec["body"],
            status="draft",
            ephemeral=False,
        )
        session.add(tpl)
        await session.flush()
        result = await provider.create(
            TemplateSpec(
                name=name,
                language=spec["language"],
                category="utility",
                body=spec["body"],
            )
        )
        tpl.meta_template_id = result.meta_template_id
        tpl.status = "approved" if str(result.status) == "approved" else "pending_meta"
        submitted.append(name)
    return submitted
