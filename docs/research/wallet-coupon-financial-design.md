# Wallet & Coupon System — Financial-Grade Design for Multi-Tenant SaaS

> **Status:** Design + research note. Not implemented yet.
> **Date:** 2026-06-28
> **Scope:** Multi-tenant WhatsApp restaurant platform — many restaurants (tenants), each with many customers. COD, UAE F&B, own-fleet delivery.
> **Related:** `complaint-ticket-system-design.md` (the wallet refund action), `post-delivery-complaints-analysis.md`, `loyalty-program-analysis.md`.
> **Goal:** Implement customer wallets (for complaint refunds) and coupon codes with **financial-grade correctness and abuse resistance**, modeled on how banks/fintechs run money.

---

## 1. The Core Problem

We are about to store and move **money-like value** (wallet credit, coupon discounts) for **many tenants × many customers**. The moment value is stored, you inherit every problem a bank has: double-spend, reconciliation, fraud, disputes, idempotency, liability, audit, regulatory exposure.

Restaurant SaaS naïve approach: `customer.wallet_balance` integer column, `UPDATE balance = balance - x`. **This is how you lose money.** Race conditions double-spend it, a failed request leaves it inconsistent, there is no audit, no reconciliation, and abuse is invisible.

This doc applies the **fintech playbook** instead.

---

## 2. How Top Financial Institutions Handle It (the principles we copy)

### 2.1 Double-entry, append-only ledger (NOT a balance column)
Banks never store "your balance" as a mutable number. They store an **immutable journal of entries**; the balance is **derived** by summing entries. Every movement is two (or more) entries that **net to zero** across accounts — money is conserved, never created or destroyed, only moved.

- **Append-only**: rows are never updated or deleted. A mistake is fixed with a **reversing entry**, not an edit.
- **Balance = SUM(entries)** for an account. Always reconstructable, always auditable.
- **Double-entry**: a wallet credit from a complaint is `+X to customer wallet` AND `-X from the restaurant's goodwill/expense account`. Both sides recorded. Nothing appears from nowhere.

### 2.2 Idempotency keys on every money operation
Every write that moves value carries a client-supplied **idempotency key**. Replays (network retry, webhook redelivery, double-click) with the same key return the **same result** and do NOT move money twice. (Stripe/Adyen do exactly this — you already use this pattern in `outbox` + `webhook`.)

### 2.3 Atomic, isolated transactions
Balance check + debit happen in **one DB transaction** with proper isolation (or row-level locking / optimistic concurrency). No "read balance, then write" gap where two requests both pass the check. Banks use serializable-equivalent guarantees on the ledger.

### 2.4 Reconciliation
Every day, **independently re-sum** the ledger and compare to control totals. Any drift = a fixable, alertable discrepancy. (You already reconcile COD cash per rider shift in `cod/service.py` — same discipline, applied to wallets.)

### 2.5 Authorization vs capture (hold model)
For pending spends, banks **authorize (hold)** funds, then **capture** later. For us: when wallet credit is applied to an order, **hold** it; **capture** on delivery; **release** the hold if the order cancels. Prevents spending the same credit twice on two simultaneous orders.

### 2.6 Segregation of duties + maker-checker
The person who initiates a high-value movement is not the one who approves it. For us: large manual wallet adjustments need a second approval (or are capped). Limits insider fraud.

### 2.7 Immutable audit + non-repudiation
Who did what, when, why — append-only, tamper-evident. Every entry traces to an actor (manager id / system) and a cause (ticket id / order id). You already have `audit/service.record_audit`.

### 2.8 Limits, velocity checks & anomaly detection
Per-transaction, per-day, per-account caps. Velocity rules (X refunds in Y hours → flag). Anomaly scoring. Banks decline/flag before money moves, not after.

### 2.9 Money is integer minor units
Never floats. Store **fils** (AED minor unit, 1 AED = 100 fils) as integers, or `Numeric(_, 2)` Decimals — never `float`. (You already use `Numeric(8,2)`/`Decimal` for money — keep that, but integer-minor-unit is the bank-grade default.)

### 2.10 Tenant fund isolation
In a multi-tenant SaaS each restaurant's liability is **its own**. Customer wallet credit at Restaurant A is Restaurant A's liability and is spendable only there. No cross-tenant pooling, no cross-tenant leakage. Reconcile per tenant.

---

## 3. Wallet Design (ledger-based)

### 3.1 Model

```
WalletAccount:                              # one per (restaurant, customer); identity only, no balance
  id
  restaurant_id                             # tenant scope
  customer_id
  status                                    (active | frozen)   # frozen = abuse hold, no spend
  created_at, updated_at
  UNIQUE(restaurant_id, customer_id)

WalletEntry:                                # append-only journal. balance = SUM(amount_fils)
  id
  account_id                                (FK WalletAccount)
  restaurant_id                             # denormalized for tenant-scoped queries + reconciliation
  amount_fils                               # +credit / -debit (integer minor units)
  type                                      (refund_credit | order_debit | hold | hold_release |
                                             manual_adjust | expiry | reversal | promo_credit)
  status                                    (posted | held)     # held = authorized not captured
  idempotency_key                           UNIQUE              # dedupe replays
  ticket_id                                 (nullable)          # cause: complaint refund
  order_id                                  (nullable)          # cause: spend/hold on an order
  reverses_entry_id                         (nullable)          # this entry reverses that one
  reason_note                               # human reason (required for manual_adjust)
  created_by                                (manager id | "system")
  created_at                                # never updated
```

### 3.2 Rules
- **Balance = SUM(amount_fils WHERE status='posted')** for an account. Held entries reduce *available* balance but aren't captured.
- **Available = posted_sum − active_holds.**
- **Never negative**: a debit/hold cannot exceed available balance (checked inside the txn).
- **Per-restaurant**: wallet is tenant-scoped; never spendable across tenants.
- **Append-only**: corrections are **reversal** entries (`type=reversal`, `reverses_entry_id=...`), never edits/deletes.
- **Idempotent**: every entry has a unique `idempotency_key`; replay returns the existing entry.
- **Double-entry counterpart**: each `refund_credit` to a customer is mirrored by a restaurant liability/expense entry (so the tenant's books balance — see §6 reconciliation).

### 3.3 Spend flow (hold → capture, bank-style)
```
1. Order created, customer wants to use wallet:
   -> WalletEntry(type=hold, status=held, amount=-X, order_id, idempotency_key=order:hold:<order_id>)
      (fails if available < X)
2. Order delivered (COD collected on the remainder):
   -> WalletEntry(type=order_debit, status=posted, amount=-X, order_id, idem=order:capture:<order_id>)
   -> release the hold (hold_release +X) so it nets correctly
3. Order cancelled before delivery:
   -> WalletEntry(type=hold_release, +X, order_id, idem=order:release:<order_id>)  # credit returns to available
```
This guarantees the same credit can't be spent on two concurrent orders, and cancellations return the credit cleanly.

### 3.4 Lifecycle edges
- **Expiry**: optional per-restaurant (e.g. 90 days). Expiry = a debit entry (`type=expiry`) for the unused credit, on a scheduled sweep (Celery beat). Breakage (expired unused credit) is reported.
- **Freeze**: abuse → `WalletAccount.status=frozen` blocks spend (and optionally credit) pending review.
- **Refund-of-refund**: customer cancels an order that was paid with wallet → credit returns via hold_release / reversal, never a cash payout (COD).
- **Cash-out**: NOT supported. Wallet credit is store credit, never withdrawable to cash (avoids it becoming stored-value/e-money that may trigger UAE financial regulation — see §7).

---

## 4. Coupon Design

### 4.1 Two kinds of coupon
1. **Single-use apology/refund coupon** (already exists, `coupons/models.py`) — minted per incident, unique code, tied to a customer+order.
2. **Campaign coupon** (marketing) — a code or rule redeemable by many customers under constraints.

### 4.2 Model (generalize the existing one)
```
Coupon:
  id
  restaurant_id                     # tenant scope — codes unique PER TENANT, not globally
  code                              # see §4.3 generation
  kind                              (single_use | multi_use)
  discount_type                     (fixed_fils | percent)
  discount_value                    # fils or percent
  max_discount_fils                 # cap for percent coupons (prevent huge catering blowups)
  min_order_fils                    # eligibility floor
  applies_to                        (whole_order | delivery_fee | specific_dishes)
  per_customer_limit                # times one customer may use it
  total_redemption_limit           # global budget cap (units)
  redeemed_count                    # derived/locked counter
  valid_from, expires_at
  status                            (active | paused | exhausted | expired)
  customer_id                       (nullable; set for single_use targeted)
  created_by, created_at

CouponRedemption:                   # append-only ledger of uses (THE source of truth for limits)
  id
  coupon_id, restaurant_id, customer_id, order_id
  discount_applied_fils
  idempotency_key                   UNIQUE
  created_at
```

### 4.3 Code generation (anti-guessing)
- **High entropy**: ≥ enough random bits that brute force is infeasible (e.g. `SORRY-<base32 of 6+ random bytes>`). The existing `secrets.token_hex(3)` (24 bits) is **too weak** for guessable value — increase entropy.
- **Tenant-namespaced**: code unique per restaurant, not globally (two restaurants can both have "WELCOME10").
- **No sequential/predictable codes.**
- **Rate-limit redemption attempts** per customer/phone (you have `ratelimit/`) → blocks code-guessing.
- **Single-use codes** validated against the redemption ledger, not a mutable flag, to survive races.

### 4.4 Redemption rules (enforced atomically)
- Validate: exists, active, not expired, within `valid_from`, customer eligible, order meets `min_order_fils`, under `per_customer_limit` and `total_redemption_limit`.
- **Atomic**: the limit check + the redemption insert happen in one transaction with locking (or a unique constraint that makes the over-limit insert fail). No "check then insert" gap.
- **Idempotent**: replay with the same key returns the same redemption, doesn't double-count.
- **Stacking policy**: explicit — can coupon + wallet + tier-perk combine? Default: **one coupon per order**, wallet applies after coupon, caps enforced.

---

## 5. Abuse Prevention (the misuse problem)

| Abuse | Defense |
|-------|---------|
| Double-spend wallet (concurrent orders) | Hold model + atomic txn + available-balance check |
| Replay / double-click moves money twice | Idempotency key on every entry |
| Coupon code guessing | High entropy + per-tenant namespace + redemption rate-limit |
| Coupon shared publicly | Single-use via redemption ledger; per-customer + global caps |
| Serial complaint → refund farming | Velocity flag (X refunds / Y days) → freeze account, manager review |
| Multi-account (many phones, one person) | Device/address/phone clustering signals; first-refund caps for new accounts |
| Staff issuing refunds to friends | Maker-checker on large adjusts; every entry has `created_by` + audit; anomaly report |
| Rider+customer collusion (fake non-delivery) | Proof-of-delivery (GPS+photo); refunds need a ticket + manager, never auto |
| Refund-then-reorder loop for bonuses | Track lifetime refund ratio per customer; cap |
| Negative balance via race | Never-negative invariant enforced in txn |
| Promo budget drain | `total_redemption_limit` hard cap + kill switch (pause coupon) |
| Cross-tenant credit leak | Tenant-scoped accounts; all queries filtered by restaurant_id |
| Prompt injection → AI grants money | AI NEVER moves money (per ticket design) — human-only |
| Backdated/manual order farming | Manual entries flagged, audited, capped, reviewed |
| Currency/rounding exploit | Integer minor units; consistent rounding rule |

### Velocity / anomaly rules (start simple)
- Per-customer: max N refunds per 30 days; max AED total refund per 30 days.
- Per-customer lifetime: refund ratio (refunds / orders) above threshold → flag.
- New-account: lower refund cap for first K orders.
- Per-tenant: daily compensation budget; breach → alert + auto-pause auto-paths.
- All flags surface on the ticket + customer profile; managers decide.

---

## 6. Multi-Tenant Reconciliation & Reporting

- **Per-tenant liability**: outstanding wallet balance = SUM(posted entries) per restaurant = the AED that restaurant owes its customers. Reported on the dashboard.
- **Daily reconciliation job** (Celery beat): independently re-sum each tenant's wallet ledger + coupon redemptions; compare to control totals; alert on drift. Mirrors `cod/service.py` shift reconciliation.
- **Breakage report**: expired unused wallet credit + unredeemed coupons (a credit back to the restaurant).
- **COD interaction**: an order paid partly by wallet → rider collects only the remainder; the end-of-day cash sheet must reconcile (wallet debit + cash collected = order total).
- **Audit exports**: per-tenant, append-only, for the restaurant's own books.
- **Isolation guarantee**: a tenant can never see/affect another tenant's wallets, coupons, or ledgers.

---

## 7. Regulatory & Legal (UAE context — flag, get counsel)

- **Stored value risk**: a wallet that can be **cashed out** can be classified as stored-value/e-money and may fall under UAE Central Bank / financial regulation. **Mitigation: store credit only, non-withdrawable, usable only for orders.** Document this clearly.
- **PDPL**: wallet/coupon/complaint data is personal data — consent, retention, erasure, access requests.
- **Consumer protection**: refund/credit terms must be disclosed; expiry of paid-for vs goodwill credit may be treated differently.
- **Tax/VAT**: discounts and credits affect the VAT base — the restaurant's accounting must reflect it; expose the data.
- **Per-tenant terms**: each restaurant may need its own wallet/coupon T&Cs surfaced to customers.

> This section is a **flag, not legal advice.** Engage UAE counsel before launching stored value.

---

## 8. Architecture Fit

New bounded contexts (mirror existing module conventions: `models/schemas/service/router`):
```
src/app/wallet/      WalletAccount, WalletEntry; balance/hold/capture/refund/expiry service
src/app/coupons/     EXTEND: generalize Coupon + add CouponRedemption ledger
```
- **Money ops** go through services only; routers never touch ledgers directly.
- **Idempotency keys** plumbed from callers (ticket resolve, order confirm, webhook).
- **Atomic txns** with row locking / unique constraints for limit + balance invariants.
- **Audit**: every entry → `audit/service.record_audit` in the same transaction.
- **Notifications**: outbox (24h-window aware), idempotent.
- **Beat jobs**: wallet expiry sweep, daily reconciliation (apps/workers).
- **Migrations**: new tables register in `alembic/env.py` + `tests/conftest.py`; `trg_<table>_updated_at` triggers per convention.
- **Multi-tenant**: `restaurant_id` on every table; tenant-scoped via `identity/deps.py`.

---

## 9. 200+ Real-World Questions

Grouped by theme. Each needs a defined answer in product + code. Treat as a requirements + adversarial-test checklist.

### A. Wallet — Money Model & Correctness (1–25)
1. Is the balance a stored column or derived from a ledger? (must be derived)
2. What's the minor unit — fils integers or Decimal AED?
3. How is a balance computed — SUM of which entry statuses?
4. What is "available" vs "posted" balance?
5. Can a wallet ever go negative? How is that prevented?
6. Two orders try to spend the same credit at once — what stops double-spend?
7. A refund request is retried (network) — does it credit twice?
8. A webhook redelivers — does it move money twice?
9. How is a mistaken entry corrected — edit or reversal?
10. Is every entry traceable to a cause (ticket/order) and an actor?
11. What happens to a hold if the order never completes?
12. What releases a hold on cancellation?
13. Capture timing — on delivery or on order placement?
14. Rounding rule when wallet partially covers an order?
15. Is the double-entry counterpart (restaurant expense) recorded?
16. Can the ledger be reconstructed after a DB restore?
17. How do we detect drift between ledger sum and expected?
18. Concurrency control — locking, serializable, or optimistic?
19. What isolation level do money transactions run at?
20. How are partial failures (credit ok, notify fails) handled?
21. Is a credit + its audit row written in ONE transaction?
22. Can two managers refund the same ticket simultaneously?
23. What's the idempotency key format for each money op?
24. How long are idempotency keys retained?
25. How are floating-point bugs structurally prevented?

### B. Wallet — Lifecycle & Customer (26–50)
26. When does wallet credit expire (if ever)?
27. Is goodwill credit treated differently from paid-in credit?
28. How is the customer notified of a new credit?
29. How does a customer check their balance via WhatsApp?
30. Can a customer have wallets at multiple restaurants? (yes, separate)
31. Customer changes phone — does the wallet follow them?
32. Two people share a phone — whose wallet?
33. Customer deletes account (PDPL) — what happens to credit?
34. Can credit be transferred between customers? (default no)
35. Can credit be gifted? (default no)
36. Credit applied, order cancelled — credit returns how?
37. Credit applied, order modified up/down — recompute?
38. Credit exceeds order total — leftover stays in wallet?
39. Order total is fully covered by credit — COD collects AED 0 cleanly?
40. Partial coverage — rider collects exact remainder?
41. Credit about to expire — do we warn? Within the 24h window?
42. Customer disputes a debit they don't recognize — statement?
43. Can a customer get a full transaction history?
44. Credit issued in error — clawback path?
45. Restaurant offboards the platform — outstanding credit honored by whom?
46. Customer inactive 1 year — does credit lapse?
47. Multiple credits, partial spend — FIFO, LIFO, or pooled? (pooled sum)
48. Negative experience → credit, then they never return — breakage.
49. Credit shown in which currency/format to the customer?
50. Localized balance messages (EN/AR/UR)?

### C. Wallet — Refund Origination (Tickets) (51–70)
51. Who can issue a wallet refund? (manager only)
52. Is there a max refund amount per ticket?
53. Does a large refund need a second approval (maker-checker)?
54. Can the AI ever issue a refund? (no, never)
55. Must every refund cite a ticket + reason?
56. Refund amount > order total — allowed?
57. Refund on an order already compensated by SLA coupon — double-pay guard?
58. Refund after the customer already ate the food — manager judgement?
59. Refund for a non-delivery dispute without proof — policy?
60. Refund split across multiple complaints on one order?
61. Manager fat-fingers the amount — reversal path?
62. Refund issued, then customer's complaint proven false — claw back?
63. Refund to a frozen (abuse-flagged) account — blocked?
64. Refund in a closed-restaurant period — queued?
65. Bulk refund for a kitchen-wide incident (many orders) — tooling?
66. Refund vs replacement — manager picks which; can they do both?
67. Catering order refund — partial by tray?
68. Refund triggers VAT/accounting adjustment — recorded?
69. Refund notification fails to deliver — retried idempotently?
70. Audit: can we prove who approved every refund?

### D. Coupons — Generation & Validity (71–95)
71. How are codes generated — entropy level?
72. Are codes unique per tenant or globally?
73. Can two restaurants reuse the same human code (WELCOME10)?
74. Single-use vs multi-use — how enforced?
75. Fixed-amount vs percentage — both supported?
76. Percentage coupon on a huge order — is there a max cap?
77. Minimum order value to qualify?
78. Applies to whole order, delivery fee, or specific dishes?
79. Valid-from / expiry windows — timezone (Asia/Dubai)?
80. Per-customer usage limit?
81. Global redemption budget cap?
82. What marks a coupon exhausted?
83. Can a coupon be paused mid-campaign (kill switch)?
84. Can a coupon be edited after issue — or only reissued?
85. Stacking: coupon + wallet + tier perk — allowed combo?
86. Coupon + free-delivery tier on one order — double benefit?
87. Coupon applied pre- or post-discount on earning/loyalty?
88. Coupon on a catalog order — supported?
89. Coupon expiry during an active order conversation?
90. Targeted single-use coupon used by the wrong customer?
91. Coupon value > order total — refund difference or cap?
92. Currency/rounding on percentage coupons?
93. Coupon on COD — reduces cash collected correctly?
94. Coupon issued by SLA breach vs by marketing — same model?
95. How is a coupon linked to the order it was used on?

### E. Coupons — Redemption Correctness (96–115)
96. Limit check + redemption insert — atomic?
97. Two orders redeem a single-use coupon at once — what wins?
98. Replay of a redemption — idempotent?
99. Customer cancels an order that used a coupon — coupon returns?
100. Customer modifies order below min after redeeming — revoke?
101. Coupon redeemed, order auto-cancelled by SLA — coupon state?
102. Redemption attempted on an exhausted coupon — clear error?
103. Redemption attempted past expiry — clear error?
104. Brute-force redemption attempts — rate limited/locked?
105. Redemption ledger is the source of truth, not a flag — enforced?
106. Per-customer limit hit — exact error to the customer?
107. Global cap hit mid-redemption race — last one rejected cleanly?
108. Coupon discount recorded per redemption for reporting?
109. Coupon applied by manager manually vs by customer — same ledger?
110. Coupon reversal when an order is refunded too — don't double-credit?
111. Coupon on a replacement (AED-0) order — disallowed?
112. Coupon redemption across two devices/sessions — race?
113. Partial redemption (use part of a percentage)? (n/a — define)
114. Coupon fine print surfaced before the customer commits?
115. Coupon redemption audited with actor + cause?

### F. Abuse, Fraud & Velocity (116–145)
116. Same person, many phones, each claiming new-customer coupon?
117. Serial complainer farming refunds — detection threshold?
118. Refund ratio (refunds/orders) cap per customer?
119. New-account lower refund cap for first K orders?
120. Per-day per-tenant compensation budget + auto-pause?
121. Staff issuing refunds/coupons to themselves or friends?
122. Maker-checker on adjustments above a threshold?
123. Rider+customer collusion on fake non-delivery refunds?
124. Coupon code leaked on social media — single-use saves us?
125. Multi-account clustering signals (phone/address/device)?
126. Velocity: X refunds in Y hours → freeze + review?
127. Account freeze — blocks spend, credit, or both?
128. Promo budget drain by bots — global cap + monitoring?
129. Backdated manual orders to hit an expired promo?
130. Refund-then-reorder loop for first-purchase bonuses?
131. Negative-balance exploit via concurrent debits?
132. Prompt injection trying to make the bot grant credit?
133. Chargeback-equivalent on COD (there is none) — fake "I paid" claims?
134. Anomaly: a customer's comp spikes vs their history — flag?
135. Cross-tenant attempt to spend Restaurant A credit at B?
136. Manager colludes across tenants — platform-level detection?
137. Reused/old evidence photo across complaints?
138. Coupon guessing via sequential codes — entropy defense proven?
139. How fast can we kill a compromised coupon globally?
140. Are all money ops rate-limited per customer/phone?
141. Insider DB tampering — append-only + tamper-evidence?
142. Are reversals themselves auditable and bounded?
143. Sudden 100x earning/discount misconfig — guardrail?
144. Do we alert on abnormal redemption velocity per coupon?
145. Is there a documented fraud-response runbook?

### G. Multi-Tenant, Liability & Reconciliation (146–170)
146. Is wallet liability tracked per tenant?
147. Can a restaurant see its total outstanding credit (AED)?
148. Daily reconciliation job — does it re-sum independently?
149. What's the alert when ledger drift is detected?
150. Breakage report (expired credit, unredeemed coupons)?
151. COD cash sheet reconciles with wallet debits?
152. Rider collects remainder after wallet — sheet balances?
153. Per-tenant coupon spend vs budget reporting?
154. Tenant isolation — query-level enforcement on every table?
155. One tenant's bug can't corrupt another's ledger?
156. Platform-funded vs tenant-funded promo — who's debited?
157. Tenant offboarding — settle outstanding liability how?
158. Tenant plan downgrade — is wallet a gated feature?
159. Per-branch wallets if a tenant has multiple locations?
160. Bulk import of an existing wallet/credit list?
161. Export per-tenant ledger for the restaurant's accountant?
162. VAT impact of credits/discounts surfaced per tenant?
163. Currency is always AED — any multi-currency need?
164. Reconciliation across wallet + coupon + COD + SLA coupon?
165. Manager dashboard: liability + redemption + breakage KPIs?
166. Reporting: refund rate by dish/rider/time?
167. Audit retention period per tenant (PDPL vs accounting)?
168. Can the platform produce a per-tenant financial statement?
169. Settlement: does the platform ever hold tenant money? (avoid)
170. Are tenant ledgers logically (or physically) partitioned?

### H. Engineering, Idempotency & Operations (171–190)
171. Idempotency key format + storage + TTL?
172. Are all money writes in a single DB transaction with audit?
173. Locking strategy for balance/limit invariants?
174. What isolation level for the ledger?
175. Outbox notifications for money events — idempotent?
176. Replay safety against webhook + Celery retries?
177. Migration: tables in env.py + conftest.py + triggers?
178. How is the hold/capture/release flow tested (concurrency tests)?
179. Property-based tests for "money is conserved"?
180. Load test: concurrent redemptions / refunds?
181. Graceful failure if Redis/DB down mid-op?
182. Backfill/repair tooling if drift is found?
183. Feature flag / kill switch per money feature?
184. Observability: metrics on refunds, redemptions, holds, drift?
185. Alerting thresholds wired to which channel?
186. Rollback plan if a money bug ships?
187. Data model versioning for the ledger?
188. Are reversals the ONLY correction mechanism?
189. Is there a "money operations" service boundary (no router shortcuts)?
190. Disaster recovery: can balances be rebuilt from the journal alone?

### I. Customer Experience, Legal & Edge (191–215)
191. How does a customer see balance + history in WhatsApp?
192. Localized money messages (EN/AR/UR)?
193. Credit applied silently — does the customer perceive the value?
194. Clear mental model: wallet vs coupon vs loyalty points?
195. Stored value cash-out — supported? (no, by design)
196. Could the wallet trigger UAE e-money/stored-value regulation?
197. PDPL: consent, retention, erasure for wallet/coupon data?
198. Consumer-protection disclosure of credit/expiry terms?
199. Per-tenant T&Cs surfaced to customers?
200. Tax/VAT treatment of credits and discounts?
201. Refund expiry of goodwill vs paid credit — legal difference?
202. Customer demands cash instead of credit — policy + script?
203. Customer disputes a wallet transaction formally — process?
204. Customer requests full data export of their financial history?
205. Dormant credit — escheatment/unclaimed-property concerns?
206. Credit issued near tenant offboarding — disclosure to customer?
207. Coupon/credit used as bait-and-switch — compliance?
208. Accessibility of balance info for all customers?
209. Manager messaging templates approved by Meta (WhatsApp)?
210. Outside-24h-window money notifications need paid templates?
211. Customer marks money messages as spam — quality risk?
212. STOP/opt-out vs still needing to receive a refund notice?
213. Birthday/promo credit consent basis?
214. Cross-border customer (UAE number abroad) — any difference?
215. Sunset of the wallet/coupon program — wind-down + honor outstanding?

---

## 9b. Redemption Flow & Duplicate-Redeem Prevention

This is the core fintech problem. **Never trust a flag or a counter you `UPDATE`.** Use the database to make duplicates *impossible*, not just unlikely.

### How customers redeem

**Wallet credit — auto-applied, no code typing.**
Wallet is keyed by `(restaurant_id, phone)` — the phone IS the wallet key, so the customer never "enters" anything.

```
1. Customer orders as normal via WhatsApp.
2. At confirmation, system checks wallet AVAILABLE balance for this (restaurant, phone).
3. If credit exists -> auto-apply (or ask "You have AED 20 credit — use it? yes/no").
4. Order total AED 60, wallet covers AED 20 -> bot: "AED 20 credit applied. Pay AED 40 cash on delivery."
5. Rider collects only the AED 40 remainder.
```
No code, no copy-paste, no typing-error surface.

**Coupon — customer sends the code.**
```
1. Customer types the code in chat: "WELCOME10".
2. Bot validates (exists, active, not expired, eligible, under per-customer + global limits).
3. Applies discount, shows new total, collects the reduced COD amount.
```

### The five duplicate-redeem defenses

**Defense 1 — Redemption ledger + UNIQUE constraint (the real guarantee).**
Don't "check if used, then mark used" — that read-then-write gap is exactly where double-redeem lives. Instead **insert a redemption row** and let a UNIQUE constraint reject the second one. The check IS the insert, so it cannot be raced.
- Single-use coupon: `UNIQUE(coupon_id)` → the second redemption INSERT fails, hard.
- Per-customer-limited coupon: `UNIQUE(coupon_id, customer_id, order_id)` + a counted limit check inside the txn.
- Two concurrent requests both pass the "is it used?" read → both attempt INSERT → the DB rejects the second.

**Defense 2 — Idempotency key (replay / double-click / webhook redelivery).**
Every redemption AND every wallet entry carries a unique `idempotency_key`:
```
coupon:  redeem:<coupon_id>:<order_id>
wallet:  order:hold:<order_id>   /   order:capture:<order_id>
```
Replay with the same key returns the **existing** result and moves nothing. Kills double-redeem from network retries, double-taps, and WhatsApp webhook redelivery (the same pattern already used in `outbox` + `webhook`).

**Defense 3 — Wallet hold model (concurrent orders).**
Customer with AED 20 starts two orders at once, each trying to spend 20:
```
Order A -> WalletEntry(type=hold, -20)   # available now 0
Order B -> WalletEntry(type=hold, -20)   # available < 20 -> REJECTED
```
The hold reduces *available* balance immediately, inside the transaction — the same credit can't be spent twice across simultaneous orders.

**Defense 4 — Atomic transaction + row lock.**
The balance/limit check and the write happen in ONE DB transaction with `SELECT ... FOR UPDATE` on the account/coupon row (or rely on the unique constraint). No two transactions interleave through the gap.

**Defense 5 — Balance is derived, never stored.**
Wallet balance = `SUM(posted entries)`. There is no mutable `balance` column to corrupt with a lost update. Every spend is an immutable debit row; worst case you re-sum and the truth is intact.

### Why this is bulletproof

| Attack | Blocked by |
|--------|-----------|
| Click "redeem" twice fast | Idempotency key |
| Two phones / sessions, same coupon | UNIQUE constraint on redemption |
| Two orders spend the same credit | Hold model + atomic txn |
| Network retry resends redeem | Idempotency key |
| WhatsApp redelivers the webhook | Idempotency key (existing pattern) |
| Race past the "is it used?" check | The check IS the INSERT (constraint) |
| Lost-update on a balance column | No balance column — derived from ledger |

**The principle: the database enforces uniqueness, not application code.** App logic can have bugs and races; a UNIQUE constraint + an idempotency key cannot be raced.

---

## 10. Build Order (TDD per CLAUDE.md)

1. **Wallet ledger** (`WalletAccount`, `WalletEntry`) — balance/available derivation, never-negative, idempotency. Property test: money conserved.
2. **Hold → capture → release** flow with concurrency tests.
3. **Coupon generalization** + `CouponRedemption` ledger — atomic limit enforcement, entropy, rate-limit.
4. **Ticket integration** — manager refund-to-wallet writes a ledger entry + audit (per `complaint-ticket-system-design.md`).
5. **Wallet spend in ordering/confirmation** — reduce COD due, hold/capture on FSM.
6. **Reconciliation + expiry** Celery beat jobs; drift alerting.
7. **Abuse/velocity** flags + account freeze + per-tenant budget kill switch.
8. **Dashboard**: liability/KPI views, wallet on customer profile, coupon management.
9. **Full test matrix** (unit → integration → E2E → load → security) per CLAUDE.md.

---

*End of design. No code was changed by this document.*
