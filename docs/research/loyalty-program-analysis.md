# Customer Loyalty Program — Analysis & Real-World Scenarios

> **Status:** Implementation-ready design. Loyalty itself not built yet, but the primitives it needs (ledger-backed wallet, generalized coupons, RFM) now exist — §6+ is a concrete build spec on top of them.
> **Date:** 2026-06-28 · **Updated:** 2026-06-29 (wallet + generalized coupons shipped)
> **Scope:** Multi-tenant WhatsApp restaurant platform (COD, UAE F&B, own-fleet delivery).
> **Audience:** Product + engineering. §1–5 = analysis + 200 scenarios. §6–13 = buildable design.

---

## 1. Current State — What Exists Today

**There is no dedicated loyalty program.** But the building blocks — and now the earn/redeem rails — are in place:

| Asset | File | What it gives you |
|-------|------|-------------------|
| **RFM segmentation** | `src/app/marketing/rfm.py` | 6 mutually-exclusive cohorts: `champions` / `loyal` / `potential` / `at_risk` / `lost` / `new`, from `total_orders` + `last_order_at` |
| **Customer aggregates** | `src/app/ordering/models.py:Customer` | `total_orders`, `total_spend`, `first_order_at`, `last_order_at`, `usual_order_times`, `tags` (JSONB) |
| **Wallet ledger (NEW, shipped)** | `src/app/wallet/` | Append-only `WalletAccount`+`WalletEntry`; **derived balance**, idempotent `credit`/`debit`/`hold`/`capture`/`release`, freeze, reversal, per-tenant, never-negative. **This is the earn/redeem rail loyalty needs.** |
| **Wallet spend at checkout (NEW)** | `src/app/ordering/payments.py` | Auto-applies wallet credit at confirm → `cod_due = total − wallet`; capture on delivery, release on cancel. No double-charge. |
| **Coupons, generalized (NEW)** | `src/app/coupons/` | Campaign + apology coupons: fixed/percent, caps, min-order, per-customer + total limits, validity, **dup-proof `CouponRedemption` ledger**, pause kill-switch, ~50-bit codes. |
| **WhatsApp utility templates (NEW)** | `src/app/whatsapp/templates.py` | 24h-window-aware customer notifications (session text in-window, approved template out). `coupon_issued`, `wallet_credit_added` already defined. |
| **Segment DSL** | `src/app/marketing/segments.py` | Targeting on `total_spend`, `order_count`, `last_order_days_ago` |
| **Marketing engine** | `src/app/marketing/service.py` | Throttle + send-window + opt-out + WhatsApp template send to any segment |

**Conclusion (updated 2026-06-29):** the data layer (aggregates), targeting (RFM + DSL), delivery (marketing send + window-aware templates), AND the **earn/redeem rail (wallet ledger + checkout spend)** now exist. What remains for loyalty is a thin layer: a **tier engine** (RFM+Monetary → tier → perks) and a **points-as-wallet-credit earn loop**. Most of the hard money plumbing is already done — see §6.

### Current RFM formula (`_classify`)

```
F = total_orders
if F <= 1:                      -> "new"
if last_order_at is None:       -> "lost"
R = days since last_order_at
if F >= 5 and R <= 30:          -> "champions"
if F >= 3 and R <= 60:          -> "loyal"
if R <= 30:                     -> "potential"
if R <= 120:                    -> "at_risk"
else:                           -> "lost"
```

**Gap:** uses only Recency + Frequency. `total_spend` (the Monetary axis) is available but unused — flagged in `rfm.py:9`. A true "champion" should be high-spend, not merely frequent.

---

## 2. How to Define Loyalty

Two distinct concepts — do not conflate them:

- **RFM = diagnosis.** Who is loyal *right now*. Already built.
- **Loyalty program = intervention.** A mechanic that *creates* loyalty. Not built.

RFM alone is **not** a loyalty program — it is the segmentation that *targets* one. Use RFM to decide *who gets what*, then a points/tier mechanic to *change behavior*.

### Candidate mechanics, ranked for THIS platform

**1. Tier-based (RFM-driven) — best fit, lowest friction. RECOMMENDED START.**
Map existing RFM cohorts straight to tiers. No new earn/balance state required.
- `champions` → Gold (free delivery always, early access to today's special)
- `loyal` → Silver (free delivery above AED X, birthday reward)
- `potential` → Bronze (nudge toward next tier)

Already computable. Reuses coupon issuance. Recompute nightly.

**2. Points / stamps — classic, higher engagement, more to build.**
"AED 1 = 1 point" or "every 5th order free." Needs new state: `points_balance`, a `points_ledger` (earn/redeem rows for audit), and redemption wired into the conversation engine + checkout. Stamps ("buy 9, get 10th free") test best for F&B repeat frequency — simpler than points and customers track them mentally.

**3. Spend-threshold cashback.**
`total_spend` crosses AED N → auto-coupon. Trivial (you already have `total_spend` + coupon issuance) but the weakest behavior driver.

### Why RFM-driven tiers win here

- **WhatsApp has no good UI for a live points balance** — a *tier* is one word the bot can state ("You're Gold 🥇 — delivery's on us").
- **COD means no card-on-file, no checkout loyalty hooks** — earning must be order-completion-driven, which `total_orders` / `total_spend` already track.
- **Multi-tenant** — each restaurant tunes its own thresholds, fitting the per-restaurant `settings` pattern.

**Recommended formula upgrade:** add Monetary to `_classify` so tiers reflect spend, not just frequency.

---

## 3. How to Utilize It

**Acquisition → Activation**
- New customer's first order → welcome reward via marketing engine → push to 2nd order (`new` → `potential`).

**Retention (highest ROI)**
- `at_risk` cohort → automated win-back coupon through the existing marketing send. You already have the segment + the pipeline; only reward issuance needs wiring.
- Tier perks announced **inside the conversation engine** at order time ("Gold member — free delivery applied"). Perceived value at the exact decision moment.

**Frequency lift**
- `usual_order_times` (already captured per weekday) + loyalty → perfectly-timed nudge: "Your usual Friday biryani — order now, earn double points." Combine with `marketing/todays_special.py`.

**Margin protection**
- Tier free-delivery instead of blanket discounts → protects food margin and subsidizes only the controllable delivery cost (delivery fees are already tiered by km).

**Referral loop**
- WhatsApp is inherently shareable — "refer a friend, both get AED 10." Reuses the coupon model + a referral attribution field.

**Analytics**
- `AnalyticsScreen` + RFM counts → show tier migration over time (champions growing? at_risk shrinking?) as the program KPI.

### Bottom line
We have **RFM (diagnosis) + coupons + marketing send (delivery)**. We are missing the **mechanic** and the **earn/redeem loop**. Cheapest high-value path: **RFM-cohort → tier → auto-issue perks via the existing coupon + marketing pipeline**, add **Monetary** to the RFM formula, and surface tier status in the conversation engine at order time. Points/stamps are a phase-2 upgrade if engagement data justifies the extra state.

---

## 4. 200 Real-World Scenarios a Restaurant Must Handle

These are the operational, edge-case, and customer-facing situations any loyalty program on this platform will run into. They are grouped by theme. Each is a question the product and the code must have a defined answer for. Treat this as a requirements checklist and an adversarial test list.

### A. Enrollment & Identity (1–20)

1. Customer orders for the first time — are they auto-enrolled in loyalty, or must they opt in?
2. Customer changes phone number — how do we keep their points/tier history?
3. Two people share one phone (family/flatmates) — whose loyalty is it?
4. One person uses two numbers (personal + work) — do we merge or keep separate?
5. Customer orders via WhatsApp catalog AND via the conversation bot — same loyalty account?
6. A manager places a manual order on the customer's behalf — does the customer earn points?
7. Customer ports their number to a new SIM — does loyalty survive?
8. A guest checks out without ever giving a name — can they still earn?
9. Customer wants to delete their account (UAE PDPL / GDPR-style) — what happens to points?
10. Customer enrolled at Restaurant A — does that mean anything at Restaurant B on the same platform?
11. A new restaurant joins the platform mid-program — do existing customers carry any status?
12. Customer asks "am I a member?" — how does the bot answer?
13. Customer never consented to marketing but is loyalty-enrolled — can we still message them?
14. Phone number recycled by the telco to a new person — old loyalty leaks to a stranger?
15. Customer enrolled twice due to a typo'd name on two orders — duplicate accounts?
16. Staff member orders as a customer to farm points — how do we detect/prevent?
17. Customer wants to enroll a family member as a beneficiary of their points.
18. WhatsApp Business account vs personal — does the sender identity affect enrollment?
19. Customer signs up just before a known price hike to lock in a tier — allowed?
20. Restaurant wants enrollment gated behind a minimum first-order value.

### B. Earning Points / Stamps (21–45)

21. Does the customer earn on the full order total or only the food (excluding delivery fee)?
22. Do they earn on the tip?
23. Do they earn on a discounted/coupon order, and on the pre- or post-discount amount?
24. Order is partially refunded — are the earned points clawed back proportionally?
25. Order cancelled before cooking — points reversed?
26. Order cancelled after cooking (auto-resell case) — does the original customer keep points?
27. Customer modifies the order (allowed before `ready`) — recompute earned points?
28. Multi-item order where one item is out of stock and removed — recompute earning?
29. Double points promo overlaps with a happy-hour discount — do they stack?
30. Customer splits one big order into three to farm "per-order" stamps — abuse?
31. Rounding: AED 1 = 1 point but the order is AED 47.50 — round up, down, or fractional?
32. Points earned on a COD order that the customer then refuses at the door — reverse?
33. A failed/undelivered order (rider couldn't find address) — earn or not?
34. Backdated order entered manually by staff days later — earn at today's or that day's rate?
35. Earning rate changed yesterday — which rate applies to an order placed before the change?
36. Customer earns on a catalog order — same rate as a bot order?
37. Bulk/catering order of AED 2,000 — cap the points or let it ride?
38. Does a free birthday meal itself earn points?
39. Points on delivery fee when delivery was free (tier perk) — earn on zero?
40. Two promos active at two restaurants the customer ordered from same day — independent?
41. Customer pays partly with a coupon and partly cash — earn on which portion?
42. Negative-margin loss-leader dish — restaurant wants it excluded from earning.
43. Weekend-only double points — what timezone boundary defines "weekend" (Asia/Dubai)?
44. Order placed at 11:59 PM during a promo, delivered at 12:30 AM after it ended — which window counts?
45. System outage means an order wasn't recorded — customer claims missing points later.

### C. Redemption (46–75)

46. Customer wants to redeem mid-conversation — how does the bot present available rewards?
47. Customer has enough points for two rewards but the order only fits one — which applies?
48. Reward value exceeds the order total — refund the difference, cap it, or block?
49. Customer redeems, then cancels the order — are points returned?
50. Customer redeems, then modifies the order below the reward's minimum — revoke?
51. Reward is "free delivery" but the address is outside the 10 km radius (no delivery anyway).
52. Reward is a free dish that's currently out of stock — substitute or hold?
53. Customer wants to redeem on a catalog order — is redemption supported there?
54. Customer tries to redeem an already-redeemed (single-use) coupon — clear error?
55. Two coupons on one order — allowed to stack?
56. Coupon + tier free-delivery on the same order — double benefit allowed?
57. Customer redeems for someone else's delivery (gifting) — permitted?
58. Reward expired yesterday; customer is upset — manager override path?
59. Customer redeems the wrong reward by mistake — can the bot undo within the session?
60. COD: reward reduces total to AED 0 — does the rider still "collect" nothing cleanly?
61. Partial redemption — use 50 of 200 points — supported, or all-or-nothing?
62. Customer wants to redeem but is below the restaurant's minimum order value.
63. Reward redemption during a delivery-only / closed-kitchen window.
64. Customer redeems, order is auto-cancelled by SLA breach — reward state?
65. Reward is "buy-one-get-one" but they ordered only one — auto-add the free one?
66. Manager manually applies a reward in the dashboard — does it sync to the customer's balance?
67. Redemption attempted across two devices/sessions at once — race / double-spend.
68. Customer redeems at Restaurant A using points they think are platform-wide — explain scope.
69. Reward fine print (min spend, excluded items) — how is it surfaced before commit?
70. Customer redeems a percentage discount on a huge catering order — cap the absolute value?
71. Reward applies only to specific dishes — customer's cart has none of them.
72. Customer disputes that a redemption "didn't work" — audit trail to resolve.
73. Redeemed reward on an order that gets weather-delayed — does the late-coupon ALSO apply?
74. Customer wants to "save" a reward for next time after starting to redeem — reversible?
75. Reward redemption pushes the order under the free-delivery threshold they were relying on.

### D. Tiers & Status (76–95)

76. Customer just dropped from Gold to Silver — do we notify them, and how gently?
77. Customer is one order away from Gold — proactive nudge?
78. Tier perks change mid-month — grandfather current members or apply immediately?
79. Customer was Gold, went quiet 120 days, now `lost` — instant demotion or grace period?
80. Seasonal spike (Ramadan) inflated everyone's frequency — tiers distort afterward?
81. Restaurant lowers the Gold threshold — sudden flood of new Gold members, perk cost spikes.
82. Two customers same frequency, very different spend — should they share a tier? (Monetary gap)
83. Customer asks "what do I need to do to reach Gold?" — bot must explain the formula simply.
84. Tier recompute runs nightly — customer ordered at 11 PM and expects instant upgrade.
85. A refund drops a customer below a tier threshold after they were promoted — demote?
86. Manager wants to manually grant VIP/Gold to a friend — override path + audit.
87. Tier benefits conflict between restaurants (Gold means different things per tenant).
88. Customer screenshots a friend's "Gold" message and demands the same — proof of status.
89. Inactive customer returns after a year — restore old tier or start fresh?
90. Tier-based free delivery erodes margin on long-distance (>5 km) orders — cap distance?
91. Restaurant wants a hidden top tier (invite-only) above Gold.
92. Tier downgrade message lands during an active order conversation — bad timing.
93. Bulk corporate customer always high-frequency — permanently top tier, gaming the perks?
94. Tier thresholds in `total_orders` vs `total_spend` — which does the restaurant control?
95. Customer demands retroactive tier credit for orders made before the program launched.

### E. Expiry, Communication & Consent (96–115)

96. Points about to expire — when and how do we warn (and via WhatsApp's 24-hour window rules)?
97. Customer opted out of marketing — can we still send loyalty/transactional balance updates?
98. WhatsApp template approval needed for loyalty messages — what if Meta rejects the template?
99. Customer marks loyalty messages as spam — WhatsApp quality rating risk to the number.
100. Points expired during a platform outage that blocked ordering — fair to expire?
101. Customer never opened WhatsApp for months — are "your points expired" messages even seen?
102. Frequency cap (24h) on marketing collides with an urgent expiry warning — which wins?
103. Customer replies "STOP" to a loyalty message — does that opt them out of all marketing?
104. Restaurant wants no expiry at all — does the model support infinite points liability?
105. Time-zone edge: expiry computed in UTC but customer thinks in Asia/Dubai.
106. Customer asks for their full points history / statement — can we produce it?
107. Reward sent but the WhatsApp message failed to deliver (outbox dead-letter) — reissue?
108. Customer changed language preference — are loyalty messages localized (EN/AR)?
109. Sending a balance update outside the 24h customer-service window — needs a paid template.
110. Customer disputes "I never got the reward message" — outbox audit as proof.
111. Mass expiry on the 1st of the month triggers a send spike — throttle / WhatsApp limits.
112. Loyalty message sent during the restaurant's closed hours — appropriate?
113. Customer consent withdrawn under PDPL — must we stop loyalty messaging immediately?
114. A/B testing reward copy — is that allowed under the consent the customer gave?
115. Reward code leaked/shared publicly on social media — single-use enforcement.

### F. Fraud, Abuse & Edge Cases (116–140)

116. Customer cancels-after-delivery repeatedly to farm apology coupons — detect pattern.
117. Same person, many phone numbers, all claiming "new customer" welcome reward.
118. Referral abuse: customer refers their own alternate numbers.
119. Staff issuing rewards to themselves through the manual-order path.
120. Coupon code brute-forced/guessed — code entropy and rate limiting.
121. Customer places, earns, refuses at door (COD) repeatedly — points + operational abuse.
122. Bot tricked via prompt injection into "granting" points it shouldn't.
123. Two restaurants on the platform colluding to inflate a shared customer's status.
124. Reward arbitrage: redeem free delivery, cancel food, keep nothing but cost the restaurant.
125. Time-travel: manual backdated orders to qualify for an expired promo.
126. Points balance goes negative after a clawback — floor at zero or allow debt?
127. Concurrent redemptions racing to double-spend the same balance.
128. Customer disputes a chargeback equivalent (COD has none) but demands points back.
129. Bulk fake accounts created to drain a launch promo budget.
130. Reward applied, order marked delivered by a colluding rider, never actually delivered.
131. Customer screenshots an old higher balance and demands it be honored after a clawback.
132. Promo stacking exploit found by customers and shared in a WhatsApp group.
133. Restaurant accidentally sets earning rate to 100x — runaway liability overnight.
134. Negative test: redeeming more points than exist must hard-fail, not silently zero.
135. A customer's tier flips back and forth daily near a threshold — perk thrash.
136. Loyalty data used to price-discriminate in a way that violates platform/UAE rules.
137. Self-ordering kiosk / manual order double-counts an order into loyalty.
138. Customer claims points for an order placed at a DIFFERENT restaurant.
139. Refund-then-reorder loop to repeatedly trigger first-purchase bonuses.
140. Reward issued, restaurant offboards from the platform — who honors it?

### G. Operations, Reporting & Multi-Tenant (141–165)

141. How does a restaurant see total outstanding points liability (AED at risk)?
142. Manager wants to pause the program instantly (budget blown) — kill switch?
143. Two managers edit loyalty settings simultaneously — last-write-wins or conflict?
144. Restaurant wants per-branch loyalty (if they have multiple locations on one account).
145. Reporting: redemption rate, breakage (unredeemed expiry), incremental revenue.
146. Manager wants to export the member list with tiers for an external campaign.
147. Reconciling COD cash vs points-discounted orders at end of day.
148. Rider sees a "free delivery — collect AED 0 delivery" — does the cash sheet balance?
149. Loyalty cost attribution: is a free dish charged to marketing or COGS?
150. Restaurant changes its menu prices — does that retroactively shift past `total_spend`?
151. Multi-tenant isolation: Restaurant A must never see Restaurant B's members.
152. Platform-level promo vs restaurant-level promo — who pays for the reward?
153. Manager wants to manually adjust a single customer's points with a reason (audit).
154. Bulk import of an existing loyalty list from the restaurant's old system.
155. Restaurant wants to set blackout dates (no earning/redemption on peak holidays).
156. Forecasting reward redemption load for kitchen capacity planning.
157. Loyalty settings must survive a settings migration without resetting balances.
158. Restaurant downgrades plan/subscription — is loyalty a paid feature gated off?
159. Audit: every points change must be traceable (who, when, why) — append-only.
160. Manager disputes the platform's reported redemption numbers — source of truth.
161. A/B which tier thresholds drive the most reorders — experimentation framework.
162. Customer-service rep needs a quick "look up this customer's loyalty" view in the dashboard.
163. Loyalty interacts with the 40-min SLA late-coupon — don't double-compensate.
164. Restaurant wants loyalty perks ONLY for direct orders, not catalog — configurable scope.
165. Onboarding a restaurant: sensible default loyalty config vs forcing setup.

### H. Customer Experience & Conversation (166–185)

166. Customer asks "how many points do I have?" mid-order — bot answers without derailing the order.
167. Customer asks in Arabic — loyalty replies must be localized.
168. Bot must not over-message (loyalty spam) and erode the ordering experience.
169. Customer confused by points vs tiers vs coupons — single clear mental model.
170. Reward auto-applied silently — customer doesn't notice the benefit (no perceived value).
171. Customer wants to know WHY they were demoted — empathetic, non-accusatory copy.
172. Voice note: customer asks about loyalty by audio — STT → intent → answer.
173. Customer asks the bot to "use my free meal" — natural-language redemption intent.
174. Customer says "save it for next time" — bot must not redeem.
175. Bot offers a reward the customer isn't eligible for — embarrassing; eligibility check first.
176. Customer asks "is delivery free for me?" before ordering — tier-aware answer.
177. Reward messaging during an active complaint — read the room (sentiment).
178. New customer asked to enroll mid-first-order — friction vs opportunity.
179. Customer screenshots a competitor's better program — retention talking point.
180. Bot should celebrate milestones ("that's your 10th order! 🎉") without being gimmicky.
181. Customer asks to transfer points to a friend — supported phrase, clear yes/no.
182. Customer wants a reminder before points expire — opt-in to the reminder itself.
183. Disabled/blocked customer still receiving loyalty messages — suppression list.
184. Customer replies to a loyalty broadcast with an actual order — bot must switch to ordering.
185. Birthday reward — do we even have birthday data, and how was it consented?

### I. Lifecycle, Refunds & FSM Interactions (186–200)

186. Order FSM: at which status do points "lock in" (placed, cooking, delivered)?
187. Earn on `delivered` only, but reward shown at `placed` — interim state messaging.
188. Modification restarts the SLA clock — does it also re-trigger any loyalty calc?
189. Cancelled-after-cooking auto-resell: the RESELL buyer's loyalty vs the original.
190. Weather-delay exemption (no late coupon) — does loyalty messaging still fire?
191. Partial delivery (one of two batched orders failed) — earn on the delivered part only.
192. Refund issued days later — points clawback must replay through the ledger cleanly.
193. Reward + late-coupon on the same breached order — cap total compensation.
194. Order stuck in a non-terminal state for hours — when do points settle?
195. Duplicate webhook replays the same order — points must not double-count (idempotency).
196. Outbox retry resends a "you earned points" message twice — dedupe customer-facing comms.
197. Manual order edited after creation — keep the points ledger consistent.
198. Customer profile merge (two accounts → one) — sum balances, dedupe history.
199. Restaurant deletes a customer — points ledger retention vs PDPL erasure conflict.
200. Program sunset: restaurant ends loyalty — graceful wind-down, honor outstanding rewards, communicate.

---

## 5. Cross-Cutting Challenges (the hard parts)

Most of the 200 above collapse into a handful of systemic challenges:

1. **Identity resolution** — phone is the key, but phones are shared, recycled, and changed. Every loyalty bug eventually traces back to "who is this customer, really?"
2. **Idempotency & the ledger** — earning/clawback must be an append-only, replay-safe ledger (you already do this for audit + outbox). Never mutate a balance in place; derive it.
3. **State-machine coupling** — points must hook the Order FSM at exactly one settle point and survive cancel / modify / refund / auto-resell without double-counting.
4. **WhatsApp constraints** — the 24-hour window, template approval, opt-out/STOP, and quality-rating risk constrain *every* loyalty message. Transactional vs marketing classification matters.
5. **Multi-tenancy** — scope is per-restaurant by default; "platform-wide loyalty" is a different, bigger product decision. Isolation must never leak.
6. **Liability & margin** — outstanding points are a real financial liability; tier free-delivery and free dishes erode margin. Needs caps, kill switches, and reporting.
7. **Fraud surface** — COD + self-service + manual orders + referrals is a wide abuse surface. Velocity checks and audit trails are mandatory, not optional.
8. **Consent & PDPL** — enrollment, messaging, profiling, and erasure all have legal edges in the UAE. Loyalty data is personal data.

---

## 6. Implementation Design — Build on What's Already Shipped

The earlier sections were written before the wallet/coupon work landed. They now have a concrete substrate. The loyalty program is **two thin layers** over existing, tested primitives:

```
        ┌─────────────────────────────────────────────┐
        │  LOYALTY (new, thin)                          │
        │   • Tier engine: RFM+M → tier → perks         │
        │   • Earn loop: order delivered → points       │
        └───────────────┬───────────────┬──────────────┘
                        │ rewards as     │ tier perks as
                        │ wallet credit  │ free-delivery / coupon
        ┌───────────────▼───────────────▼──────────────┐
        │  EXISTING, SHIPPED                             │
        │   wallet ledger · coupons · checkout spend ·  │
        │   RFM · marketing send · utility templates    │
        └───────────────────────────────────────────────┘
```

**Design rule:** loyalty issues **value only through the existing rails** — points become **wallet credit** (already spendable at checkout), tier rewards become **coupons** or **free-delivery at confirm**. No new money primitive. This inherits the wallet's idempotency, audit, never-negative, and no-double-charge guarantees for free.

---

## 7. The Two Mechanics (ship tiers first, points second)

### 7a. Tiers (Phase 1 — recommended first)
RFM cohort → tier → perks. **No new earn state needed** — recompute nightly from data we already have.

| Tier | RFM source (after Monetary upgrade) | Perks (all via existing rails) |
|------|--------------------------------------|---------------------------------|
| 🥇 Gold | `champions` (high F, recent, high M) | Free delivery always; early access to today's special |
| 🥈 Silver | `loyal` | Free delivery above min order; birthday reward (coupon) |
| 🥉 Bronze | `potential` | "1 order from Silver" nudge |
| — | new / at_risk / lost | targeted win-back (marketing), no standing perk |

Perks map to mechanisms that exist: **free delivery** = set `delivery_fee_aed = 0` at confirm for the tier; **birthday/welcome reward** = `coupons.issue_coupon` or a wallet credit; **early access** = marketing segment send.

### 7b. Points → wallet credit (Phase 2)
"Earn X% of order value back as wallet credit." On order **delivered**, credit the wallet:
`points_credit = round(order.subtotal × earn_rate, 2)` → `wallet.credit(type="promo_credit", reason="loyalty_earn", idempotency_key=f"loyalty:earn:{order_id}")`.
- **Idempotent per order** (the wallet key guarantees no double-earn on webhook/retry).
- **Spendable immediately** — checkout already auto-applies wallet credit (no new redemption code).
- **Stamps variant** ("buy 9, get 10th free") = a counter on the customer; the 10th order issues a 100%-capped coupon. Simpler for customers to track; pick per restaurant.

**Why points = wallet credit, not a separate balance:** the wallet is already a correct, audited, spendable ledger. A parallel `points_balance` would duplicate it and re-introduce the double-spend/expiry problems the wallet already solved.

---

## 8. Monetary RFM Upgrade (prerequisite, tiny)

`rfm.py:_classify` uses only R + F today (flagged at `rfm.py:9`). Add Monetary so tiers reflect spend:

```
m = total_spend
# champion now requires money, not just frequency:
if f >= 5 and r <= 30 and m >= settings.loyalty_champion_min_spend:  -> "champions"
```
Per-restaurant thresholds in settings (`loyalty_*`). Keep buckets mutually exclusive (the counts/targeting code is untouched — only `_classify` changes). Back-compat: default the spend threshold to 0 so existing behavior is preserved until a restaurant tunes it.

---

## 9. Data Model (minimal — most state already exists)

```
# Tier is DERIVED nightly; persist only for fast reads + change detection.
Customer (extend):
  loyalty_tier        String(12)  # gold|silver|bronze|none  (recomputed nightly)
  loyalty_tier_since  DateTime    # for "you've been Gold since…" + demotion grace

# Per-restaurant config (settings JSONB — no schema change):
  loyalty_enabled, earn_rate (e.g. 0.05), tier thresholds, champion_min_spend,
  perk map (gold_free_delivery: true, …), stamp_target (e.g. 10), reward_value.

# Earn is just a wallet entry (NO new table):
  WalletEntry(type="promo_credit", reason_note="loyalty_earn", idempotency_key="loyalty:earn:{order_id}")

# Optional stamps counter (only if stamps chosen):
  LoyaltyStamps(restaurant_id, customer_id, count, last_order_id)  # tiny
```

No new money table. Tier is a denormalized cache of an RFM computation; the wallet is the value store.

---

## 10. Wiring (every hook point already exists)

- **Earn**: `dispatch/delivery.py:advance_delivery` (the `delivered` branch — already where capture + stats recompute happen) → call `loyalty.earn(order)`. Idempotent via the wallet key.
- **Tier recompute**: nightly Celery beat (mirror `wallet.reconcile` / `predictions` beat) → recompute `loyalty_tier` per customer from RFM+M; on change, notify ("You're now Gold 🥇") via the window-aware sender.
- **Tier perks at checkout**: `ordering/payments.apply_at_confirm` (already runs at confirm) → if tier grants free delivery, set `delivery_fee_aed = 0` before computing COD.
- **Conversation surfacing**: the order-summary redeem block (already conditional in `engine._send_order_summary`) → add a tier line ("Gold member — delivery's on us 🥇") when the customer has a tier/perk. Reuses the exact pattern just built for wallet/coupon options.
- **Birthday/welcome rewards**: marketing beat or signup hook → `coupons.issue_coupon` (notified via the `coupon_issued` utility template).
- **Dashboard**: tier shown on `CustomerProfileScreen` (next to the wallet/coupons sections already there); a Loyalty settings tab (reuse `SettingsScreen` pattern) for earn rate + thresholds + perk toggles.

---

## 11. Guardrails (mostly inherited)

| Risk | Mitigation (existing unless noted) |
|------|------------------------------------|
| Double-earn (webhook/retry) | Wallet idempotency key `loyalty:earn:{order_id}` |
| Earn on cancelled/refunded order | Earn fires on `delivered` only; a later refund reverses via the wallet reversal already built |
| Liability blowup | Earn rate capped per restaurant; outstanding = wallet liability already reconciled nightly |
| Tier gaming (bulk corp account) | Monetary axis + per-restaurant thresholds; manager can manually adjust |
| Free-delivery margin erosion | Perk gated by tier + optional min-order/distance cap (settings) |
| Cross-tenant leak | Wallet + coupons already per-`restaurant_id`; tier is per-customer-per-tenant |
| Points expiry | Reuse the wallet expiry sweep (`wallet.reconcile.expire_credits`) — loyalty credit expires like any credit |
| Customer confusion (points vs wallet vs coupon) | **Single mental model**: there are no "points" — earnings are AED wallet credit. One balance the bot can state plainly. |

---

## 12. Build Plan (TDD, phased — small because the rails exist)

**Phase 1 — Tiers (no money):**
1. Monetary RFM upgrade in `_classify` (+ settings thresholds). Test: spend changes the bucket.
2. `Customer.loyalty_tier` + nightly recompute beat. Test: cohort → tier mapping + change detection.
3. Free-delivery perk in `apply_at_confirm`. Test: Gold → COD excludes delivery fee.
4. Tier line in order summary + tier on customer profile. Tests.

**Phase 2 — Earn (points = wallet credit):**
5. `loyalty.earn(order)` on `delivered`, idempotent. Test: one credit per order, none on cancel.
6. Settings: earn rate + enable toggle + dashboard Loyalty tab.
7. Refund reversal path (earn reversed when the order is refunded). Test.

**Phase 3 — Rewards & comms:**
8. Birthday/welcome coupons via existing issuance + `coupon_issued` template.
9. Tier-change notifications (window-aware). Tier-migration KPIs on Analytics.

Each phase ships independently and is useful alone. Phase 1 needs **zero** new money code.

---

## 13. Open Decisions (need product input before building)

1. **Tiers, points, or stamps first?** (Recommend: tiers — zero money risk, immediate perceived value.)
2. **Earn rate** default + whether it's per-restaurant tunable (recommend yes).
3. **Do tiers expire / demote?** Grace period before Gold→Silver on going quiet (recommend 30-day grace).
4. **Free-delivery perk caps** — distance/min-order limits to protect margin?
5. **Points expiry** — reuse wallet TTL (recommend 90 days, off by default)?
6. **Enrollment** — auto-enroll all customers (recommend) vs opt-in?
7. **Naming** — "wallet credit" covers earnings; do we even surface the word "points/loyalty" to customers, or just "credit + member tier"?

These map directly onto scenarios in §4 (A. Enrollment, B. Earning, D. Tiers, E. Expiry) — answer them there.

---

*End of analysis. No code was changed by this document.*
