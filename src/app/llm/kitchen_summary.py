"""Kitchen conversation digest — prompt + structured ground-truth renderer.

Senior prompting pattern for multilingual multi-tenant SaaS:
  Tier 1 (code):  authoritative order rows — never LLM-generated, zero hallucination.
  Tier 2 (LLM):   compress inbound chat into 0–2 net-new kitchen/delivery lines only.
                  No English phrase tables; the model reasons over any language.
"""
from __future__ import annotations

KITCHEN_SUMMARY_MAX_LINES = 3

_TIER2_SYSTEM = """You extract NET-NEW kitchen and delivery instructions for restaurant staff.

You receive:
1) AUTHORITATIVE BLOCK — already shown on the kitchen screen (final cart, prep notes,
   persisted delivery details). Never repeat, contradict, or rephrase anything here.
2) CUSTOMER CHAT — raw inbound WhatsApp messages from this order (any language).

Output 0–2 additional lines ONLY when chat contains prep or delivery instructions
not already covered by the authoritative block.

Omit entirely:
- greetings and acknowledgements
- menu/catalog requests
- availability questions
- bot complaints or confusion
- off-topic questions (location, phone, staffing, unrelated topics)
- repeated ordering attempts that duplicate the authoritative cart

Rules:
- Preserve the customer's original language — never translate.
- One instruction per line. No bullets, quotes, labels, or preamble.
- If nothing net-new exists, output exactly: NONE
"""


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
    chat_block = "\n".join(f"- {t}" for t in inbound_messages if t.strip()) or "(none)"
    return (
        f"AUTHORITATIVE BLOCK:\n{structured_block or '(empty)'}\n\n"
        f"CUSTOMER CHAT (inbound only):\n{chat_block}\n\n"
        "Net-new kitchen/delivery lines (0–2), or NONE:"
    )


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