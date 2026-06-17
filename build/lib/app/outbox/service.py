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


async def enqueue_message(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    msg_type: OutboundMessageType,
    payload: dict,
    idempotency_key: str,
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
    return row
