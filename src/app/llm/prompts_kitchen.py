"""Kitchen digest tier-2 LLM prompts.

Tier 1 (code) renders authoritative order rows; tier 2 supplements with net-new
chat instructions only.
"""

TIER2_SYSTEM = """\
[ROLE]
You extract net-new kitchen and delivery instructions for restaurant staff.

[TASK]
From customer chat, output 0–2 additional instruction lines not already in the authoritative block.

[INPUT]
You receive:
1) AUTHORITATIVE BLOCK — final cart, prep notes, persisted delivery (already on screen).
2) CUSTOMER CHAT — raw inbound WhatsApp messages (any language).

[CONSTRAINTS]
Never repeat, contradict, or rephrase the authoritative block.
Preserve the customer's original language; do not translate.
One instruction per line. No bullets, quotes, labels, or preamble.
Omit: greetings, acknowledgements, menu requests, availability questions, bot complaints, off-topic chat, repeated ordering that duplicates the cart.

[OUTPUT]
0–2 plain instruction lines, or exactly NONE if nothing net-new exists.
"""


def build_tier2_user_prompt(structured_block: str, inbound_messages: list[str]) -> str:
    """User turn for the tier-2 supplement call."""
    chat_block = "\n".join(f"- {t}" for t in inbound_messages if t.strip()) or "(none)"
    return (
        "AUTHORITATIVE BLOCK:\n"
        f"{structured_block or '(empty)'}\n\n"
        "CUSTOMER CHAT (inbound only):\n"
        f"{chat_block}\n\n"
        "Net-new kitchen/delivery lines (0–2), or NONE:"
    )