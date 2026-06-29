import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.models import OutboxMessage
from app.whatsapp.port import OutboundMessageType

# WhatsApp uses *single* asterisks for bold. LLMs (and any Markdown source) emit
# **double** asterisks and `#` headers, which render as LITERAL characters on the
# device ("**Menu**" instead of bold). Normalize those to WhatsApp's flavor so
# replies look right on the phone. Applied to every outbound `body` at the single
# enqueue chokepoint, so it covers AI-generated text and static strings alike.
# NOTE: we deliberately do NOT touch __double_underscores__ — that would mangle
# identifiers/filenames like __init__, and these models emit ** for bold anyway.
_MD_HEADER = re.compile(r"^[ \t]*#{1,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_MD_BOLD_STARS = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def to_whatsapp_text(text: str) -> str:
    """Convert common Markdown to WhatsApp formatting (idempotent)."""
    # '## Title' -> bold line. Do headers first so a header's inner ** is handled
    # by the bold pass below.
    text = _MD_HEADER.sub(r"*\1*", text)
    # '**bold**' -> '*bold*'
    text = _MD_BOLD_STARS.sub(r"*\1*", text)
    return text


async def deliver_pending(session: AsyncSession, restaurant_id: int) -> None:
    """Flush all pending outbox rows for a restaurant (best-effort).

    For request handlers that enqueue notifications but have no event-driven
    delivery of their own (manual dispatch trigger, manual reassign). Without
    this the rows sit ``pending`` until the 5-min orphan sweeper — which doesn't
    run when Celery beat is absent (e.g. Render) — so the messages never send.
    """
    from sqlalchemy import select

    ids = (
        await session.scalars(
            select(OutboxMessage.id).where(
                OutboxMessage.restaurant_id == restaurant_id,
                OutboxMessage.status == "pending",
            )
        )
    ).all()
    await deliver_outbox_now(session, list(ids))


async def deliver_outbox_now(session: AsyncSession, outbox_ids: list[int]) -> None:
    """Deliver freshly-committed outbox rows — synchronously in-request when no
    Celery worker runs (APP_OUTBOX_SYNC_DELIVERY, e.g. Render free tier), else
    hand off to the outbox queue. Shared by the webhook/conversation reply paths
    and event-driven dispatch so rider/manager notifications go out promptly
    instead of waiting on the 5-minute orphan sweeper."""
    if not outbox_ids:
        return
    from app.config import get_settings

    if get_settings().outbox_sync_delivery:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.outbox.worker import _deliver_one
        from app.whatsapp.factory import get_whatsapp_provider

        provider = get_whatsapp_provider()
        factory = async_sessionmaker(
            bind=session.bind,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        for oid in outbox_ids:
            await _deliver_one(oid, provider=provider, session_factory=factory)
    else:
        from app.outbox.worker import deliver_outbox_message

        for oid in outbox_ids:
            deliver_outbox_message.apply_async(args=[oid], queue="outbox")


async def enqueue_message(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    msg_type: OutboundMessageType,
    payload: dict,
    idempotency_key: str,
    mirror_rider_conversation: bool = True,
) -> OutboxMessage:
    """Write an outbox row in the caller's transaction. Commit is the caller's responsibility."""
    body = payload.get("body")
    if isinstance(body, str):
        payload = {**payload, "body": to_whatsapp_text(body)}
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone=to_phone,
        payload={"type": str(msg_type), **payload},
        idempotency_key=idempotency_key,
    )
    session.add(row)
    if mirror_rider_conversation:
        from app.conversation.service import maybe_record_rider_outbound

        await maybe_record_rider_outbound(
            session,
            restaurant_id=restaurant_id,
            to_phone=to_phone,
            msg_type=str(msg_type),
            payload={"type": str(msg_type), **payload},
        )
    return row
