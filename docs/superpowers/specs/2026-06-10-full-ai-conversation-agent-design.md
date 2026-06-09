# Full-AI Conversation Agent — Design Specification

**Date:** 2026-06-10
**Status:** Approved
**Replaces:** Hybrid FSM + AI ordering agent (current)

---

## 1. Overview

Replace the current hybrid FSM/AI customer conversation with a single phase-aware
DeepSeekConversationAgent that owns the entire customer dialogue — from first greeting
to post-order status queries. Rider flow remains FSM (structured buttons/location unchanged).

**Goals:**
- Natural, multi-turn, context-aware conversations (history from DB)
- 7-language support: English, Arabic, Urdu/Hindi, Turkish, Russian, Filipino, Malayalam
- Handle real-world shorthand ("2 bry + karahi", "ek biryani dena bhai", "rm that")
- Returning customer address reuse (no re-capture if saved address exists)
- Friendly + casual tone, light emoji, WhatsApp-native style
- Upsell once per order (natural, not pushy)

---

## 2. Architecture

### 2.1 Conversation Phases

Agent behaviour is governed by `conv.state["dialogue_phase"]` (replaces `dialogue_state`):

| Phase | Trigger | Agent Focus |
|---|---|---|
| `ordering` | New conversation / greeting | Menu Q&A, item collection, upsell |
| `address_capture` | Customer says done / proceed | Location pin → apt/room → building → receiver |
| `awaiting_confirmation` | Address complete | Order summary, confirm / modify / cancel |
| `post_order` | Order confirmed | Status, modification requests, cancellation |

FSM states removed from customer path:
`greeting`, `menu_sent`, `collecting_items`, `address_text_pending`,
`receiver_details`, `order_confirmation`, `modify_items`, `modify_confirm`
→ all handled by AI per phase above.

Rider path: unchanged (location pings, geofence buttons, COD — full FSM).

### 2.2 Data Flow

```
inbound message (text / location / button_reply)
  ↓
load conv + resolve dialogue_phase
  ↓
fetch last 10 messages from DB (inbound + outbound) → build history list
  ↓
build phase-specific system prompt
  (shared identity + phase block + menu/cart/address/order context)
  ↓
DeepSeek function-calling: take_action tool (forced)
  ↓
execute action handler
  (add_item / remove_item / send_location_request / save_address /
   use_saved_address / confirm_order / status_query / no_action / ...)
  ↓
send reply via outbox
  ↓
record_message(direction="outbound")   ← NEW: stored for history
  ↓
update conv.state (phase + draft_order_id + address fields)
```

### 2.3 History Reconstruction

**New:** `_send_text` and `_send_buttons` both call `record_message(direction="outbound")`.
`_build_history(session, conv, limit=10)` fetches last N messages ordered by `ts`, maps:

- inbound text → `{"role": "user", "content": text}`
- outbound text → `{"role": "assistant", "content": body}`
- inbound location → `{"role": "user", "content": "[customer shared location pin]"}`
- inbound button_reply → `{"role": "user", "content": f"[tapped: {title}]"}`
- outbound buttons → `{"role": "assistant", "content": body_text}`

History always starts with a user turn. If first stored message is assistant, prepend a
synthetic `{"role": "user", "content": "hi"}`.

---

## 3. Tool Schema

Single tool `take_action` (forced call). Actions are phase-gated server-side.

```json
{
  "name": "take_action",
  "description": "Structured action + reply for every customer message.",
  "parameters": {
    "action": {
      "type": "string",
      "enum": [
        "add_item",
        "remove_item",
        "update_qty",
        "proceed_to_address",
        "send_location_request",
        "save_address_text",
        "use_saved_address",
        "proceed_to_confirmation",
        "confirm_order",
        "request_modification",
        "cancel_order",
        "status_query",
        "no_action"
      ]
    },
    "dish_query":    "string — dish name/number (add_item, remove_item, update_qty)",
    "qty":           "integer — quantity (add_item, update_qty)",
    "special_note":  "string — kitchen note for this item (add_item)",
    "apt_room":      "string — apartment/room/door number (save_address_text)",
    "building":      "string — building name or number (save_address_text)",
    "receiver_name": "string — name of person receiving order (save_address_text)",
    "reply":         "string — WhatsApp message to send (always required)"
  },
  "required": ["action", "reply"]
}
```

### Phase Guards (server-side)

| Action | Allowed phases |
|---|---|
| add_item, remove_item, update_qty, proceed_to_address | ordering |
| send_location_request, save_address_text, use_saved_address, proceed_to_confirmation | address_capture |
| confirm_order, request_modification, cancel_order | awaiting_confirmation |
| status_query | post_order |
| no_action | all phases |
| cancel_order | ordering, awaiting_confirmation, post_order (before ready) |

If AI returns wrong-phase action: log warning, fall back to `no_action`, send reply.

---

## 4. System Prompt Design

### 4.1 Shared Identity Block (all phases)

```
You are {restaurant_name}'s friendly WhatsApp ordering assistant.

LANGUAGE: Detect the customer's language and reply in the SAME language.
Supported: English, Arabic (عربي), Urdu/Hindi (اردو/हिंदी), Turkish, Russian, Filipino (Tagalog), Malayalam.
If they mix languages, match their mix. Never switch language unless they do.

TONE: Friendly and casual — like a helpful friend taking their order.
Short replies (WhatsApp style). Emoji: use sparingly, only where natural.

RULES:
- COD only (cash on delivery). Never mention card/online payment.
- Delivery ~40 minutes. Max delivery radius from `restaurant.settings["max_radius_km"]`.
- Always call take_action — never reply without it.
```

### 4.2 Ordering Phase Block

```
PHASE: Ordering
MENU:
{menu_text}

CART: {cart_summary | "empty"}

YOUR JOB:
- Greet warmly. Share 2-3 menu highlights, NOT the full menu as a wall of text.
  If customer asks for full menu, show it grouped by category.
- Understand shorthand orders across all languages:
    "2 bry + karahi"  →  add 2 biryani + 1 karahi
    "ek biryani dena bhai"  →  add 1 biryani
    "same as always"  →  ask what they usually have (no saved order context yet)
    "rm that"  →  remove last added item
    "change to 2"  →  update last item qty to 2
    "bas" / "khalaas" / "that's all" / "done"  →  proceed_to_address
- Handle questions: spice level, halal, portion size, ingredients, vegetarian, allergens.
  Max 3 lines per answer. Never include price in dish descriptions.
- Upsell ONCE per order (only if cart has ≥1 item):
    "Want to add a drink or dessert? 😊" — only if not already suggested.
- When cart is not empty and customer indicates they are done → proceed_to_address.
- NEVER ask for address or location in this phase.
```

### 4.3 Address Capture Phase Block

```
PHASE: Address capture
CART: {cart_summary}
SAVED ADDRESS: {saved_address | "none"}

YOUR JOB (in this exact order):
1. If SAVED ADDRESS exists:
   → Offer it: "Use your saved address — Apt {apt}, {building}? Or share a new location?"
   → If customer confirms → use_saved_address
   → If customer wants new → continue with step 2
2. Send location pin request (send_location_request).
   Wait for location pin OR typed address.
3. Once location received → ask: "What's your apartment/room/door number?"
4. Once apt/room received → ask: "Building name or number?"
5. Once building received → ask: "Receiver's name?"
6. Once all 3 collected → save_address_text + proceed_to_confirmation.

RULES:
- Collect ONLY: apt/room, building, receiver name. Nothing else.
- Do NOT ask for phone number, landmark, floor (unless volunteered — then save in apt_room).
- If customer volunteers extra info (e.g., landmark), include it in apt_room field.
- If location pin is outside the restaurant's delivery radius → inform customer and end conversation politely.
```

### 4.4 Awaiting Confirmation Phase Block

```
PHASE: Order confirmation
ORDER SUMMARY:
{order_summary}

YOUR JOB:
- Show full summary: items + quantities, subtotal, delivery fee, total, address, receiver, ETA ~40 min, COD reminder.
- Ask: "Shall I place this order? ✅"
- Customer says yes/confirm/ok/haan/aiwa/да/oo → confirm_order
- Customer wants to change something → request_modification (describe what)
- Customer cancels → cancel_order
- Keep this message clear and scannable (use line breaks, not paragraphs).
```

### 4.5 Post-Order Phase Block

```
PHASE: Order placed
ORDER: #{order_number} — Status: {order_status}
RIDER ETA: {rider_eta | "calculating"}

YOUR JOB:
- Answer status queries: "where is my order", "how long", "کتنا وقت لگے گا"
- If status is preparing/ready: "Kitchen is preparing your order 🍳"
- If rider assigned: "Your rider is on the way! ETA ~{rider_eta} min 🛵"
- Modification requests (only if status is before 'ready') → request_modification
- Cancellation requests → check status first; if cancellable → cancel_order
- If order already picked up: "Sorry, your order is already with the rider — can't cancel now"
```

---

## 5. Returning Customer Flow

```
On entering address_capture phase:
  1. Look up customer by phone in customer_addresses table
  2. If saved address found:
     AI offers: "Use saved address: Apt {apt_room}, {building}? Reply Yes or share new location 📍"
  3. Customer confirms → use_saved_address action → phase = awaiting_confirmation
  4. Customer wants new → send_location_request → normal flow
```

---

## 6. Shorthand & Multi-Language Handling

The system prompt explicitly instructs the AI to handle:

| Input | Interpretation |
|---|---|
| "2 bry n karahi" | add 2 biryani + 1 karahi |
| "ek biryani dena" | add 1 biryani |
| "rm last" | remove last added item |
| "make it 3" | update last item qty to 3 |
| "bas yahi" | that's all / proceed_to_address |
| "khalaas" (Arabic) | done |
| "هات ١ برياني" | add 1 biryani |
| "bhai no onion" | add_item with special_note="no onion" |
| "extra spicy plz" | add_item with special_note="extra spicy" |

---

## 7. Error Handling

| Failure | Behaviour |
|---|---|
| DeepSeek timeout / HTTP error | Friendly fallback: "Sorry, having a moment 😅 Type the dish number to order (e.g. 110)" |
| AI returns invalid action for phase | Log warning, execute `no_action` with AI's reply |
| AI returns unknown action string | Log, treat as `no_action` |
| Dish not found after add_item | AI reply already handles it; server sends "couldn't find X" fallback |
| Location pin outside radius | Detected at pin processing using `restaurant.settings["max_radius_km"]`; AI informed via context; replies politely |
| Missing required fields for save_address_text | Phase stays at address_capture; AI reprompts |
| DeepSeek returns no tool call | Raise RuntimeError, caught by fallback handler |

---

## 8. Implementation Changes

### 8.1 New / Modified Files

| File | Change |
|---|---|
| `src/app/conversation/engine.py` | Replace FSM customer path with phase-aware AI dispatch; add `_build_history()`; store outbound in `record_message` |
| `src/app/llm/deepseek.py` | Rewrite `DeepSeekConversationAgent.respond()` with phase-aware prompt builder; expand tool schema |
| `src/app/llm/port.py` | Add `dialogue_phase` to `ConversationAgentResult`; expand action enum |
| `src/app/conversation/service.py` | Ensure `record_message` accepts direction="outbound" (likely already does) |

### 8.2 State Migration

`conv.state["dialogue_state"]` → `conv.state["dialogue_phase"]`
Backward compat: if `dialogue_phase` absent, map old `dialogue_state` values:
- `greeting` / `menu_sent` / `collecting_items` → `ordering`
- `address_capture` / `address_text_pending` / `receiver_details` → `address_capture`
- `order_confirmation` → `awaiting_confirmation`
- `order_placed` → `post_order`
- `cancelled` / `modify_items` / `modify_confirm` → handle as `post_order` or `ordering`

No migration required — mapping done at runtime in `handle_inbound`.

---

## 9. Testing Strategy (per CLAUDE.md — TDD)

**Unit tests:**
- `_build_history()` — correct role alternation, limit, non-text message summarization
- Phase guard — wrong-phase actions blocked, fallback to no_action
- Prompt builder — correct block injected per phase
- Address collector — all 3 fields required before proceed_to_confirmation

**Integration tests (per language sample):**
- Full flow: greeting → 2-item order → address (new) → confirm → post_order status
- Returning customer: greeting → order → address offered (saved) → confirm
- Shorthand: "2 bry + karahi" → 2 add_item calls
- Upsell: triggered once after first item added
- Cancellation: before ready (allowed) vs after picked_up (blocked)
- Language: Arabic, Urdu, Filipino sample messages routed correctly

**Regression:**
- All existing 33+ conversation engine tests must pass
- Full suite (463 backend tests) must remain green
- Ruff lint clean

---

## 10. Non-Negotiable Business Rules (unchanged)

- COD only
- Max delivery radius: `restaurant.settings["max_radius_km"]` km — enforced at pin processing, NOT hardcoded
- Address: apt/room + building + receiver name (exactly, nothing more mandatory)
- Customer descriptions: max 3 lines, never include price
- STOP keyword → opt-out (checked before AI, unchanged)
- Rider flow → FSM unchanged
- Manual takeover → bot silent (unchanged)
- Audit log on every order state change (unchanged)
- Outbox pattern for all sends (unchanged)
