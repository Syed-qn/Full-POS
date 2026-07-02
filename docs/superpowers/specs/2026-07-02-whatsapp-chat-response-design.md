# WhatsApp Chat Response & Dashboard Mirroring — Design Spec

**Date:** 2026-07-02  
**Status:** Approved  
**Scope:** Unified fix for (A) bot response behavior in `post_order` and (B) dashboard Conversations showing every outbound WhatsApp send to a customer phone.

---

## Problem statement

### Customer-facing (bot)

Production transcript (Syed / Order #R1-0120):

1. Customer confirms order → bot sends confirmation ✅
2. Customer replies **"Ok"** → bot sends *"Sorry, something went wrong on our end 🙏"* ❌
3. Later: duplicate *"The restaurant has started preparing your order."*
4. Customer accepts resale offer with **"Ok"** → *"Yours! Order #R1-0086-RS-SOLD0120"* ✅
5. Customer replies **"Ok"** again → error apology again ❌

Bare acknowledgments in `post_order` are not handled safely. Some turns hit an uncaught exception in `_handle_customer_ai` (before the internal try/except around `agent.respond`), causing the webhook safety net (`_send_error_apology`) to fire.

### Manager-facing (dashboard)

The Conversations screen reads the `messages` table via `GET /api/v1/conversations/{id}/messages`. Not every WhatsApp outbound is recorded:

| Send path | Recorded today? |
|-----------|-----------------|
| Engine `_send_text` / `_send_buttons` / etc. | Yes (`record_message` after `enqueue_message`) |
| Proactive status pings (`_notify_customer_status`) | Yes (manual `_record` mirror) |
| Error apology (`_send_error_apology`) | **No** — outbox only |
| Marketing / coupon / SLA template sends | **No** — outbox only |

Managers see an incomplete thread compared to what the customer received on WhatsApp.

---

## Goals

1. **Contextual LLM replies in `post_order`** — bare acks ("Ok", "Sure", "👍") are interpreted from conversation history, not hardcoded silent/status shortcuts.
2. **Zero false error apologies** — harmless customer messages must not trigger the webhook exception handler.
3. **Dashboard = WhatsApp truth** — every outbound enqueue to a customer phone appears in their Conversations thread (bot, pings, marketing, coupons, errors, templates).

## Non-goals

- Hardcoded silent ignore for bare "Ok" in `post_order`.
- Dashboard pagination or message limits (API already returns all rows).
- Full frontend redesign (only ensure `MessageBubble` renders mirrored payload shapes).
- Changing resale accept semantics (`ok` + pending `resale_offer_id` stays deterministic before LLM).

---

## Architecture

### Outbound mirroring (Approach 1 — mirror at enqueue)

```
Any producer → enqueue_message(to_phone, payload, idempotency_key, ...)
                 ├─ if customer phone → maybe_record_customer_outbound()
                 ├─ if rider phone    → maybe_record_rider_outbound() [existing]
                 └─ OutboxMessage row → delivery worker / sync deliver
```

**New function:** `maybe_record_customer_outbound(session, *, restaurant_id, to_phone, msg_type, payload)`

- Resolve phone via `phone_lookup_values` / `normalize_phone`.
- If phone belongs to a **rider** for this tenant → skip (rider tab owns that thread via existing rider mirror).
- Else `get_or_create_conversation(..., counterpart="customer")` + `record_message(direction="outbound", ...)`.
- **Dedup:** if `enqueue_message` returns an existing row (idempotency hit), skip mirror insert. Optionally key mirror rows with `mirror-{idempotency_key}` stored in payload metadata or check latest outbound with same body+ts window — simplest: only mirror on fresh insert.

**`enqueue_message` changes:**

- Add parameter `mirror_customer_conversation: bool = True`.
- Call `maybe_record_customer_outbound` when True and recipient is not a rider.

**Remove duplicate mirrors:**

- `engine._send_text`, `_send_buttons`, `_send_cta_url`, `_send_location_request` — remove inline `record_message` (enqueue handles it).
- `dispatch/rider_flow._notify_customer_status` — remove `_record` helper; enqueue mirror suffices.
- `_send_error_apology` — no code change beyond benefiting from centralized mirror.

**Payload normalization for dashboard:**

- Keep `message_view_payload()` mapping `body` → `text` for `MessageBubble`.
- Store interactive fields (`buttons`, `button_label`, `url`, template name) in payload as today so future UI can render chips; minimum bar is visible body text.

### LLM contextual responses in `post_order`

**Pipeline (hardened, not replaced):**

```
inbound TEXT
  → deterministic guards (resale accept, tracking, complaint, …)
  → _maybe_offer_resale (unchanged)
  → router classify intent (NON_ACTIONABLE ok — must NOT mutate cart)
  → _try_post_order_item_edit (unchanged)
  → _handle_customer_ai
       → _build_history + _build_context  [NEW: try/except, degrade to empty]
       → agent.respond (updated _POST_ORDER_BLOCK)
       → _dispatch_action
            → no_action + reply → _send_text
            → status_query → _handle_status_query
```

**Prompt update (`_POST_ORDER_BLOCK` in `deepseek.py`, mirror in `claude.py`):**

- Instruct model to read **last assistant message + customer reply** together.
- After a terminal bot message (order confirmed, resale accepted, delivered) and bare ack → `no_action` with short warm close; do not re-confirm or dump full status.
- After proactive status ping and bare ack → brief reassurance OR `status_query` if customer sounds anxious.
- Never emit `confirm_order`, `cart_add`, or cart mutations in `post_order` (phase guard remains backstop).

**Exception hardening (`_handle_customer_ai`):**

```python
try:
    history = await _build_history(...)
    context = await _build_context(...)
except Exception:
    log warning
    history = history or [{"role": "user", "content": text}]
    context = context or {"order_number": "", "order_status": "unknown", ...}
```

Prevents `reverse_geocode_cached` / OKF / DB edge failures from bubbling to webhook rollback + error apology.

**Resale accept (unchanged):**

- `pending resale_offer_id` + `_is_resale_accept(text)` handled **before** LLM at existing guard (~L7737).

**Test doubles:**

- `FakeConversationAgent` `post_order` branch: contextual `no_action` for bare ack after confirm message in history; not blanket `status_query`.

### Frontend (minimal)

- `MessageBubble` already reads `payload.text` (populated by `message_view_payload`).
- Verify rendering for `buttons`, `cta_url`, `location_request` types show at least body text; optional enhancement: render button labels as muted chips (follow-up, not blocking).

---

## Data flow — error path (after fix)

```
handle_inbound throws
  → webhook rollback
  → _send_error_apology (fresh session)
       → enqueue_message(..., mirror_customer_conversation=True)
            → maybe_record_customer_outbound  [NEW]
            → outbox → WhatsApp
```

Manager dashboard now shows the apology the customer received.

---

## Testing plan

| Test file | Test | Asserts |
|-----------|------|---------|
| `tests/conversation/test_ok_post_order.py` | `test_ok_after_order_confirm_no_error_apology` | No "something went wrong" in outbox bodies |
| `tests/conversation/test_ok_post_order.py` | `test_ok_after_confirm_gets_contextual_reply` | Outbound exists; not empty error |
| `tests/conversation/test_outbound_mirror.py` | `test_enqueue_mirrors_customer_once` | Single `messages` row per `_send_text` |
| `tests/conversation/test_outbound_mirror.py` | `test_error_apology_mirrored` | Apology in `messages` after forced webhook error |
| `tests/marketing/...` or new | `test_marketing_enqueue_mirrored` | Marketing send creates conversation outbound |
| `tests/dispatch/test_customer_notifications.py` | `test_status_ping_is_recorded_in_conversation_chat` | Still passes after removing `_record` |

Regression suite: `pytest tests/conversation tests/dispatch/test_customer_notifications.py -v`

---

## Rollout / risks

| Risk | Mitigation |
|------|------------|
| Double-recording during migration | Remove engine `_record` in same PR as enqueue mirror |
| Rider phone collision | Rider check in `maybe_record_customer_outbound` before customer conv |
| LLM still occasionally throws | `_handle_customer_ai` degrade + internal dispatch try/except (existing) |
| Marketing noise in chat thread | Accepted — user chose option B (everything to phone) |

---

## Implementation order (for writing-plans)

1. **PR1 — Outbound mirror centralization** (`outbox/service.py`, `conversation/service.py`, remove duplicates in `engine.py` + `rider_flow.py`, tests)
2. **PR2 — AI hardening + post_order prompts** (`engine.py`, `deepseek.py`, `claude.py`, `fake.py`, tests)
3. **PR3 — Frontend smoke** (optional button chip rendering if body-only insufficient)

---

## Approval

- **User approved:** 2026-07-02 — Sections 1–3 (mirror at enqueue, LLM contextual post_order, scope/non-goals).