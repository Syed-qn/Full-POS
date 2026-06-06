"""Marketing opt-out (STOP keyword) primitives.

``is_stop_keyword`` is a pure matcher. ``record_opt_out`` / ``is_opted_out``
are DB-backed and tenant-scoped (restaurant_id + phone). The caller commits.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.marketing.models import OptOut

# Whole-message matches (stripped + lowercased). English mandatory; Arabic
# ("الغاء" = cancel, "توقف" = stop) included as a nice-to-have.
_STOP_KEYWORDS: frozenset[str] = frozenset(
    {
        "stop",
        "unsubscribe",
        "opt out",
        "optout",
        "stop promo",
        "cancel",
        "الغاء",
        "توقف",
    }
)
# Lenient prefixes so "stop sending the biryani" still triggers.
_STOP_PREFIXES: tuple[str, ...] = ("stop", "unsubscribe")


def is_stop_keyword(text: str) -> bool:
    """True if ``text`` is a marketing opt-out request.

    Case-insensitive and trimmed. Matches when the stripped lowercase message
    exactly equals a keyword OR starts with "stop"/"unsubscribe".
    """
    if not text:
        return False
    normalized = text.strip().lower()
    if not normalized:
        return False
    if normalized in _STOP_KEYWORDS:
        return True
    return any(normalized.startswith(prefix) for prefix in _STOP_PREFIXES)


async def record_opt_out(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
    source: str = "stop_keyword",
) -> OptOut:
    """Idempotently record an opt-out for ``(restaurant_id, phone)``.

    Uses ON CONFLICT DO NOTHING on the unique constraint so calling twice never
    raises. Records an audit row in the same transaction. The caller commits.
    """
    stmt = (
        pg_insert(OptOut)
        .values(restaurant_id=restaurant_id, phone=phone, source=source)
        .on_conflict_do_nothing(index_elements=["restaurant_id", "phone"])
    )
    await session.execute(stmt)

    row = (
        await session.execute(
            select(OptOut).where(
                OptOut.restaurant_id == restaurant_id,
                OptOut.phone == phone,
            )
        )
    ).scalar_one()

    await record_audit(
        session,
        actor=f"customer:{phone}",
        restaurant_id=restaurant_id,
        entity="marketing_opt_out",
        entity_id=str(row.id),
        action="opt_out",
        after={"phone": phone, "source": source},
    )
    return row


async def is_opted_out(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
) -> bool:
    """True if ``phone`` has opted out of marketing for ``restaurant_id``."""
    result = await session.execute(
        select(OptOut.id).where(
            OptOut.restaurant_id == restaurant_id,
            OptOut.phone == phone,
        )
    )
    return result.first() is not None
