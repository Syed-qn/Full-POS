# Consistent, Multilingual Order-Completion Handling — Design

**Date:** 2026-06-30
**Status:** Approved (design), pending implementation plan
**Owner:** AI/conversation layer
**Module:** `src/app/conversation/engine.py`, `src/app/llm/deepseek.py`, `src/app/llm/fake.py`

## Problem

When a customer finishes ordering and signals "that's all" (in any language or
phrasing), the bot inconsistently re-adds the last dish instead of advancing to
delivery-address capture. Observed production transcript:

```
Lemon mint 1            → 1x Lemon mint added! 😊 Anything else?
No that's all           → 1x Lemon mint added! 😊 Anything else?
That's all              → 1x Lemon mint added! 😊 Anything else?
Thats all can't you understand → Got it, 1x Lemon mint added! 😊 Anything else?
Motherfucker that's all → Sorry about that, Syed! ... share your location pin ...
```

The customer repeated "I'm done" four times and only the emphatic/profane
fifth message advanced. This is a decision/action inconsistency, not a wording
problem.

## Root Cause (verified in code)

Three independent failures stack:

1. **Hardcoded English closing guard.** `engine.py` carries a deterministic
   pre-LLM guard (`_is_closing`, `_CLOSING_PHRASES`, `_CLOSING_FILLER`,
   `_normalise_closing`) that bypasses the LLM when a message looks like a
   closing. It fails in production because:
   - `_normalise_closing` keeps only the straight apostrophe `'`. WhatsApp/iOS
     autocorrect emits the curly apostrophe `'` (U+2019), which the regex strips
     to a space, so `"that's all"` becomes `"that s all"` and never matches the
     phrase set.
   - The phrase/filler sets are English plus a few transliterated Arabic tokens.
     They cannot cover the service's actual languages (Arabic, Urdu/Hindi,
     Turkish, Russian, Tagalog, Malayalam, and others). This directly violates
     the multilingual and no-hardcoding requirements.
   - Any extra word ("can't you understand") breaks the exact-set match.

2. **LLM add-bias on terse closings.** When the guard misses, the message reaches
   `DeepSeekConversationAgent`. The system prompt already contains a correct
   FINISHING rule (cart not empty + closing signal → `proceed_to_address`), but
   the ADDING block and the `add_item` enum are presented first, so the model
   defaults to `add_item` on short closings. At `temperature=0.0`, the
   near-identical context produces a byte-identical reply each turn, which reads
   like a canned replay loop but is the model re-deciding `add_item` every time.

3. **Silent quantity inflation (overcharge).** `ordering/service.py:add_item`
   merges into the existing cart line (`existing_line.qty += qty`). Each bogus
   `add_item` therefore incremented the real cart quantity, while the LLM's reply
   text kept saying "1x" (it echoes, it does not read the DB). After the four
   closings above, the persisted cart quantity for Lemon mint is ~4 — the
   customer would be overcharged. The visible "1x" is wrong.

The customer's message **is** given to the LLM: `handle_inbound` records the
inbound message (`engine.py:5073`) before dispatch, so `_build_history` includes
it. The loop is an LLM decision loop amplified by temp-0 determinism, not a
missing-message replay.

## Constraints

- Multi-tenant: per-restaurant prompt variables must stay intact; no tenant
  specifics hardcoded.
- Multilingual: completion intent must work in any language and any phrasing.
- No hardcoding: no English/transliterated phrase tables driving production
  behavior.
- Give the decision to the LLM with the facts it needs, rather than pre-empting
  it with brittle string matching.

## Design

### 1. Remove the hardcoded closing guard

Delete `_is_closing`, `_CLOSING_PHRASES`, `_CLOSING_FILLER`, `_normalise_closing`,
and the bypass block in `_handle_customer_ai` (engine.py ~4673–4687). These
contradict every constraint and mask the real fix. The dish-info deterministic
guard and other unrelated pre-guards are untouched.

### 2. Restructure the ordering prompt — finishing as a first-class decision

In `deepseek.py:_ORDERING_BLOCK`, add an explicit decision order at the top of
the phase block, before ADDING:

- **STEP 1 — completion check.** If the cart is NOT empty and the customer's
  message declines more items, signals they are finished, or expresses
  impatience/frustration that the order is not moving forward — in ANY language
  and ANY phrasing — return `action="proceed_to_address"`. Do not add anything.
- **STEP 2** — only if STEP 1 does not apply, consider add/remove/update/menu/
  question as today.

Add an explicit **anti-re-add rule**: never re-add a dish that is already in the
cart unless the customer names a NEW dish or a number in THIS message. A decline
or a bare "no" is never an `add_item`.

Frame completion as a concept, not a list. Any example phrases are marked
"illustrative only, recognise the same intent in any language." Include the real
failing transcript as a negative example (cart `{1x Lemon mint}` + "No that's
all" → `proceed_to_address`, NOT `add_item`).

### 3. Tighten the tool schema descriptions

In `deepseek.py:_DS_TOOL`:
- `proceed_to_address`: "customer is done, declines more items, or is frustrated
  the order has not moved on — in ANY language."
- `add_item`: "ONLY when the customer NAMES a new dish (or a quantity for one);
  NEVER re-add a dish already in the cart in response to a 'no'/decline."

### 4. Language-agnostic re-add backstop at dispatch

In `_dispatch_action` (engine.py), before executing a single-dish `add_item`:
if the resolved dish is already present in the draft cart AND the customer's
message carried no new dish name and no quantity, treat the action as a no-op
(do not increment; reply gently, e.g. confirm the cart and ask to checkout).

This is a pure conversation-state check — it inspects the cart and the parsed
action, never a phrase table — so it stays multilingual and non-hardcoded. It is
defense in depth: even if the model slips, the cart can never silently inflate.

The exact "no new dish/quantity" signal is taken from the parsed tool call
(empty/whitespace `dish_query` resolving to an existing line via the matcher,
with `qty` absent), not from inspecting raw customer text for keywords.

### 5. Fake agent parity

`fake.py`'s conversation agent (test double) must produce `proceed_to_address`
for generic closing intent so the suite does not depend on the deleted guard.
This logic lives only in the test double, never in production paths.

### 6. Tests (production-representative)

Add/adjust conversation tests so they exercise what production actually sends:

- Curly apostrophe (U+2019): `"No that's all"` → reaches `address_capture`, cart
  quantity unchanged.
- Multilingual closings in native scripts (Arabic, Hindi/Urdu) → same outcome.
- Frustration phrasing ("can't you understand", trailing extra words) → same.
- Regression: repeated closings in a row never increase any cart line quantity
  (guards against the overcharge path).
- The existing `test_negative_reply_advances_and_does_not_re_add` is updated to
  use a curly apostrophe and to assert cart quantity is unchanged after the loop.

## Non-Goals

- No change to LLM provider (stays DeepSeek per prior decision).
- No change to `add_item` merge semantics for legitimate repeat adds.
- No broader refactor of `engine.py` size in this work.

## Success Criteria

- A customer signalling completion in any supported language, with any
  phrasing or apostrophe style, advances to address capture on the first try.
- Repeated closings never increase cart quantities.
- No hardcoded phrase tables drive production completion behavior.
- All existing conversation/ordering tests pass; new representative tests pass.
