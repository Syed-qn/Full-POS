"""Open Knowledge Format (OKF) store.

OKF (https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)
is markdown + YAML-frontmatter concept docs forming a linked knowledge graph. We
store one row per concept (a dish, the restaurant profile, a policy, a customer, an
order) so the conversation bot can RETRIEVE grounded facts and stop hallucinating
the long-tail questions the structured prompt doesn't already cover.

``body`` is the human/agent-readable markdown; ``frontmatter`` is the YAML header as
JSON; ``search_text`` is a flattened, lowercased blob indexed with pg_trgm for
lexical retrieval. The (restaurant_id, kind, slug) triple is the stable identity so
regeneration upserts rather than duplicates.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class OkfDoc(Base, TimestampMixin):
    __tablename__ = "okf_docs"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "kind", "slug", name="uq_okf_docs_rest_kind_slug"),
        Index("ix_okf_docs_rest_kind", "restaurant_id", "kind"),
        # pg_trgm GIN index on search_text is created in the migration (raw SQL).
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    # dish | policy | restaurant | customer | order
    kind: Mapped[str] = mapped_column(String(16), index=True)
    # Stable slug within (restaurant, kind): e.g. "dish-110", "customer-8", "policy".
    slug: Mapped[str] = mapped_column(String(128))
    # Optional FK-ish entity id (dish id / customer id / order id) for targeted recall.
    entity_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)  # markdown concept doc
    frontmatter: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Flattened, lowercased text for pg_trgm lexical retrieval.
    search_text: Mapped[str] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
