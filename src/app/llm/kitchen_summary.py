"""Kitchen conversation digest — prompt + structured ground-truth renderer.

Senior prompting pattern for multilingual multi-tenant SaaS:
  Tier 1 (code):  authoritative order rows — never LLM-generated, zero hallucination.
  Tier 2 (LLM):   compress inbound chat into 0–2 net-new kitchen/delivery lines only.
                  No English phrase tables; the model reasons over any language.
"""
from __future__ import annotations

from app.llm.prompts_kitchen import build_tier2_user_prompt

KITCHEN_SUMMARY_MAX_LINES = 3


def render_structured_lines(
    items_rows: list,
    *,
    order_details: str | None = None,
    delivery_details: str | None = None,
) -> list[str]:
    """Tier 1: deterministic digest from persisted order/address fields."""
    lines: list[str] = []
    blob = ""

    item_bits: list[str] = []
    for it in items_rows:
        note = (getattr(it, "notes", None) or "").strip()
        if note:
            item_bits.append(f"{it.qty}x {it.dish_name} — {note}")
            blob += f" {note.lower()}"
        else:
            item_bits.append(f"{it.qty}x {it.dish_name}")
        blob += f" {(getattr(it, 'dish_name', None) or '').lower()}"
    if item_bits:
        lines.append("; ".join(item_bits))

    for detail in (order_details, delivery_details):
        d = (detail or "").strip()
        if not d:
            continue
        low = d.lower()
        if low in blob:
            continue
        lines.append(d)
        blob += f" {low}"

    return lines


def build_tier2_prompt(structured_block: str, inbound_messages: list[str]) -> str:
    """User turn for the tier-2 supplement call."""
    return build_tier2_user_prompt(structured_block, inbound_messages)


def parse_tier2_response(raw: str) -> list[str]:
    """Parse tier-2 LLM output into 0–2 supplement lines."""
    text = (raw or "").strip()
    if not text or text.upper() == "NONE":
        return []
    out: list[str] = []
    for line in text.splitlines():
        cleaned = line.strip().lstrip("•-* ").strip()
        if cleaned and cleaned.upper() != "NONE":
            out.append(cleaned)
    return out[:2]


def clamp_summary_lines(lines: list[str]) -> str | None:
    if not lines:
        return None
    return "\n".join(lines[:KITCHEN_SUMMARY_MAX_LINES])