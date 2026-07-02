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

# E-08: pin priority — policy beats order beats customer beats restaurant beats dish;
# lexical matches are lowest priority.
_KIND_PRIORITY: dict[str, int] = {
    "policy": 0,
    "order": 1,
    "customer": 2,
    "restaurant": 3,
    "dish": 4,
}

# E-08 grounding_block budget caps.
_MAX_GROUNDING_DOCS = 4
_MAX_BODY_CHARS = 200
_MAX_GROUNDING_CHARS = 800


async def retrieve(
    session: AsyncSession,
    *,
    restaurant_id: int,
    query: str,
    customer_id: int | None = None,
    dish_ids: list[int] | None = None,
    order_id: int | None = None,
    limit: int = 6,
    max_docs: int = 4,
) -> list[OkfDoc]:
    """Top OKF docs for ``query``.

    MULTILINGUAL: lexical (pg_trgm) similarity only matches English query terms, so a
    Telugu/Arabic/Urdu question wouldn't retrieve anything. To stay language-agnostic
    we PIN the highest-value grounding by ENTITY id (not text): restaurant + policy +
    this customer + their order + the dishes in their cart — these answer the common
    questions regardless of the message's language. Lexical matches are added on top
    as an English bonus. (Grounding facts are English markdown; the LLM reads them and
    replies in the customer's language.)
    MULTI-TENANT: every branch is scoped by restaurant_id.
    """
    q = (query or "").strip().lower()
    pins: list[OkfDoc] = []
    pin_ids: set[int] = set()

    # Language-agnostic pins: policy + restaurant + this customer + their order +
    # cart dishes — matched by kind/entity_id, NOT by the query's language.
    pin_conds = [OkfDoc.kind == "policy", OkfDoc.kind == "restaurant"]
    if customer_id is not None:
        pin_conds.append((OkfDoc.kind == "customer") & (OkfDoc.entity_id == customer_id))
    if order_id is not None:
        pin_conds.append((OkfDoc.kind == "order") & (OkfDoc.entity_id == order_id))
    if dish_ids:
        pin_conds.append((OkfDoc.kind == "dish") & (OkfDoc.entity_id.in_(dish_ids)))
    pin_rows = await session.scalars(
        select(OkfDoc).where(OkfDoc.restaurant_id == restaurant_id, or_(*pin_conds))
    )
    for d in pin_rows:
        if d.id not in pin_ids:
            pin_ids.add(d.id)
            pins.append(d)

    lexical: list[OkfDoc] = []
    if q:
        # Lexical match via pg_trgm word_similarity (query within doc text).
        sim_rows = await session.execute(
            text(
                "SELECT id FROM okf_docs "
                "WHERE restaurant_id = :rid AND word_similarity(:q, search_text) >= :floor "
                "ORDER BY word_similarity(:q, search_text) DESC LIMIT :lim"
            ).bindparams(q=q, rid=restaurant_id, floor=_MIN_SIM, lim=limit)
        )
        sim_ids = [r[0] for r in sim_rows.all() if r[0] not in pin_ids]
        if sim_ids:
            rows = await session.scalars(select(OkfDoc).where(OkfDoc.id.in_(sim_ids)))
            by_id = {d.id: d for d in rows}
            for sid in sim_ids:  # preserve similarity order
                if sid in by_id:
                    lexical.append(by_id[sid])

    pins.sort(key=lambda d: (_KIND_PRIORITY.get(d.kind, 99), d.id))
    return (pins + lexical)[:max_docs]


def _cite_tag(doc: OkfDoc) -> str:
    """E-20 provenance tag — entity_id when pinned, else stable doc id."""
    ref = doc.entity_id if doc.entity_id is not None else doc.id
    return f"[okf:{doc.kind}:{ref}]"


def _strip_frontmatter(body: str) -> str:
    """Drop YAML frontmatter — it burns budget without adding customer-facing facts."""
    text_body = (body or "").strip()
    if not text_body.startswith("---"):
        return text_body
    end = text_body.find("\n---", 3)
    if end == -1:
        return text_body
    return text_body[end + 4 :].strip()


def _truncate_body(body: str, max_chars: int = _MAX_BODY_CHARS) -> str:
    """Truncate markdown body to ~max_chars, suffixing with ellipsis when clipped."""
    text_body = _strip_frontmatter(body)
    if len(text_body) <= max_chars:
        return text_body
    if max_chars <= 1:
        return "…"
    return text_body[: max_chars - 1].rstrip() + "…"


def grounding_block(docs: list[OkfDoc]) -> str:
    """Render retrieved OKF docs into a prompt-injectable grounding block."""
    if not docs:
        return ""
    header = (
        "GROUNDED KNOWLEDGE (authoritative — answer ONLY from these facts; if the "
        "answer isn't here, say you'll check with the team, NEVER invent). "
        "Cite only [okf:…] tags for factual claims; if none apply, defer to team phone. "
        "These facts are in English; REPLY IN THE CUSTOMER'S LANGUAGE:"
    )
    selected = docs[:_MAX_GROUNDING_DOCS]
    prefixes = [f"\n{_cite_tag(d)} {d.title}\n" for d in selected]
    fixed = len(header) + sum(len(p) for p in prefixes)
    if fixed >= _MAX_GROUNDING_CHARS:
        out = header
        for d in selected:
            prefix = f"\n{_cite_tag(d)} {d.title}\n"
            remaining = _MAX_GROUNDING_CHARS - len(out) - len(prefix)
            if remaining <= 0:
                break
            out += prefix + _truncate_body(d.body, remaining)
        return out[:_MAX_GROUNDING_CHARS]

    body_pool = _MAX_GROUNDING_CHARS - fixed
    per_doc = min(_MAX_BODY_CHARS, max(1, body_pool // len(selected)))

    out = header
    for d, prefix in zip(selected, prefixes):
        out += prefix + _truncate_body(d.body, per_doc)

    if len(out) > _MAX_GROUNDING_CHARS:
        overflow = len(out) - _MAX_GROUNDING_CHARS
        out = out[: _MAX_GROUNDING_CHARS - 1].rstrip() + "…"
        if overflow and not out.endswith("…"):
            out = out[: _MAX_GROUNDING_CHARS - 1].rstrip() + "…"

    return out