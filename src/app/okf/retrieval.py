"""OKF lexical retrieval — find the concept docs most relevant to a customer
message, using pg_trgm word_similarity over search_text (the same engine the dish
matcher uses). No embeddings/vector DB: cheap, deterministic, good for the small
per-restaurant knowledge base. The retrieved docs are injected into the bot prompt
as authoritative grounding so it answers from real facts, not invention.
"""
from __future__ import annotations

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.okf.models import OkfDoc

# pg_trgm similarity floor — below this a doc is irrelevant noise.
_MIN_SIM = 0.2


async def retrieve(
    session: AsyncSession,
    *,
    restaurant_id: int,
    query: str,
    customer_id: int | None = None,
    limit: int = 4,
) -> list[OkfDoc]:
    """Top OKF docs for ``query``. Always includes the restaurant policy + (if given)
    this customer's profile doc, then fills the rest by lexical similarity."""
    q = (query or "").strip().lower()
    picked: dict[int, OkfDoc] = {}
    order: list[int] = []

    # Pinned grounding: policy + this customer's own profile are always relevant.
    pins = await session.scalars(
        select(OkfDoc).where(
            OkfDoc.restaurant_id == restaurant_id,
            or_(
                OkfDoc.kind == "policy",
                (OkfDoc.kind == "customer") & (OkfDoc.entity_id == (customer_id or -1)),
            ),
        )
    )
    for d in pins:
        if d.id not in picked:
            picked[d.id] = d
            order.append(d.id)

    if q:
        # Lexical match via pg_trgm word_similarity (query within doc text).
        sim_rows = await session.execute(
            text(
                "SELECT id FROM okf_docs "
                "WHERE restaurant_id = :rid AND word_similarity(:q, search_text) >= :floor "
                "ORDER BY word_similarity(:q, search_text) DESC LIMIT :lim"
            ).bindparams(q=q, rid=restaurant_id, floor=_MIN_SIM, lim=limit)
        )
        sim_ids = [r[0] for r in sim_rows.all() if r[0] not in picked]
        if sim_ids:
            rows = await session.scalars(select(OkfDoc).where(OkfDoc.id.in_(sim_ids)))
            by_id = {d.id: d for d in rows}
            for sid in sim_ids:  # preserve similarity order
                if sid in by_id:
                    picked[sid] = by_id[sid]
                    order.append(sid)

    return [picked[i] for i in order][: max(limit, 2)]


def grounding_block(docs: list[OkfDoc]) -> str:
    """Render retrieved OKF docs into a prompt-injectable grounding block."""
    if not docs:
        return ""
    parts = [
        "GROUNDED KNOWLEDGE (authoritative — answer ONLY from this; if the answer "
        "isn't here, say you'll check with the team, NEVER invent):",
    ]
    for d in docs:
        parts.append(f"\n[{d.kind}] {d.title}\n{d.body}")
    return "\n".join(parts)
