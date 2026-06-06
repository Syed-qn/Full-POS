# UAT Checklist — Restaurant WhatsApp Platform

**Audience:** a restaurant owner / non-technical tester. No coding knowledge needed — just follow the
steps in order, type exactly what is shown in `quotes`, and tick the box if the result matches.

**What this covers:** the parts of the platform that are built today — manager onboarding, AI menu
digitization, customer ordering by WhatsApp (via a browser simulator), order cancellation, "where is
my order?" status, and the manager dashboard. **What it does NOT cover** (still being built) is listed
at the very bottom under "Known — not yet implemented". Do **not** raise bugs for anything in that list.

**How to read each scenario:**
- **Validates §** — the rule in the design spec this step proves (`docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`).
- **[ ] Pass / [ ] Fail** — tick one. If Fail, write what you actually saw in **Notes**.
- A "step" is one action. The **Expected result** is what you should see right after.

---

## 0. Setup (do this once, in order)

You need four programs running at the same time, each in its **own** terminal window/tab. Leave them
all running for the whole test session. Open the project folder first in every terminal:

```bash
cd "Restaurant Whatsapp Service"     # the project folder
```

| # | What | Command (copy/paste into its own terminal) | You should see |
|---|------|--------------------------------------------|----------------|
| 0.1 | Database + Redis | `docker compose up -d` | lines ending `Started` / `Healthy`; no red errors |
| 0.2 | Create test data DB (first time only) | `docker compose exec db psql -U app -d restaurant -c "CREATE DATABASE restaurant_test;"` | `CREATE DATABASE` |
| 0.3 | Apply database setup | `.venv/bin/alembic upgrade head` | ends with `Running upgrade ... (no errors)` |
| 0.4 | The API server | `.venv/bin/uvicorn app.main:app --reload --port 8000` | `Application startup complete` |
| 0.5 | The background worker | `.venv/bin/celery -A apps.workers.celery_app:celery_app worker --loglevel=info` | `celery@... ready.` |
| 0.6 | The manager dashboard | `cd frontend && npm install && npm run dev` | `Local: http://localhost:5173/` |

**Addresses you will use during testing:**
- API health check: <http://localhost:8000/health> — should show `{"status":"ok"}`.
- API request docs (used for signup/menu steps): <http://localhost:8000/docs>
- Customer WhatsApp simulator: <http://localhost:8000/simulator/>
- Manager dashboard: <http://localhost:5173/>

> Setup acceptance — tick before continuing:
> - [ ] **Pass** / [ ] **Fail** — All four servers (0.4, 0.5, 0.6) plus docker (0.1) are running, and
>   <http://localhost:8000/health> shows `{"status":"ok"}`.
> - Notes: ________________________________________________

> **Note on the simulator (read once):** the simulator is a **text-only** WhatsApp stand-in. It can type
> messages but it **cannot drop a Google-Maps location pin** and **cannot tap blue reply-buttons**. So in
> the ordering scenarios you will type the address as text (the comma format) and type button choices as
> plain words (e.g. type `confirm order`). Distance-based delivery-fee tiers and the >10 km rejection are
> verified separately in **Scenario E** using the API docs page, because they need a real pin.

---

## A. Manager onboarding (signup → login → dashboard)

**Why:** proves a restaurant owner can create an account and reach their dashboard.
**Validates:** §4.1 onboarding, §6 manager JWT auth.

We create the account through the API docs page (no real signup screen is built into the dashboard yet —
the dashboard only has a **login** screen).

| # | Step | Expected result | Pass/Fail | Notes |
|---|------|-----------------|-----------|-------|
| A1 | Open <http://localhost:8000/docs>. Find **POST `/api/v1/auth/signup`**, click **Try it out**. | An editable request box appears. | [ ] P / [ ] F | |
| A2 | Paste this and click **Execute**:<br>`{ "name": "Test Kitchen", "phone": "+97150000001", "password": "test1234", "lat": 25.2048, "lng": 55.2708 }` | Response code **201**. Body shows your restaurant `id`, name, and a `settings` block. | [ ] P / [ ] F | |
| A3 | Repeat the same signup once more (click Execute again). | Response is an **error (4xx)**, not another 201 — the same phone cannot register twice. | [ ] P / [ ] F | |
| A4 | Open the dashboard <http://localhost:5173/>. Log in with phone `+97150000001` and password `test1234`. | Login succeeds and the dashboard loads (live ops / orders board visible). | [ ] P / [ ] F | |
| A5 | Try logging in again with a **wrong** password. | Login is **rejected** with an error message; you stay on the login screen. | [ ] P / [ ] F | |

---

## B. Menu digitization (upload → review → set numbers/prices → activate)

**Why:** proves the AI menu extraction, manager review/edit, and the activation safety gate.
**Validates:** §4.1 menu flow; §1 — dish numbers + prices mandatory, activation blocked otherwise.

> **Fake-extractor note:** in this test environment `APP_LLM_PROVIDER=fake`, so the "AI vision" step is
> simulated by a built-in **FakeExtractor**. It returns a fixed set of draft dishes regardless of the
> file you upload — that is expected and correct for UAT. The real Claude vision model only runs in
> production. So when you upload a menu file you are testing the **pipeline and the review/activate
> rules**, not the accuracy of reading your specific menu image.

All steps use <http://localhost:8000/docs>. You must be **authorized** first.

| # | Step | Expected result | Pass/Fail | Notes |
|---|------|-----------------|-----------|-------|
| B1 | At the top of /docs click **Authorize**. Get a token first: run **POST `/api/v1/auth/login`** (phone `+97150000001`, password `test1234`), copy the `access_token` from the response, then in the Authorize box enter `Bearer <that token>`. | The padlock icons close — you are authorized. | [ ] P / [ ] F | |
| B2 | Run **POST `/api/v1/menus`** (upload). Click **Try it out**, choose any small image or PDF file as the upload, **Execute**. | Response **201**. Body shows a new menu (status like `pending_confirmation`) with a list of **draft dishes**. Note the menu `id`. | [ ] P / [ ] F | |
| B3 | Run **GET `/api/v1/menus/{menu_id}`** with that id. Look at the dishes. | You see the draft dishes with names. Some may be **missing a dish number or price** (incomplete drafts). | [ ] P / [ ] F | |
| B4 | **Negative case — blocked activation:** while at least one dish still lacks a number or price, run **POST `/api/v1/menus/{menu_id}/activate`**. | Activation is **rejected** with an error explaining a dish is missing a number/price. Menu does **not** become active. | [ ] P / [ ] F | |
| B5 | Fix the drafts: for each dish missing data, run **PATCH `/api/v1/menus/{menu_id}/dishes/{dish_id}`** and set a `dish_number` and a `price_aed` (e.g. number `110`, price `22.00`). Give each dish a unique number. | Each PATCH returns **200** with the updated dish. | [ ] P / [ ] F | |
| B6 | Now run **POST `/api/v1/menus/{menu_id}/activate`** again. | Response **200**; menu status becomes **`active`**. | [ ] P / [ ] F | |
| B7 | Open the dashboard → **Menu Manager** screen. | The activated dishes appear with their numbers and prices. | [ ] P / [ ] F | |

> Keep a note of two dish numbers + names from your active menu (e.g. `110. Chicken Biryani`,
> `111. Special Chicken Biryani`) — you will order them in Scenario C.

---

## C. Customer ordering via the simulator (happy path)

**Why:** the core flow — a customer orders entirely by WhatsApp text.
**Validates:** §4.2 — greeting→menu, dish capture by number, quantity, address (text path), receiver,
totals + COD + 40-min ETA confirmation.

Open the simulator <http://localhost:8000/simulator/>. At the top set:
- **Customer phone (From):** `+97155000111`
- **Restaurant phone:** `+97150000001` (the one you signed up with in A2)

Type each message into the box and press send. Wait ~1–2 seconds for the reply bubble.

| # | You type | Expected reply | Pass/Fail | Notes |
|---|----------|----------------|-----------|-------|
| C1 | `hi` | The **digital menu** appears: a categorized list like `110. Chicken Biryani — AED 22`. Never a raw PDF. | [ ] P / [ ] F | |
| C2 | `110` (a real dish number from your menu) | `Added 1x 110. <name> (AED ..). Reply with more items, or send 'done' ...` | [ ] P / [ ] F | |
| C3 | `2 111` (quantity 2 of dish 111) | `Added 2x 111. <name> ...` — quantity recognised. | [ ] P / [ ] F | |
| C4 | `done` | `Great! Please share your delivery location pin, or type your address.` | [ ] P / [ ] F | |
| C5 | `101, Tower A` (room, building — comma is required) | `Address noted: room/apartment 101, building Tower A. Who should the rider ask for? ...` | [ ] P / [ ] F | |
| C6 | `Ahmed` (receiver name) | **Order summary**: item lines with line totals, **Subtotal**, **Delivery fee**, **Total**, `Payment: COD (cash on delivery)`, `ETA: 40 minutes`, and a confirm prompt. | [ ] P / [ ] F | |
| C7 | Check the math in C6. | Subtotal = sum of (qty × price); Total = Subtotal + Delivery fee. (With the text-address path the fee shows **AED 0** — see note below.) | [ ] P / [ ] F | |
| C8 | `confirm order` | `Order confirmed! Order #<n>. Total: AED .. (COD ...). Your food will arrive within 40 minutes.` | [ ] P / [ ] F | |

> **Fee note for C7:** because the simulator cannot drop a map pin, this order has no measured distance, so
> the fee is **AED 0 (free tier)**. That is expected here. The **distance-based fee tiers** (≤3 km free /
> 3–5 km AED 5 / >5 km AED 10) and the **>10 km rejection** are verified in **Scenario E**. — Validates §1.

> Negative-format check (optional): in C5 type an address **without a comma** (e.g. `101 Tower A`). Expected:
> the bot asks you to include a comma and gives the example. Then re-send with the comma. — Validates §4.2.

---

## D. Cancel before cooking, and "where is my order?"

**Why:** proves a customer can cancel an un-cooked order and can ask for status anytime.
**Validates:** §4.2 step 8/9 — cancellation before `ready`; status reply with ETA.

Use the **same** customer phone `+97155000111` and restaurant `+97150000001`.

### D-cancel — cancel a fresh order before it is confirmed

| # | You type | Expected reply | Pass/Fail | Notes |
|---|----------|----------------|-----------|-------|
| D1 | `hi` | Menu appears again. | [ ] P / [ ] F | |
| D2 | `110` | `Added 1x 110. ...` | [ ] P / [ ] F | |
| D3 | `done` then `101, Tower A` then `Ahmed` | You reach the order summary with confirm/cancel prompt. | [ ] P / [ ] F | |
| D4 | `cancel` | `No problem — your order has been cancelled. Send 'hi' to start again.` | [ ] P / [ ] F | |

### D-status — ask where the order is (use the order confirmed in Scenario C)

| # | You type | Expected reply | Pass/Fail | Notes |
|---|----------|----------------|-----------|-------|
| D5 | `where is my order` | A status line about your confirmed order #, e.g. "...is confirmed and will be ready in about 40 minutes", and may add `Estimated time remaining: ~NN minutes`. | [ ] P / [ ] F | |
| D6 | From a **brand-new** customer phone (change From to `+97155000999`), type `where is my order` | `I don't see any recent orders for this number...` — the bot does not leak another customer's order. | [ ] P / [ ] F | |

> **Cancel-after-cooking** (auto-resale, exclusion by phone/person/address — §1) cannot be exercised from
> the customer simulator today because moving an order into the kitchen (`preparing`/`ready`) needs the
> dispatch/kitchen tooling from Phase 4. See "Known — not yet implemented".

---

## E. Edge cases

**Why:** proves the bot handles bad/edge input gracefully and enforces the delivery radius.
**Validates:** §4.2 dish matching (no-match / ambiguous), §1 radius + fee tiers, availability hiding.

### E-text — run these in the simulator (customer `+97155000222`, restaurant `+97150000001`)

| # | You type | Expected reply | Pass/Fail | Notes |
|---|----------|----------------|-----------|-------|
| E1 | `hi` then `pizza` (a dish **not** on the menu) | `Sorry, I couldn't find that dish. Please reply with the dish number ...` — no crash. | [ ] P / [ ] F | |
| E2 | A name that partly matches **two** dishes (e.g. type `chicken` when you have `110. Chicken Biryani` and `111. Special Chicken Biryani`) | `Did you mean 110. ... or 111. ...? Please reply with the dish number.` | [ ] P / [ ] F | |
| E3 | Then reply with one of the offered numbers (e.g. `110`) | `Added 1x 110. ...` — disambiguation resolves cleanly. | [ ] P / [ ] F | |

### E-availability — toggle a dish off and confirm it disappears from the menu

| # | Step | Expected result | Pass/Fail | Notes |
|---|------|-----------------|-----------|-------|
| E4 | In the dashboard **Menu Manager**, toggle one dish to **unavailable** (or via /docs: **PATCH `/api/v1/dishes/{dish_id}/availability`** with `{"is_available": false}`). | Toggle succeeds. | [ ] P / [ ] F | |
| E5 | In the simulator, from a new customer phone, type `hi`. | The menu now renders **without** that dish. Toggling reflects immediately on the next menu. | [ ] P / [ ] F | |
| E6 | Toggle the same dish back **available**; type `hi` again from a new phone. | The dish reappears in the menu. | [ ] P / [ ] F | |

### E-radius — distance fee tiers + >10 km rejection (needs a real pin, so use /docs)

The simulator can't send a pin, so inject a location event through the webhook test view. If your tester
cannot do this comfortably, mark these rows **N/A** and hand them to a technical reviewer — but they MUST
be checked before go-live.

| # | Step (technical reviewer) | Expected result | Pass/Fail | Notes |
|---|---------------------------|-----------------|-----------|-------|
| E7 | Send the customer a **location** message at ~2 km from the restaurant (lat/lng close to `25.2048, 55.2708`). | Delivery fee on the summary = **AED 0** (≤3 km free). | [ ] P / [ ] F | |
| E8 | A pin at ~4 km. | Fee = **AED 5** (3–5 km). | [ ] P / [ ] F | |
| E9 | A pin at ~7 km. | Fee = **AED 10** (>5 km). | [ ] P / [ ] F | |
| E10 | A pin **>10 km** away. | `Sorry, your location is outside our delivery area (maximum 10 km)...` — order is **not** placed. | [ ] P / [ ] F | |

---

## F. Manual takeover silences the bot

**Why:** a manager must be able to step into a chat and have the robot go quiet.
**Validates:** §2 "Manual override everywhere"; §4.8 conversation viewer + manual takeover.

| # | Step | Expected result | Pass/Fail | Notes |
|---|------|-----------------|-----------|-------|
| F1 | In the simulator start a chat: customer `+97155000333` types `hi` → menu appears. | Bot replies normally. | [ ] P / [ ] F | |
| F2 | In the dashboard **Conversations** screen, open that customer's conversation and switch on **Manual takeover** (manager takes over). | The conversation is marked as taken over by the manager. | [ ] P / [ ] F | |
| F3 | Back in the simulator, the customer types `110`. | **No automatic reply** appears — the bot stays silent while the human is in control. | [ ] P / [ ] F | |
| F4 | Turn manual takeover **off** again, customer types `hi`. | The bot resumes replying. | [ ] P / [ ] F | |

> If your dashboard build does not yet expose a takeover switch (dashboard is ~75% complete), mark F2–F4
> **N/A** and note it — this is a known dashboard gap, not a bot bug.

---

## G. Dashboard live ops & menu manager

**Why:** the manager's command center shows live orders, SLA colours, and the menu.
**Validates:** §4.8 dashboard — KPIs, SLA board colours, menu manager diff, availability.

| # | Step | Expected result | Pass/Fail | Notes |
|---|------|-----------------|-----------|-------|
| G1 | After confirming an order in Scenario C, open the dashboard **Live Ops** board. | The confirmed order appears as a live order row. | [ ] P / [ ] F | |
| G2 | Look at the order's **SLA countdown**. | A countdown timer is shown; its colour reflects urgency (e.g. normal → yellow as it approaches 30 min → red near breach). | [ ] P / [ ] F | |
| G3 | Open **Menu Manager**. After a re-upload that changes a price, a **diff panel** highlights what changed (old → new price). | Changed dishes are flagged in the diff view. (If you haven't re-uploaded, mark N/A.) | [ ] P / [ ] F | |
| G4 | Cross-check E4–E6: a dish you toggled unavailable is visibly marked as such in Menu Manager and is hidden from the next simulator menu render. | Availability state is consistent between dashboard and the customer menu. | [ ] P / [ ] F | |

> The dashboard is approximately **75% complete**. If a screen above is missing or a control is not wired,
> mark the row **N/A** with a note rather than **Fail** — these are tracked dashboard gaps.

---

## Sign-off

| Scenario | Result (Pass / Fail / Partial) | Tester | Date |
|----------|-------------------------------|--------|------|
| A — Onboarding | | | |
| B — Menu digitization | | | |
| C — Ordering happy path | | | |
| D — Cancel + status | | | |
| E — Edge cases | | | |
| F — Manual takeover | | | |
| G — Dashboard | | | |

Overall UAT verdict: **[ ] Accepted   [ ] Accepted with notes   [ ] Rejected**

Tester signature: ______________________  Date: ____________

---

## Known — not yet implemented (do NOT file bugs for these)

The platform is built in phases. **Phases 0–3 are done; the dashboard (Phase 5) is ~75% complete.** The
following are intentionally **not yet present** — testers must not report them as defects:

- **Rider dispatch & logistics (Phase 4):** nearest-rider auto-dispatch, smart batching (≤3 orders / 10-min
  window / proximity), the delivery FSM, live rider GPS tracking, geofence "Delivered / next stop" buttons.
- **SLA monitor & automatic coupons (Phase 4):** the 30/35/40-minute heartbeat alerts and the automatic
  late-delivery coupon (and the weather-delay exception that suppresses it). The SLA countdown shown on the
  dashboard is a display only; no automated breach action runs yet.
- **COD ledger (Phase 4):** "Collect money & delivered", rider shift cash reconciliation.
- **Cancel-after-cooking auto-resale (Phase 4 tooling):** the resale offer + exclusion by phone/person/address
  exists in the rules but cannot be exercised end-to-end until kitchen/dispatch tooling lands.
- **Order modification dialogue (partial):** changing an order after confirmation (which restarts the SLA
  clock) is supported in the backend but is **not yet wired into the chat flow** — there is no "modify my
  order" conversation today.
- **ML demand predictions (Phase 6):** forecast panel, plain-English override box, accuracy/MAPE tracking.
- **Marketing automation (Phase 6/7):** Today's Special template pipeline, Meta template approval lifecycle,
  plain-English segments/automations, recurring promo scheduler, STOP opt-out.
- **Real WhatsApp & real AI/Maps:** in this test environment the WhatsApp provider is a **Mock** (the
  simulator), the menu AI is the **FakeExtractor**, and geo uses a haversine fallback. No messages are sent
  to real phones and no external AI/Maps calls are made.
- **Simulator limitations:** the browser simulator is **text-only** — it cannot send a map **location pin**
  or tap blue reply-**buttons**. Type button choices as words (e.g. `confirm order`, `cancel`). Pin-dependent
  checks (Scenario E7–E10) require a technical reviewer.
- **Dashboard gaps:** any screen/control not yet wired in the ~75%-complete dashboard — mark **N/A**, not Fail.
