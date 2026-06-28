# Complaint Ticket System — Design

> **Status:** Design note. Not implemented yet.
> **Date:** 2026-06-28
> **Scope:** Multi-tenant WhatsApp restaurant platform (COD, UAE F&B, own-fleet delivery).
> **Supersedes:** the auto-resolution model in `post-delivery-complaints-analysis.md` §14.
> **Core decision:** Complaints are **human-handled only**. AI never resolves a complaint.

---

## 1. Core Principle

**When a complaint is raised, human invocation is mandatory. The AI does NOT take care of it.**

The bot's only job on a complaint is to **detect it, open a ticket, acknowledge the customer, and hand off to a human**. No AI compensation, no AI judgement, no AI promises. Every resolution is a manager decision.

This is a deliberate simplification of the earlier auto-ladder design: lower risk, no AI-driven payouts, no abuse-by-prompt-injection, clear accountability. The trade-off — every complaint needs manager time — is accepted.

---

## 2. What the AI Does vs What the Human Does

| Step | AI (bot) | Human (manager) |
|------|----------|-----------------|
| Detect complaint intent | ✅ | — |
| Open ticket + link order | ✅ (auto) | — |
| Acknowledge customer ("our team will look into this") | ✅ | — |
| Investigate / judge | ❌ | ✅ |
| Decide resolution | ❌ | ✅ |
| Refund to wallet | ❌ | ✅ |
| Send replacement | ❌ | ✅ |
| Mark resolved | ❌ | ✅ |
| Notify customer of outcome | ✅ (sends the manager's chosen outcome) | manager triggers it |

**Hard rule:** the AI never picks or issues compensation. It only routes and relays.

---

## 3. The Ticket Model

A complaint **is** a ticket. One table, append-only audit.

```
Ticket:
  id
  restaurant_id           (tenant scope — isolation enforced)
  customer_id
  order_id                (the order complained about; nullable if not tied to one)
  channel                 (whatsapp)            # how it came in
  source_message          (the customer's complaint text / voice transcript)
  evidence[]              (photo URLs, voice transcript)   # whatever the customer sent
  category                (optional free tag set by manager: quality | missing | wrong | delivery | rider | payment | other)
  status                  (open -> in_progress -> resolved)   # 3-state FSM
  assigned_to             (manager id; nullable until picked up)
  resolution_action       (none | wallet_refund | replacement | resolved_no_action)
  resolution_amount_aed   (set when wallet_refund)
  replacement_order_id    (set when replacement; FK to the new order)
  resolution_note         (manager's free-text reason)
  created_at, updated_at, resolved_at
  audit[]                 (append-only: every state + action change, who, when)
```

### Ticket status FSM (only 3 states)

```
open  ->  in_progress  ->  resolved
```

- **open** — auto-created by the bot the moment a complaint is detected. Customer already acknowledged.
- **in_progress** — a manager opened/assigned it (optional intermediate; can be skipped).
- **resolved** — manager took a terminal action (one of the three below). Terminal.

No "closed" separate from "resolved" — keep it to three states. Reopening = a new ticket linked to the old one (avoid resurrecting terminal state).

---

## 4. The Manager's Three Actions

Every ticket is resolved by exactly ONE of these. All three set `status = resolved` and write an audit row + customer notification.

### Action 1 — Refund to Wallet
- Credits the customer's **wallet** (store credit) by an amount the manager enters.
- COD reality: there is no card to refund, so refund = wallet credit usable on a future order.
- Sets `resolution_action = wallet_refund`, `resolution_amount_aed = X`.
- Writes a `WalletLedger` entry (see §5).
- Customer notified: "AED X has been added to your wallet as credit. 🙏"

### Action 2 — Send Replacement
- Creates a **new linked order** (the replacement) for the same/affected items, AED 0 to the customer, dispatched normally.
- Sets `resolution_action = replacement`, `replacement_order_id = <new order>`.
- The replacement order flows through the normal kitchen → dispatch → delivery path (and its own SLA).
- Customer notified: "A replacement for your order is on the way. 🛵"

### Action 3 — Mark Resolved (no compensation)
- Closes the ticket with no payout — e.g. misunderstanding, customer satisfied by explanation/apology, or rejected claim.
- Sets `resolution_action = resolved_no_action`, requires a `resolution_note`.
- Customer notified with the manager's message (the bot relays it).

**Every action requires a `resolution_note`** (audit + accountability).

---

## 5. The Wallet (new primitive)

Refund-to-wallet needs a customer wallet. New, minimal, ledger-backed.

```
WalletLedger:                          # append-only; balance = SUM(amount)
  id
  restaurant_id                        # wallet is per-restaurant (tenant-scoped)
  customer_id
  amount_aed                           # +credit (refund) / -debit (used on an order)
  reason                               (complaint_refund | order_redemption | manual_adjust | expiry)
  ticket_id                            (nullable; set when reason = complaint_refund)
  order_id                             (nullable; set when reason = order_redemption)
  created_by                           (manager id / system)
  created_at
```

- **Balance is derived** — `SUM(amount_aed)` for (restaurant_id, customer_id). Never store a mutable balance; derive it (idempotent, audit-safe).
- **Scope: per-restaurant.** Wallet credit at Restaurant A is not spendable at Restaurant B (matches multi-tenant isolation).
- **Spending:** on a future order, wallet credit reduces the COD amount due at the door. Applied in the ordering/confirmation flow (a debit ledger row).
- **Caps / expiry:** optional per-restaurant setting (e.g. credit expires in 90 days → an expiry debit row). Start with no expiry; add later.
- **Never negative:** a debit cannot exceed the current balance.

---

## 6. End-to-End Flow

```
1. Customer (post-delivery): "my biryani was cold"
2. Bot DETECTS complaint intent.
3. Bot AUTO-CREATES Ticket(status=open, order_id=<their last order>, source_message=..., evidence=any photo/voice).
4. Bot ACKNOWLEDGES: "Sorry to hear that 🙏 — our team has been notified and will get back to you shortly."
5. Bot NOTIFIES the manager (WhatsApp + dashboard badge): "New complaint ticket #123 — Order 4567 — 'biryani was cold'."
6. Bot STOPS. It does nothing else. No compensation, no promises.
7. Manager opens ticket #123 in the dashboard (status -> in_progress).
8. Manager investigates (sees order, items, rider, evidence).
9. Manager picks ONE action:
      a. Refund to Wallet (enters AED amount)  -> WalletLedger credit
      b. Send Replacement (creates linked AED-0 order) -> dispatched
      c. Mark Resolved (enters note, no payout)
10. Ticket status -> resolved. Audit row written.
11. Bot RELAYS the outcome to the customer (the manager's chosen message).
```

---

## 7. Manager Dashboard — Tickets Screen (new)

New screen in the React dashboard (`frontend/src/screens/`). Mirrors the existing screen patterns.

- **Ticket list/queue**: open tickets first, sorted newest. Columns: #, customer, order, snippet, age, status.
- **Badge / unread count** in the nav (open ticket count) — managers must see new complaints fast.
- **Ticket detail drawer** (reuse the `OrderDetailDrawer` pattern):
  - customer + order summary (items, total, rider, delivery time)
  - the complaint message + any photo/voice
  - the three action buttons: **Refund to Wallet** / **Send Replacement** / **Mark Resolved**
  - required note field
  - audit timeline
- **Filters**: status (open / in_progress / resolved), date range.
- Wallet balance shown on the customer's profile (`CustomerProfileScreen`).

---

## 8. Backend Shape (fits existing architecture)

New bounded context `src/app/tickets/` (mirrors module conventions):

```
src/app/tickets/
  models.py     Ticket, WalletLedger (SQLAlchemy)
  schemas.py    Pydantic I/O
  service.py    create_ticket, assign, resolve_with_wallet_refund,
                resolve_with_replacement, resolve_no_action, wallet_balance
  router.py     HTTP: GET /tickets, GET /tickets/{id}, POST /tickets/{id}/resolve
```

Wiring:
- **Detection**: conversation engine (`conversation/engine.py`) gains a complaint-intent branch in `post_order` (and a general intercept) → calls `tickets.service.create_ticket` + acknowledges + notifies manager. The bot otherwise does NOTHING else on a complaint.
- **Refund**: `resolve_with_wallet_refund` writes a `WalletLedger` credit + audit (`audit/service.record_audit`, same transaction).
- **Replacement**: `resolve_with_replacement` calls `ordering.service` to create a linked AED-0 order, then dispatch as normal.
- **Customer notify**: all outcomes go through the **outbox** (`outbox/service.enqueue_message`) → respects the WhatsApp 24-hour window (template if outside).
- **Wallet spend**: ordering/confirmation flow applies available wallet balance as a debit ledger row, reducing COD due.
- **Migrations**: `tickets` + `wallet_ledger` tables; register models in BOTH `alembic/env.py` and `tests/conftest.py`; add `trg_<table>_updated_at` triggers per the TimestampMixin convention.
- **Multi-tenant**: both tables carry `restaurant_id`; all queries tenant-scoped via `identity/deps.py:current_restaurant`.
- **Audit**: every ticket state change + every wallet ledger row is auditable (append-only).

---

## 9. Rules & Guardrails

1. **AI never resolves.** Detection + acknowledgement + manager notification only. No AI payout, ever.
2. **Exactly one terminal action** per ticket (wallet refund / replacement / mark resolved).
3. **Every resolution needs a note.** No silent closes.
4. **Wallet balance is derived** from the ledger (never a mutable column).
5. **Wallet is per-restaurant** (no cross-tenant credit).
6. **Wallet never goes negative** — a debit cannot exceed balance.
7. **No double-compensation**: if the SLA auto-coupon already fired for this order, the manager sees that on the ticket and decides accordingly (manual judgement, not auto-blocked).
8. **Idempotent customer notifications** — outbox dedupe; never tell the customer twice.
9. **Reopen = new linked ticket**, never un-resolve a terminal ticket.
10. **Safety-critical complaints** (food poisoning / allergy) still flow as tickets but the dashboard should visually flag them for priority + the manager handles per the restaurant's incident process (out of scope for the three actions; may require external escalation).
11. **Tenant isolation**: a manager only ever sees their own restaurant's tickets and wallets.

---

## 10. What Changes vs the Earlier §14 Process

| Earlier (`post-delivery-complaints-analysis.md` §14) | This design |
|------------------------------------------------------|-------------|
| AI auto-resolves low/med within caps | **AI never resolves** |
| Compensation ladder (6 rungs) | **3 manager actions** |
| Auto vs manager-approval gates | **Always manager** |
| Coupon-centric | **Wallet refund + replacement** |
| Complex DECIDE branch | **Simple ticket queue** |

Simpler, safer, fully human-accountable. The 200 scenarios in `post-delivery-complaints-analysis.md` still apply as the situations a manager will face — they now all resolve through this one ticket flow.

---

## 11. Build Order (TDD per CLAUDE.md)

1. **Models + migrations**: `Ticket`, `WalletLedger` (+ triggers, env.py + conftest.py registration).
2. **Service**: `create_ticket`, `wallet_balance`, the three `resolve_*` functions (each writes audit).
3. **Detection**: complaint-intent branch in the conversation engine → create ticket + ack + manager notify.
4. **Router**: list / detail / resolve endpoints.
5. **Customer notifications** via outbox (24h-window aware).
6. **Wallet spend** in the ordering/confirmation flow.
7. **Dashboard**: Tickets screen + detail drawer + nav badge + wallet on customer profile.
8. **Tests** across the stack (unit → integration → E2E) per the CLAUDE.md testing mandate.

---

*End of design. No code was changed by this document.*
