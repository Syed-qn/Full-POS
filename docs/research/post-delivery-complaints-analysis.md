# Post-Delivery Customer Complaints — Analysis & 200 Real-World Scenarios

> **Status:** Research / design note. No post-delivery complaint flow is implemented yet.
> **Date:** 2026-06-28
> **Scope:** Multi-tenant WhatsApp restaurant platform (COD, UAE F&B, own-fleet delivery).
> **Audience:** Product + engineering + customer-care, ahead of any complaint-handling build.

---

## 1. Current State — What Happens Today

**There is no real post-delivery complaint flow.** The bot deflects, and the only automated compensation is SLA-clock-driven, not complaint-driven.

| Behavior | File | What it does |
|----------|------|--------------|
| **Bot deflects complaints** | `src/app/llm/deepseek.py:342-348` | Identity prompt lists "a complaint, a refund" as out of scope → replies "please call us on {restaurant_phone}". Nothing logged. |
| **Post-order phase = status/modify/cancel only** | `src/app/llm/deepseek.py:478-493` (`_POST_ORDER_BLOCK`) | Handles status query, modify (before `ready`), cancel (before `picked_up`), "too late to cancel" if delivered. No "something's wrong" branch. |
| **SLA late-coupon (auto)** | `src/app/sla/monitor.py:212` | At `breach_40`, auto-issues AED 10 coupon UNLESS `weather_delay_disclosed`. Triggered by the clock, NOT by a complaint. |
| **Coupon primitive** | `src/app/coupons/` | Single-use `SORRY-` codes, 30-day expiry, FSM `issued/redeemed/expired`. Late-delivery apology only. |

### The gap matrix

| Complaint type | Handled? | What happens today |
|----------------|----------|--------------------|
| Late delivery | ⚠️ Partial | Auto-coupon from SLA clock (not from the complaint itself) |
| Wrong item | ❌ No | Bot deflects to phone |
| Missing item | ❌ No | Bot deflects to phone |
| Cold / bad quality | ❌ No | Bot deflects to phone |
| Refund request | ❌ No | Bot deflects to phone (COD = no captured payment to refund) |
| Rider behavior | ❌ No | Bot deflects to phone |

**Missing entirely:** complaint model / ticket / logging, refund or goodwill-credit mechanic, complaint-triggered compensation, manager dashboard complaint surface, complaint-intent + sentiment detection, and any link between a complaint and the order/rider/dish that caused it.

**Bottom line today:** *late = auto-coupon (clock-driven); everything else = "call us."* No complaint is recorded, tracked, or escalated.

---

## 2. How to Read the 200 Scenarios

Each item is a real situation a restaurant's customer care WILL face after an order is marked delivered. They are grouped by theme. For each, the product + code need a defined answer to three questions:

- **Capture** — does the system record it (intent, evidence, link to order)?
- **Resolve** — what is the action (refund / redeliver / remake / goodwill credit / nothing / escalate)?
- **Account** — who pays, what's audited, how is abuse prevented?

Treat this as a requirements checklist and an adversarial test list. The hard cross-cutting challenges are summarized in §13.

---

## 3. Food Quality Complaints (1–25)

1. "Food arrived cold." — remake, refund, partial credit, or nothing?
2. "Food was stale / not fresh."
3. "Biryani was undercooked / raw in the middle."
4. "Food was burnt."
5. "Too salty / inedible."
6. "Portion was much smaller than usual / than the photo."
7. "The dish tasted completely different from last time."
8. "There was a hair in my food."
9. "There was a plastic / foreign object in the food."
10. "I found an insect in the food."
11. "Food gave me food poisoning / I'm sick." (health-liability escalation)
12. "The meat smelled off / spoiled."
13. "Bread was hard / stale."
14. "Sauce/gravy was missing or dried out."
15. "Drink was flat / warm / wrong flavor."
16. "Dessert melted / was crushed."
17. "It was way too spicy despite my 'no spice' note."
18. "It wasn't spicy at all despite my 'extra spicy' note."
19. "They ignored my 'no onion' / allergy note." (allergy = safety-critical)
20. "Food was greasy / swimming in oil."
21. "Rice was hard / overcooked."
22. "Packaging leaked and ruined the food."
23. "Wrong sauce / wrong side included."
24. "Quantity per the menu didn't match what arrived (e.g. '6 pieces' but got 4)."
25. "It just wasn't good — I want my money back." (subjective, no defect)

## 4. Wrong / Missing Items (26–50)

26. "A whole dish is missing from my order."
27. "One of two drinks is missing."
28. "I got someone else's order entirely."
29. "I got the right items plus extra items I didn't order — do I pay?"
30. "Right dish, wrong variant (got chicken, ordered mutton)."
31. "Right dish, wrong size (got small, ordered large)."
32. "Missing cutlery / napkins / condiments I asked for."
33. "Missing the free item from a promo / reward."
34. "Quantity short — ordered 3, got 2."
35. "Ordered combo, one combo component missing."
36. "Got a substituted item I never agreed to."
37. "Two of the same dish, but I ordered two different ones."
38. "Missing item that was the whole reason I ordered."
39. "Half the batched order arrived, half didn't." (batching edge)
40. "I was charged for an item that wasn't in the bag."
41. "Extra charge on the bill for something I didn't get."
42. "The order is complete but the receipt/total is wrong."
43. "Modification I requested before 'ready' wasn't applied."
44. "Add-on I paid for (extra cheese) is missing."
45. "Kids' meal toy / freebie missing."
46. "Wrong spice level entirely on a multi-dish order — which dish gets remade?"
47. "Catering order short by several portions." (high-value, high-stakes)
48. "Got an expired / past-date packaged item."
49. "Items correct but cold AND missing a drink." (compound complaint)
50. "I ordered for a party; the headcount of food is wrong."

## 5. Delivery & Logistics Complaints (51–75)

51. "Order arrived very late (but under 40 min, so no auto-coupon)."
52. "Order arrived late and I DID get the coupon, but it's not enough."
53. "Rider left it at the wrong door / building."
54. "Rider left it at the gate / lobby without telling me."
55. "Rider marked delivered but I never received it." (delivery dispute)
56. "Rider was rude / unprofessional."
57. "Rider asked for a tip / extra cash aggressively."
58. "Rider couldn't find me and cancelled — I still want my food."
59. "Rider called repeatedly despite my 'do not call' setting."
60. "Rider never called and left without delivering."
61. "Order delivered to the wrong person who took it."
62. "Live tracking showed the rider, then it froze / disappeared."
63. "Tracking said delivered but rider was still 2 km away."
64. "Rider damaged the food in transit (spilled/tipped)."
65. "Rider was on a motorbike in rain and the food got wet." (weather edge)
66. "It took the rider forever because of batching with another order."
67. "Rider delivered the other batched customer's food to me."
68. "I moved / gave a new address mid-delivery and it went to the old one."
69. "Order says out for delivery for an hour with no movement."
70. "Rider asked me to come downstairs / to the street."
71. "No contactless delivery despite my request."
72. "Rider entered a restricted/secure area improperly."
73. "Delivery fee charged even though I was told it'd be free (tier/promo)."
74. "Delivery fee higher than quoted at order time."
75. "Order never arrived at all and no one contacted me."

## 6. Payment, Billing & COD Complaints (76–95)

76. "Rider didn't have change for my cash." (COD core)
77. "I was overcharged vs the amount confirmed in chat."
78. "Rider demanded more than the order total."
79. "I paid but the order shows unpaid in your system."
80. "I want a refund — but I paid cash, how does that work?" (COD refund mechanics)
81. "Delivery fee was added that I didn't agree to."
82. "The coupon I had wasn't applied at the door."
83. "I was charged the pre-discount amount despite a valid coupon."
84. "Double-charged / two orders created from one." (duplicate webhook edge)
85. "I refused the order at the door — am I charged anything?"
86. "Partial order arrived; I only want to pay for what I got."
87. "Rider kept the change / rounded up without asking."
88. "Currency confusion — quoted in AED, rider asked something else."
89. "I want an itemized receipt and never got one."
90. "Promo price wasn't honored at delivery."
91. "Minimum-order fee charged on a qualifying order."
92. "I was told free delivery for being a regular but still charged."
93. "Refund promised by phone last time never materialized."
94. "Tip I added in chat wasn't passed to the rider."
95. "I paid extra for priority/express that didn't happen."

## 7. Refund, Replacement & Compensation Demands (96–120)

96. "I want a full refund." — policy threshold?
97. "I want a partial refund for the one bad dish."
98. "I want the order remade and redelivered now."
99. "I want store credit instead of a refund."
100. "I want a free meal next time as compensation."
101. "I'll only accept cash back, not a coupon."
102. "The coupon you gave expires too soon."
103. "The coupon value is insulting for what happened."
104. "I want compensation for the inconvenience, not just the food cost."
105. "I want compensation for a stained shirt from leaked packaging."
106. "I demand a refund 3 days after delivery." (claim-window edge)
107. "I demand a refund 2 weeks later." (stale claim)
108. "This is the 3rd time — I want more than a coupon." (repeat complainant)
109. "I want my delivery fee back but keep the (eaten) food."
110. "I ate most of it but still want a refund."
111. "I want a refund AND to keep the replacement." (double-dip attempt)
112. "Refund me to my bank card." (COD — no card on file)
113. "Refund me to a different person's account."
114. "I want compensation in loyalty points." (ties to loyalty doc)
115. "Replace it but I'm not home for 3 hours."
116. "I want an apology from the manager personally."
117. "Refund the whole catering order over one wrong tray."
118. "I'll dispute this publicly unless you refund." (reputational pressure)
119. "I want the rider fired as my compensation."
120. "Give me the refund in cash when the next order arrives."

## 8. Evidence, Proof & Disputes (121–140)

121. Customer sends a photo of the wrong/damaged food — how is it captured/stored?
122. Customer refuses to send a photo but insists on a refund.
123. Photo is clearly of a different restaurant's packaging.
124. Photo is old / reused from a previous complaint.
125. "Rider marked delivered, I say no" — whose word wins? (GPS/photo proof)
126. Rider took a proof-of-delivery photo; customer disputes it.
127. No proof-of-delivery exists for this order.
128. Customer's complaint timestamp is hours after the marked-delivered time.
129. Two customers on one phone dispute the same order's outcome.
130. Customer claims missing item; rider/kitchen say it was packed.
131. Kitchen has a packing checklist; customer disputes it.
132. Customer escalates the same complaint across multiple messages/days.
133. Customer screenshots a different person's refund and demands parity.
134. Voice-note complaint — transcribe, capture intent, attach to order.
135. Complaint in Arabic — capture, classify, respond localized.
136. Customer deletes their messages then claims they reported earlier.
137. Conflicting accounts: customer says cold, rider says handed over hot.
138. Customer claims allergy reaction — needs serious handling + records.
139. Weather-delay was disclosed at order time; customer complains about lateness anyway.
140. Customer claims they "called and reported" but no record exists. (no ticket system today)

## 9. Fraud, Abuse & Serial Complainers (141–160)

141. Same customer claims "missing item" on every order.
142. Customer claims a refund then the food was clearly eaten (delivery logs/timing).
143. Customer orders, eats, complains, repeats — serial refund abuse.
144. Multiple phone numbers, same address, all complaining for freebies.
145. Customer threatens a bad review to extract compensation.
146. Customer threatens to report to authorities over a minor issue.
147. Coordinated group abuse (shared in a WhatsApp group).
148. Customer claims non-delivery on a GPS-confirmed delivery.
149. Refund-farming: cancel-after-delivery loop to trigger apology coupons.
150. Customer disputes COD they actually paid, to get a "refund."
151. Customer redeems an apology coupon then re-complains about the same order.
152. Staff colluding to issue refunds/coupons to friends.
153. Rider colluding to mark delivered + split a fraudulent refund.
154. Customer escalates trivial issues for guaranteed compensation each time.
155. Customer demands compensation exceeding the order value repeatedly.
156. Fake allergy claim to force a free remake.
157. Customer reports an issue only after the loyalty reward posts.
158. Bot prompt-injected into "approving" a refund it shouldn't.
159. High refund rate on one customer — when do we flag/block them?
160. New account immediately files a high-value complaint. (first-order fraud)

## 10. Conversation, Tone & Channel (161–180)

161. Angry, profanity-laden complaint — bot tone + de-escalation.
162. Customer wants a human NOW, not the bot.
163. Bot must detect complaint intent vs a normal status query.
164. Complaint arrives mid a NEW order conversation — switch context cleanly.
165. Customer sends complaint after the WhatsApp 24-hour window closed (template needed).
166. Customer complains via voice note while angry — STT + sentiment.
167. Bot over-apologizes or makes a promise it can't keep.
168. Bot offers compensation the restaurant didn't authorize.
169. Customer satisfied by a quick fix — capture the resolution + close the loop.
170. Customer ignored after deflection ("call us") and churns silently.
171. Complaint needs the manager but it's outside opening hours.
172. Customer expects an instant reply; no agent is online.
173. Multiple complaints flooding in during a kitchen disaster — triage/queue.
174. Customer replies "STOP" out of anger — opt-out vs still needing resolution.
175. Bot must not bury the complaint under upsells/marketing.
176. Customer wants to escalate beyond the restaurant to "the platform."
177. Language switch mid-complaint (Arabic ↔ English ↔ Urdu).
178. Customer demands a callback at a specific time.
179. Sarcasm / ambiguous complaint the bot misreads as positive.
180. Customer complaining on behalf of someone else (gift recipient).

## 11. Operations, SLA & Resolution Workflow (181–195)

181. Who is the owner of a complaint once filed — bot, manager, or platform?
182. What's the target response/resolution time (a complaint SLA)?
183. How does a manager see all open complaints in the dashboard? (none today)
184. How is a complaint linked to the order, rider, and specific dish?
185. How is a resolution recorded and audited (append-only)?
186. When does a complaint auto-issue a goodwill coupon vs require approval?
187. What's the compensation ladder (apology → coupon → refund → remake)?
188. Caps: max compensation per order / per customer / per day.
189. Kill switch: pause auto-compensation when abuse spikes.
190. Reporting: complaint rate by dish, by rider, by time-of-day.
191. Feedback loop: complaints about a dish → flag it to the kitchen/menu.
192. Complaint about a rider → does it affect rider scoring/dispatch?
193. Reconcile a refunded COD order in the end-of-day cash sheet.
194. Don't double-compensate: SLA late-coupon + complaint coupon on one order.
195. Multi-tenant: complaints isolated per restaurant; platform-level visibility separate.

## 12. Legal, Safety & Reputation (196–200)

196. Alleged food poisoning — incident record, escalation, possible authority report (UAE food-safety).
197. Allergy reaction from an ignored note — liability, documentation, duty of care.
198. Customer threatens legal action — what's captured and who's notified?
199. Customer threatens / posts a public review — reputation-management playbook.
200. Data/privacy: complaint contains health info or third-party data — PDPL handling + retention.

---

## 13. Cross-Cutting Challenges (the hard parts)

Most of the 200 collapse into a handful of systemic problems the platform must solve:

1. **No capture layer** — today a complaint vanishes after "call us." Nothing is logged, linked, or auditable. A complaint model (intent + evidence + order/rider/dish links + status FSM) is the prerequisite for everything else.
2. **COD refund mechanics** — there is no captured payment to refund. "Refund" must mean cash-back-on-next-delivery, goodwill credit, or a coupon. The model must make this explicit, not pretend a card refund exists.
3. **Proof & delivery disputes** — "marked delivered vs never received" needs proof-of-delivery (rider GPS + photo) and a clear adjudication rule. Without it, every dispute is he-said-she-said.
4. **Compensation ladder + authority** — apology → coupon → partial refund → remake → full refund, with per-order/per-customer/per-day caps, auto vs manager-approval thresholds, and a kill switch. Outstanding compensation is real liability.
5. **Abuse & velocity control** — COD + self-service + manual orders is a wide fraud surface (serial complainers, refund farming, collusion). Needs velocity checks, a per-customer complaint/refund rate flag, and audit trails.
6. **Intent + sentiment detection** — the conversation engine must distinguish a complaint from a status query, read anger/severity, route to a human, and switch context cleanly (incl. voice notes and Arabic/Urdu).
7. **WhatsApp constraints** — the 24-hour window, template approval, and STOP/opt-out all constrain complaint comms. Transactional resolution messages vs marketing must be classified.
8. **FSM & double-compensation** — a complaint hooks the Order FSM at/after `delivered`; it must not double-pay with the SLA late-coupon, must survive auto-resell/batching edges, and must be idempotent against webhook/outbox retries.
9. **Operational feedback loops** — complaints are data: dish-level quality flags to the kitchen, rider-level signals into dispatch scoring, time-of-day patterns for staffing.
10. **Legal, safety & reputation** — food poisoning and allergy reactions are safety-critical incidents with UAE food-safety + PDPL obligations and reputational stakes; they need a distinct, documented escalation path, not the coupon ladder.

---

## 14. The Universal Complaint-Handling Process

The goal is **one pipeline** that every complaint flows through — cold food, missing item, rude rider, fraud, food poisoning — regardless of type. You do not build 200 handlers; you build one process with a smart decision branch. Each new complaint type just maps to a `(type, severity)` → ladder rung.

### The 6-stage pipeline

```
DETECT → CAPTURE → CLASSIFY → DECIDE → ACT → CLOSE + LEARN
```

---

### Stage 1 — DETECT
The conversation engine flags complaint intent (vs status query / new order).
- Triggers: negative sentiment, keywords (wrong / missing / cold / refund / bad), a photo of food, an angry voice note.
- Works in `post_order` phase AND mid-new-order (must context-switch cleanly).
- Multilingual (EN / AR / UR) + voice (STT → intent).

### Stage 2 — CAPTURE
Create a **Complaint record** — the thing that does not exist today. Without this, nothing else is possible.

```
Complaint:
  id, restaurant_id, customer_id, order_id
  type             (quality | missing | wrong | delivery | payment | rider | safety | fraud-suspect)
  severity         (low | med | high | safety-critical)
  evidence[]       (photos, voice transcript, text)
  status           (open -> triaged -> resolving -> resolved -> closed)
  resolution       (none | apology | coupon | partial_refund | remake | full_refund | escalated)
  compensation_aed
  handled_by       (bot | manager | platform)
  audit[]          (append-only — every state change)
```

Append-only. Linked to the order + rider + dish that caused it.

### Stage 3 — CLASSIFY
Auto-tag type + severity. Severity drives routing:
- **safety-critical** (food poisoning, allergy reaction, foreign object) → instant manager + incident path. **NO coupon ladder.**
- **high** (non-delivery dispute, big catering error, repeat complainer) → manager approval required.
- **low / med** (cold, one missing item, minor quality) → bot may auto-resolve within caps.

### Stage 4 — DECIDE (the compensation ladder)

```
apology  ->  goodwill coupon  ->  partial refund  ->  remake + redeliver  ->  full refund  ->  escalate
(cheap, fast)                                                              (costly, rare)
```

**Decision gates:**
- **Auto (bot)** if severity ≤ med AND within caps (per-order, per-customer-per-month, per-day budget) AND customer not flagged for abuse.
- **Manager approval** if above caps, high severity, repeat complainer, or value > threshold.
- **COD reality:** "refund" = cash-back-on-next-order / goodwill credit / coupon — never a card refund (no card on file).
- **No double-pay:** if an SLA late-coupon was already issued for this order, complaint compensation adjusts or skips.

### Stage 5 — ACT
Issue the resolution through existing primitives:
- coupon → reuse `coupons/service.py` (extend beyond late-only).
- remake → create a linked replacement order + dispatch.
- refund → cash-back ledger entry.
- notify the customer (respect the WhatsApp 24-hour window → use a template if outside).
- Idempotent — survive webhook/outbox retries; never double-compensate.

### Stage 6 — CLOSE + LEARN
- Confirm the resolution with the customer and close the loop (today they are ghosted after "call us").
- Feed signals back:
  - dish complaints → kitchen / menu quality flag.
  - rider complaints → dispatch scoring.
  - patterns → reporting (complaint rate by dish / rider / hour).
- Increment the abuse counter → flags serial complainers for next time.

---

### Guardrails (apply to ALL complaint types)

| Guardrail | Why |
|-----------|-----|
| Per-order / per-customer / per-day compensation caps | Liability control |
| Abuse velocity flag | Serial refund farming |
| Proof rules (rider GPS + photo) for delivery disputes | Resolve he-said-she-said |
| Manager kill switch | Pause auto-comp when abuse spikes |
| Append-only audit | Disputes + accountability |
| Safety incidents bypass the coupon ladder | Legal / food-safety duty of care |
| Multi-tenant isolation | Complaints scoped per restaurant |

---

### Build order (what to ship first)

1. **Complaint model + capture** — the foundation; nothing works without it.
2. **Complaint-intent detection** in the conversation engine.
3. **Compensation ladder + caps + auto/manager gate.**
4. **Manager dashboard complaint queue.**
5. **Feedback loops** (dish / rider / reporting) — last.

The power of one pipeline: a single process with a smart DECIDE branch covers all 200 scenarios above. Every new complaint type is just another `(type, severity)` mapping onto an existing ladder rung — no new handler required.

---

*End of analysis. No code was changed by this document.*
