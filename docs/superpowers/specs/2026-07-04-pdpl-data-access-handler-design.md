# PDPL Data-Subject-Access Handler — Design

Date: 2026-07-04
Status: approved (user: "yes build the PDPL data access handler")

## Problem

Customer asked "Tell me my data as per local gov rules I want to know what information
you store about me" and got a canned LLM-outage error. Even with the LLM up, the reply
is a generic "call us". UAE PDPL (Federal Decree-Law No. 45 of 2021) grants data
subjects rights of access, correction, and deletion — a restaurant assistant must
answer this deterministically, in any phase, with zero LLM dependency.

## Approach (chosen)

Deterministic intent + static templated reply in the conversation engine, at the same
tier as the other cross-phase deterministic intents (menu request, cart query,
confirm/cancel taps) inside `handle_inbound`'s TEXT dispatch block.

Alternatives rejected:
- LLM-grounded reply (grounding block listing data categories): still dies with the
  provider, non-deterministic wording of a compliance answer.
- Full data export (send actual stored values): heavier, needs PII-safe rendering and
  identity assurance; not required for the access-information right. Future work.

## Components

1. `_is_data_access_request(text) -> bool` — module-level compiled regex, conservative:
   - "my data / my information / my info" (personal-data phrasing)
   - "information|info|data you store|have|keep|collect|hold|save"
   - "what do you know about me"
   - "delete|remove my data|info|information|account|details|number"
   - "privacy policy", "data protection", "personal data", "pdpl", "gdpr",
     "right to access|erasure|be forgotten"
   - Plain "data"/"privacy" alone NEVER triggers (they stay `_RESTAURANT_ON_TOPIC`
     keywords for the LLM path).
2. `_privacy_data_reply(restaurant_name) -> str` — static WhatsApp-formatted reply:
   categories stored (phone + WhatsApp name, addresses/pins, order history — COD, no
   card data, chat history incl. archived summaries, rider GPS retained 30 days per
   spec §6), PDPL rights line, and how to request correction/deletion (reply here /
   call restaurant). English only (deterministic layer; multilingual stays LLM-side).
3. Hook: in `handle_inbound` cross-phase TEXT block, immediately after `text` is
   extracted and before the menu-request check. Replies via `_send_text`
   (prefix `data-access`), mutates NO state, returns. Deletion requests get the same
   reply — it contains the deletion path; automated erasure flow is out of scope.

## Testing

- Unit: detection positives (incl. the exact prod message) and negatives
  ("what's in my cart", "do you have chicken biriyani", "save my address").
- E2E: `handle_inbound` with the prod message → outbox row contains the PDPL reply,
  conversation state unchanged; works mid-ordering phase too.
- Full suite + ruff (standing rule).
