# Full POS — Complete Feature Catalog

**Product:** Full POS (Catalystiq) — multi-tenant restaurant POS + WhatsApp delivery + AI + data science  
**Document date:** 2026-07-13  
**Purpose:** Single inventory of **everything** a user can open, use, edit, or operate — across desktop app (Windows/macOS), cloud manager console, WhatsApp, rider app, kitchen KDS, public pages, and integrations.  
**How to read:**  
- **Sections A–H** = interactive product surfaces (screens, buttons, roles, channels).  
- **Section I** = full named feature matrix from the advanced POS audit (order types through AI + UI shell).  
- **Evidence / implementation notes:** `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md`  
**Scope note:** Catalog features (1–14) are implemented as working product paths (API + UI and/or channel). Marketplace: **Talabat**, **Deliveroo**, and **Keeta** use **brand-specific real adapters** when `mode=live` + credentials; Careem/Noon/Uber/Zomato use generic live HTTP or mock. Default without credentials is **mock**.  
**UI redesign (2026-07-09/10):** Touch-first shell (Phases 0–5) — Floor Plan, Order Detail page, Checkout, Expo KDS, Rider web app, manager PIN gates, offline banners, role-filtered nav. Plan: `docs/superpowers/plans/2026-07-09-pos-frontend-uiux-redesign-phases.md`.

### Contents
- [A. Who can do what](#a-who-can-do-what-actors)
- [B. Full POS manager app screens](#b-full-pos-manager-app--every-screen-you-can-open)
- [C. Desktop app extras](#c-desktop-app-extras-local-software)
- [D. Customer on WhatsApp](#d-customer-on-whatsapp--interactive-capabilities)
- [E. Rider app](#e-rider-app--interactive-capabilities)
- [F. Kitchen KDS](#f-kitchen-staff-on-kds--interactive-capabilities)
- [G. Partner / marketplace](#g-partner--marketplace-integrations-operator--system)
- [H. Enforced business rules](#h-business-rules-the-product-always-enforces)
- [I. Complete feature matrix](#i-complete-feature-matrix-product-features)
- [J. Counts](#j-counts)
- [K. Related docs](#k-related-docs)

---


## A. Who can do what (actors)

| Actor | Surfaces | What they do |
|-------|----------|--------------|
| **Restaurant manager / owner** | Full POS desktop (Windows `.exe` x64/arm64, Mac `.app`/`.dmg`) **or** cloud console; email login | Full nav: ops, menu, inventory, payments, staff, marketing, AI, compliance, reports, multi-branch HQ |
| **Cashier** | Full POS + staff **PIN** (`role=cashier`) | Floor, Orders, New Order, Checkout/Payments, Customers — no Menu/Settings/Marketing |
| **Floor / waiter / counter staff** | Full POS + PIN (`role=staff` or `cashier`) | Floor Plan tables, New Order, Orders/modify, payments (role-gated) |
| **Kitchen staff** | KDS (`/kds`, Expo view); PIN `role=kitchen` | Bump/start/recall, packaging/QC/missing, station boards — no New Order/admin |
| **Customer (WhatsApp)** | WhatsApp Business chat | Order, modify, track, pay COD, redeem wallet/coupons, complain, STOP marketing, voice notes |
| **Customer (web/QR/kiosk)** | Public store `/order/:slug` (+ `?table=`), tracking `/track/:token` | Browse menu, place order, locked table QR, track delivery |
| **Rider (employee)** | Native rider app + **web** `/rider-app` + optional WhatsApp | Pair device, duty, GPS, pickup/deliver, COD, proof, OTP, fail reasons |
| **Franchise / org HQ** | Branches screen (org APIs) | Multi-branch menu publish, stock transfer, royalty, shared loyalty, promotions |
| **POS partner (e.g. Cratis)** | Partner REST + webhooks | Push kitchen status, sync menu, chat takeover, order events |
| **Marketplace (Talabat, Deliveroo, Keeta, …)** | Aggregator webhooks + brand adapters | Inbound orders, accept/reject, status push, menu/stock sync where configured |

**Nav soft-gates:** `frontend/src/lib/navAccess.ts` — owner/manager (or missing role) see everything; restricted roles hide admin modules. Shared screens, not separate apps per job.

---

## B. Full POS manager app — every screen you can open

Navigation (UI/UX redesign): **Daily** → **Manage** → **More**. Collapsible sidebar 88/240 px. Touch targets ≥56 px; primary actions ≥64 px.

### Daily (ops first)
| Screen | Route | User can |
|--------|-------|----------|
| Live Ops | `/` | Rush board (New/Preparing/Ready/Out/**Late**), SLA lanes, map, rider strip, bottom quick actions (New Order, Orders, Riders, KDS) |
| Floor Plan | `/floor` | Zone tabs, touch table map, status colors, table drawer, New Table Order / Transfer / Merge / Split (confirm) |
| Orders | `/orders` | Card-first list, filters/search by status/channel/phone, preview drawer |
| Order Detail | `/orders/:id` | Full order page: items, SLA, timeline, kitchen/rider/payment; Pay, rush, void (**manager PIN**), print |
| New Order | `/new-order` | 3-pane POS: order type rail, category grid, cart always visible, bottom Clear/Place |
| Checkout | `/orders/:id/pay` | Tender grid (cash/card/wallet/link/…), keypad, tips, split, MoneySummary; discount/refund **PIN** |
| Kitchen (KDS) | `/kds`, `/kds/:stationId` | Large tickets, 64px bump/start, allergens, urgency colors, stations |
| Expo / Ready pickup | `/kds?view=expo` | Ready tickets, packaging checklist, missing confirm, handoff actions |
| Payments (back office) | `/payments` | Tenders, refunds (**PIN**), links, gift cards, drawer, recon, billing |
| Riders (dispatch) | `/riders` | Unassigned SLA queue · live map · fleet; Manual Assign, Settle COD, add rider |
| Chats | `/conversations` | 3-pane: list · transcript · customer context; AI takeover, quick replies |

### Manage
| Screen | Route | User can |
|--------|-------|----------|
| Menu | `/menu` | Categories, dishes, variants, modifiers, combos, pricing rules, CSV import, bulk price, approve, images, allergens, AR, seasonal |
| Inventory | `/inventory` | Stock, low-stock banner, PO/GRN, waste, variance, vendors; stock adjust **PIN** |
| Customers | `/customers` | Phone-first search, segments, preview drawer |
| Customer profile | `/customers/:id` | Notes/allergies/VIP, favorites, points, stamps, wallet, reorder last, referral |
| Staff | `/staff` | PIN, roles, shifts, clock/break, attendance, tips, mistakes, training mode, approvals |
| Marketing | `/marketing` | Templates, campaigns, segments, automations, broadcast, schedule, today’s special |
| Reports | `/reports` | Owner reports, date range, Excel export, WhatsApp daily report |
| AI Insights | `/ai` | Insight cards + actions: sales/staff/stock, segments, festival, review reply, translate, calls, reservations |
| Branches | `/branches` | Org HQ: rollups, menu publish, stock transfer, royalty, promotions |
| Channels | `/channels` | Enable/pause (**PIN** on pause), live keys, sync, commission/profit, settlements; **Talabat / Deliveroo / Keeta / Careem / Noon / Uber / Zomato** + website/QR/kiosk links |
| Reliability | `/reliability` | Backups, devices, errors, audit, conflicts, network; desktop offline queue |
| Settings | `/settings` | Profile, tax/TRN, batching, zones/fees, hours, Meta WhatsApp, loyalty/resale, cart recovery; sticky save |

### More (manager secondary)
| Screen | Route | User can |
|--------|-------|----------|
| Complaints | `/tickets` | Tickets, evidence, resolve wallet/replacement |
| Coupons | `/coupons` | Create/issue/pause coupons, margin warnings |
| Compliance | `/compliance` | TRN/tax, invoices, refund notes, e-invoice, retention, accountant export |
| Analytics | `/analytics` | Forecasts, dispatch/delivery KPIs |
| Forecast | `/predictions` | Alias of analytics/forecast |

### Auth / setup (no main nav)
| Screen | Route | User can |
|--------|-------|----------|
| Login / Signup | `/login` | Email login **or** staff PIN pad; device name; offline PIN messaging |
| Onboarding | `/onboarding` | Wizard: WhatsApp, location, blockers; sticky Back/Continue |

### Public (no login)
| Screen | Route | User can |
|--------|-------|----------|
| Public storefront | `/order/:slug` | Mobile menu, sticky cart, place order |
| QR table ordering | `/order/:slug?table=` | Table **locked** banner; dine-in QR channel + `table_id` |
| Customer tracking | `/track/:trackingToken` | Status timeline + simple ETA; map only when rider en route |
| Rider share track | `/rider-track/:riderToken` | Customer views rider location |
| Rider web app | `/rider-app` | Pair code, duty, COD, sticky pickup → deliver / fail |

### Shell chrome (every authenticated screen)
| Capability | User can |
|------------|----------|
| Top bar | Page title, restaurant name, **Offline** badge, pending sync chip, **Alerts**, Staff entry, clock, Reliability link |
| Alert center | Late/low-stock/sync-style alerts panel |
| Offline limits banner | Core screens show what still works offline vs blocked |
| Manager PIN modal | Void, refund, manager discount, stock adjust, channel pause |
| Training mode chrome | Badge + shell warning when staff session is training |
| No-access screen | Friendly block if role cannot open route |

---

## C. Desktop app extras (local software)

When running as **Full POS** Electron (`.exe` / `.dmg` / `.app`), the user also gets:

| Capability | Interaction |
|------------|-------------|
| Local terminal status bar | Online/offline, pending sync count, conflicts |
| Offline order queue | Take orders without internet; sync when back |
| Offline payments ledger | Record payments offline; apply on reconnect |
| Offline KOT / receipt spool | Print jobs written to local spool / failover printer |
| Local SQLite cache | Menu + orders cached on device |
| Auto-sync every ~15s | Push pending ops, pull menu/orders |
| Conflict resolve | Retry or discard conflicting ops in Reliability |
| Auth token in main process | Secure handoff for offline API proxy |
| Auto-update channel | Polls `POS_UPDATE_URL` when configured |
| Window chrome | Native window **Full POS**, 1440×900 default, light POS theme, no browser URL bar |
| Mac arm64 / x64 packages | `desktop/dist_installer/FullPOS-0.1.0-arm64.dmg` (+ x64); API base baked at FE build (`VITE_API_BASE`) |
| `posBridge` | Network status, pending ops, conflict resolve, offline print from UI |

---

## D. Customer on WhatsApp — interactive capabilities

| User action | What happens |
|-------------|--------------|
| Say hi / start chat | Conversation engine greets; may show menu / catalog |
| Order by dish number or name | AI matching + cart |
| Voice note order | STT → text → same order path |
| Browse / ask recommendations | Suggestion agent grounded in real menu |
| Upsell / add more | Upsell rules + AI copy |
| Set qty, notes, modifiers | Cart tools |
| Provide address / pin location | Distance, fee tiers, radius check |
| Confirm order | SLA starts, VAT snapshot, wallet apply, KDS tickets, inventory deduct, partner push |
| Modify before ready | Allowed; SLA restarts after confirm |
| Cancel | Rules by stage; post-cook → resale |
| “Where is my order?” | Status + ETA explanation |
| Redeem coupon / wallet | Applied to COD due |
| Complain | Complaint agent + ticket for staff |
| STOP | Marketing opt-out |
| Catalog order (Meta) | Cart from WhatsApp catalog products |
| Abandoned cart | AI recovery nudge after quiet period |

---

## E. Rider app — interactive capabilities

Surfaces: **native** `rider-app/` (Expo) and **web** `/rider-app` (`RiderAppScreen`).

| User action | What happens |
|-------------|--------------|
| Pair with WhatsApp / device code | Stores rider device token (web) |
| Login with rider credentials | Rider session (native) |
| Go on/off duty | Duty toggle; dispatch sees availability |
| View assigned tasks | Queue of pickups/deliveries + COD strip |
| Navigate with map | Live map / open maps |
| Advance status (one primary sticky action) | Picked up → arriving → delivered |
| Share live GPS | Location pings for tracking links & dispatch |
| Collect COD | Cash due visible before deliver |
| Delivery proof photo | Upload / attach proof (native path) |
| OTP confirm (if required) | Customer code at door |
| Mark undeliverable | Failure reason **required** |
| Push notifications | Task alerts (when FCM configured) |

---

## F. Kitchen staff on KDS — interactive capabilities

Touch-first redesign: large ticket cards, allergen banners, ≥64 px Start/Bump.

| User action | What happens |
|-------------|--------------|
| Switch station | Grill/fry/beverage/dessert/pizza/cloud boards |
| See urgency colors / timers | Age, delayed, rush (safe/warn/late) |
| Start prep | Ticket → preparing (large control) |
| Bump ready | Ticket → ready / bumped |
| Recall | Undo bump |
| Packaging / quality / missing | Checklist stamps |
| Expo view (`?view=expo`) | Ready-only board, packaging, handoff to rider/customer |
| Performance tab | Prep times by item/staff |
| Printer jobs | Desktop poller prints KOTs; fallback station |

---

## G. Partner / marketplace integrations (operator + system)

| Integration | Operator can | Adapter mode |
|-------------|----------------|--------------|
| Meta WhatsApp | Connect/disconnect WABA, re-subscribe, catalog sync/push | Cloud API / mock |
| Cratis / partner POS | API keys, menu/order sync, kitchen status webhooks | Partner REST |
| **Talabat** | Enable, `mode=live`, middleware username/password, vendor remote id, health, pause (**PIN**), sync, recon | **Real** `TalabatAdapter` (Delivery Hero POS Middleware — accept/reject/prep-complete) · [docs](https://integration.talabat.com/en/documentation/) |
| **Deliveroo** | Live API key/token, site id, webhook HMAC, pause, accept/reject | **Real** `DeliverooAdapter` (PATCH order status) · [docs](https://api-docs.deliveroo.com/docs/order-integration) |
| **Keeta** | Live appId/appSecret/accessToken, shopId, signed Open API | **Real** `KeetaAdapter` (confirm/cancel/prepare) · [docs](https://api-docs.mykeeta.com/apis/standard/docs/intro) |
| Careem / Uber Eats / Noon / Zomato | Enable, live key, health, pause, sync | **Generic** `LiveHttpAggregator` or **mock** until brand OpenAPI mapped |
| Website / QR / kiosk / Instagram / GBP | Public slug, order links, pause accepting | Public storefront APIs |
| Stripe / card gateways | Store credentials (Payments), payment links | Gateway ports |
| Cloud backups | Manual/daily backup, verify, restore preview | Reliability module |

**Inbound path:** marketplace webhook → parse (provider-native shapes) → internal order FSM → KDS/dispatch.  
**Outbound path:** accept/reject/status from POS → brand adapter when live.

---

## H. Business rules the product always enforces

These are not optional UI toggles; they constrain every order:

- COD-first delivery model with configured tenders layered on  
- Max **10 km** delivery radius  
- Fee tiers: ≤3 km free / 3–5 km AED 5 / >5 km AED 10 (zones can override)  
- Customer SLA **40 min**; internal batching targets **30 min** + 10 min buffer per batched stop  
- Riders are employees (no accept/reject)  
- Modify only before `ready`; SLA restarts after re-confirm  
- Late delivery auto-coupon unless weather disclosed at order  
- Cancel-after-cook → resale, excluded from same phone/person/address  
- Dish number + price required to activate menu  
- Customer-facing dish text max 3 lines, never includes price  
- Marketing STOP honored  

---

## I. Complete feature matrix (product features)

Every named capability below is **implemented** and available for users to use or configure (via UI, WhatsApp, rider app, KDS, desktop offline, or API-backed automation).  

Source tables: `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md` (2026-07-09).


### Category 1 — Order management (32 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Dine-in orders |
| 2 | Takeaway orders |
| 3 | Delivery orders |
| 4 | Online orders |
| 5 | QR code orders |
| 6 | Tableside orders |
| 7 | Drive-thru orders |
| 8 | Aggregator orders |
| 9 | Open orders |
| 10 | Held orders |
| 11 | Scheduled orders |
| 12 | Pre-orders |
| 13 | Reorders |
| 14 | Refund orders |
| 15 | Cancelled orders |
| 16 | Partial cancellation |
| 17 | Void order with manager approval |
| 18 | Edit order after sending to kitchen |
| 19 | Add item notes |
| 20 | Add kitchen notes |
| 21 | Customer allergy notes |
| 22 | Course-wise ordering |
| 23 | Fire course later |
| 24 | Rush order button |
| 25 | Priority order button |
| 26 | Duplicate order |
| 27 | Repeat last order |
| 28 | Split order by item |
| 29 | Split order by seat |
| 30 | Merge orders |
| 31 | Transfer order between tables |
| 32 | Transfer order between staff |

### Category 2 — Kitchen and preparation (30 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Kitchen Display System |
| 2 | Kitchen Order Ticket |
| 3 | Station-wise routing |
| 4 | Grill station |
| 5 | Fry station |
| 6 | Beverage station |
| 7 | Dessert station |
| 8 | Pizza station |
| 9 | Cloud kitchen station |
| 10 | Prep time tracking |
| 11 | Estimated ready time |
| 12 | Auto-prioritize old orders |
| 13 | Color-coded order urgency |
| 14 | Order bump screen |
| 15 | Recall completed ticket |
| 16 | Delayed ticket warning |
| 17 | KDS item timer |
| 18 | Kitchen performance report |
| 19 | Average prep time by item |
| 20 | Average prep time by staff |
| 21 | Late order alerts |
| 22 | Multi-kitchen routing |
| 23 | Printer fallback if KDS fails |
| 24 | Kitchen printer routing by item category |
| 25 | Allergen warning on kitchen ticket |
| 26 | Modifier display on ticket |
| 27 | Packaging checklist |
| 28 | Missing item confirmation |
| 29 | Quality check status |
| 30 | Ready for pickup status |

### Category 3 — Menu and item control (35 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Menu categories |
| 2 | Subcategories |
| 3 | Item variants |
| 4 | Item sizes |
| 5 | Add-ons |
| 6 | Modifiers |
| 7 | Forced modifiers |
| 8 | Optional modifiers |
| 9 | Combo meals |
| 10 | Meal bundles |
| 11 | Upsell rules |
| 12 | Cross-sell rules |
| 13 | Happy hour pricing |
| 14 | Time-based pricing |
| 15 | Channel-based pricing |
| 16 | Branch-based pricing |
| 17 | Delivery-only menu |
| 18 | Dine-in-only menu |
| 19 | QR-only menu |
| 20 | Cloud kitchen brand menus |
| 21 | Menu item availability |
| 22 | Auto-hide out-of-stock item |
| 23 | Item countdown |
| 24 | Recipe linking |
| 25 | Ingredient linking |
| 26 | Allergen tags |
| 27 | Nutrition data |
| 28 | Item images |
| 29 | Multilingual menu |
| 30 | Arabic menu |
| 31 | English menu |
| 32 | Menu approval workflow |
| 33 | Bulk menu import |
| 34 | Bulk price update |
| 35 | Seasonal menu scheduling |

### Category 4 — Inventory and food-cost (29 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Ingredient-level inventory |
| 2 | Recipe-level costing |
| 3 | Stock deduction by recipe |
| 4 | Wastage tracking |
| 5 | Spoilage tracking |
| 6 | Stock transfer |
| 7 | Multi-location stock |
| 8 | Stock count |
| 9 | Stock variance report |
| 10 | Par level |
| 11 | Reorder point |
| 12 | Supplier management |
| 13 | Purchase orders |
| 14 | Goods received note |
| 15 | Cost price tracking |
| 16 | Vendor price comparison |
| 17 | Food cost percentage |
| 18 | Gross margin by item |
| 19 | Over-portioning alerts |
| 20 | Theft/loss alerts |
| 21 | Expiry date tracking |
| 22 | Batch tracking |
| 23 | Central kitchen inventory |
| 24 | Commissary kitchen support |
| 25 | Ingredient substitution |
| 26 | Low-stock WhatsApp alert |
| 27 | Daily stock closing report |
| 28 | Stock adjustment approval |
| 29 | Recipe yield tracking |

### Category 5 — Payment and billing (34 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Cash |
| 2 | Card |
| 3 | Tap to pay |
| 4 | Apple Pay |
| 5 | Google Pay |
| 6 | Online payment |
| 7 | Payment link |
| 8 | Split payment |
| 9 | Partial payment |
| 10 | Pay later |
| 11 | House account |
| 12 | Room charge for hotels |
| 13 | Tips |
| 14 | Service charge |
| 15 | Delivery charge |
| 16 | Packaging charge |
| 17 | Minimum order charge |
| 18 | Discount codes |
| 19 | Staff discount |
| 20 | Manager discount |
| 21 | Loyalty redemption |
| 22 | Gift card redemption |
| 23 | Refunds |
| 24 | Partial refunds |
| 25 | Credit note |
| 26 | Deposit payment |
| 27 | Advance payment |
| 28 | End-of-day cash closing |
| 29 | Cash drawer management |
| 30 | Cash in/out |
| 31 | Over/short cash report |
| 32 | Payment reconciliation |
| 33 | Failed payment handling |
| 34 | Duplicate payment detection |

### Category 6 — Customer, CRM, and loyalty (31 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Customer profile |
| 2 | Phone number history |
| 3 | WhatsApp opt-in |
| 4 | Order history |
| 5 | Favorite items |
| 6 | Last order shortcut |
| 7 | Customer notes |
| 8 | Allergy notes |
| 9 | Birthday |
| 10 | Anniversary |
| 11 | VIP tag |
| 12 | Complaint history |
| 13 | Refund history |
| 14 | Loyalty points |
| 15 | Cashback |
| 16 | Stamp card |
| 17 | Gift cards |
| 18 | Referral rewards |
| 19 | Coupon campaigns |
| 20 | Win-back campaigns |
| 21 | Birthday offers |
| 22 | Inactive customer campaigns |
| 23 | Customer segmentation |
| 24 | High-value customer list |
| 25 | Average order value by customer |
| 26 | Customer lifetime value |
| 27 | Feedback collection |
| 28 | Review request automation |
| 29 | NPS survey |
| 30 | Negative review escalation |
| 31 | Personalized offers |

### Category 7 — Delivery management (29 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Delivery order dashboard |
| 2 | Manual driver assignment |
| 3 | Auto driver assignment |
| 4 | Driver app |
| 5 | Driver live location |
| 6 | Rider status |
| 7 | Pickup status |
| 8 | Out-for-delivery status |
| 9 | Delivered status |
| 10 | Failed delivery status |
| 11 | Customer location pin |
| 12 | Address notes |
| 13 | Building/floor/apartment fields |
| 14 | Delivery zone pricing |
| 15 | Delivery distance calculation |
| 16 | ETA calculation |
| 17 | Delivery route optimization |
| 18 | Priority delivery |
| 19 | Multi-order batching |
| 20 | Driver cash collection |
| 21 | Driver settlement |
| 22 | Delivery proof photo |
| 23 | OTP delivery confirmation |
| 24 | Customer tracking link |
| 25 | WhatsApp delivery updates |
| 26 | Late delivery alert |
| 27 | Driver performance report |
| 28 | Average delivery time |
| 29 | Cancelled delivery reasons |

### Category 8 — Aggregator and channel integrations (24 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Talabat integration (real DH middleware adapter when live) |
| 2 | Deliveroo integration (real Order API adapter when live) |
| 3 | Noon Food integration |
| 4 | Careem integration |
| 5 | Uber Eats integration |
| 6 | Zomato integration |
| 7 | **Keeta integration** (real Open API adapter + signed confirm/cancel/prepare when live) |
| 8 | Website ordering |
| 9 | Mobile app ordering |
| 10 | WhatsApp ordering |
| 11 | Instagram order link |
| 12 | Google Business Profile order link |
| 13 | QR table ordering (locked table query UX) |
| 15 | Self-order kiosk |
| 16 | Call center order entry |
| 17 | Centralized order inbox |
| 18 | Menu sync across platforms |
| 19 | Price sync across platforms |
| 20 | Stock sync across platforms |
| 21 | Pause orders per channel (manager PIN on pause) |
| 22 | Channel-wise commission report |
| 23 | Channel-wise profitability report |
| 24 | Aggregator reconciliation |

### Category 9 — Staff and permissions (22 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Staff login |
| 2 | PIN login |
| 3 | Role-based access |
| 4 | Manager approval |
| 5 | Void approval |
| 6 | Discount approval |
| 7 | Refund approval |
| 8 | Shift open/close |
| 9 | Clock in/out |
| 10 | Break tracking |
| 11 | Attendance |
| 12 | Staff scheduling |
| 13 | Overtime tracking |
| 14 | Tip pooling |
| 15 | Tip by staff |
| 16 | Sales by staff |
| 17 | Mistake tracking |
| 18 | Cash drawer assignment |
| 19 | Staff performance report |
| 20 | Training mode |
| 21 | Audit log |
| 22 | Suspicious activity alerts |

### Category 10 — Reporting and owner dashboard (34 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Daily sales report |
| 2 | Hourly sales report |
| 3 | Weekly sales report |
| 4 | Monthly sales report |
| 5 | Sales by item |
| 6 | Sales by category |
| 7 | Sales by channel |
| 8 | Sales by branch |
| 9 | Sales by waiter |
| 10 | Sales by payment method |
| 11 | Gross profit report |
| 12 | Food cost report |
| 13 | Discount report |
| 14 | Void report |
| 15 | Refund report |
| 16 | Wastage report |
| 17 | Top-selling items |
| 18 | Slow-moving items |
| 19 | Dead menu items |
| 20 | Average order value |
| 21 | Average table turnover time |
| 22 | Average prep time |
| 23 | Average delivery time |
| 24 | Customer repeat rate |
| 25 | Customer retention rate |
| 26 | New vs returning customers |
| 27 | Peak hour report |
| 28 | Branch comparison |
| 29 | Forecasted sales |
| 30 | Inventory valuation |
| 31 | Cash closing report |
| 32 | Tax report |
| 33 | Export to Excel |
| 34 | WhatsApp daily owner report |

### Category 11 — Multi-branch and franchise (19 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Central dashboard |
| 2 | Branch-wise dashboard |
| 3 | Centralized menu |
| 4 | Branch-specific pricing |
| 5 | Branch-specific stock |
| 6 | Branch-wise staff |
| 7 | Central kitchen support |
| 8 | Stock transfer between branches |
| 9 | Franchise royalty report |
| 10 | Branch performance comparison |
| 11 | Centralized customer database |
| 12 | Shared loyalty across branches |
| 13 | Centralized promotion control |
| 14 | Region-wise reports |
| 15 | Multi-currency support |
| 16 | Multi-language support |
| 17 | Role permissions by branch |
| 18 | Menu publishing approval |
| 19 | Bulk updates across locations |

### Category 12 — Offline, backup, and reliability (19 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Offline order taking |
| 2 | Offline payment handling |
| 3 | Offline KOT printing |
| 4 | Offline receipt printing |
| 5 | Local device cache |
| 6 | Auto-sync when internet returns |
| 7 | Conflict resolution |
| 8 | Cloud backup |
| 9 | Device failover |
| 10 | Printer failover |
| 11 | KDS fallback |
| 12 | Daily automatic backup |
| 13 | Data export |
| 14 | Uptime monitoring |
| 15 | Error logs |
| 16 | Admin activity logs |
| 17 | Disaster recovery |
| 18 | Multi-device sync |
| 19 | Network status dashboard |

### Category 13 — Compliance and UAE-specific (20 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | VAT invoice |
| 2 | Simplified tax invoice |
| 3 | TRN field |
| 4 | VAT breakdown |
| 5 | Tax-inclusive pricing |
| 6 | Tax-exclusive pricing |
| 7 | Credit note |
| 8 | Refund note |
| 9 | Z report |
| 10 | Audit trail |
| 11 | Invoice sequence control |
| 12 | User action logs |
| 13 | Data retention |
| 14 | Export for accountant |
| 15 | E-invoicing readiness |
| 16 | Structured invoice data |
| 17 | Accredited service provider integration readiness |
| 18 | Arabic invoice support |
| 19 | Bilingual receipt |
| 20 | Branch TRN support |

### Category 14 — AI features (25 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | AI WhatsApp order taking |
| 2 | AI menu recommendation |
| 3 | AI upsell |
| 4 | AI combo suggestion |
| 5 | AI reorder prompt |
| 6 | AI abandoned order recovery |
| 7 | AI customer segmentation |
| 8 | AI daily sales summary |
| 9 | AI low-stock prediction |
| 10 | AI slow-moving item warning |
| 11 | AI food-cost anomaly detection |
| 12 | AI staff performance summary |
| 13 | AI customer complaint detection |
| 14 | AI review reply suggestion |
| 15 | AI negative review escalation |
| 16 | AI delivery ETA explanation |
| 17 | AI “why sales dropped” report |
| 18 | AI best menu bundle suggestion |
| 19 | AI promotion generator |
| 20 | AI festival campaign generator |
| 21 | AI menu translation |
| 22 | AI voice ordering |
| 23 | AI call answering |
| 24 | AI reservation handling |
| 25 | AI demand forecasting |

### Category 15 — Frontend UI shell & ops surfaces (32 features)

Touch-first POS shell from UI/UX redesign (not a replacement for cats 1–14 — documents delivery of those capabilities in the manager/desktop UX).

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Touch design tokens (56/64 targets, 16–28 type scale) |
| 2 | AppShell top status bar (offline, alerts, clock) |
| 3 | Collapsible sidebar 88/240 + Daily/Manage/More nav |
| 4 | Alert center |
| 5 | TouchButton / primary action sizes |
| 6 | Bottom sticky action bar |
| 7 | Manager PIN modal + danger-action matrix |
| 8 | Money summary (large totals) |
| 9 | Empty / error states |
| 10 | Login email + staff PIN pad |
| 11 | Onboarding wizard shell |
| 12 | Live Ops rush card board |
| 13 | Floor Plan / table map |
| 14 | Orders list card-first |
| 15 | Order Detail full page |
| 16 | New Order POS 3-pane |
| 17 | Checkout / Payment tender UI |
| 18 | Kitchen KDS touch redesign |
| 19 | Expo / ready pickup view |
| 20 | Rider Dispatch map + queue |
| 21 | WhatsApp inbox 3-pane |
| 22 | Public storefront mobile |
| 23 | QR table lock UX |
| 24 | Customer tracking page |
| 25 | Rider mobile **web** app |
| 26 | Manager screens touch polish |
| 27 | Role / license nav soft-gates |
| 28 | Offline limits banners on core screens |
| 29 | Accessibility baseline |
| 30 | Rush-hour load fixtures (100 orders / 20 riders / …) |
| 31 | Mac desktop package with redesign UI |
| 32 | (Partial residuals: in-shell staff switch, branch selector, settings PIN, list virtualization) |

---

## J. Counts

| Bucket | Count |
|--------|------:|
| Cat 1. Order management | 32 |
| Cat 2. Kitchen and preparation | 30 |
| Cat 3. Menu and item control | 35 |
| Cat 4. Inventory and food-cost | 29 |
| Cat 5. Payment and billing | 34 |
| Cat 6. Customer, CRM, and loyalty | 31 |
| Cat 7. Delivery management | 29 |
| Cat 8. Aggregator and channel integrations | **24** (incl. Keeta + renumbered channels) |
| Cat 9. Staff and permissions | 22 |
| Cat 10. Reporting and owner dashboard | 34 |
| Cat 11. Multi-branch and franchise | 19 |
| Cat 12. Offline, backup, and reliability | 19 |
| Cat 13. Compliance and UAE-specific | 20 |
| Cat 14. AI features | 25 |
| Cat 15. Frontend UI shell & ops surfaces | **32** |
| **Named matrix features (cats 1–14 rows in this file)** | **~383** |
| **Status doc catalog claim (1–14)** | **385** |
| **Status doc + UI shell (1–15)** | **417** (413 implemented / 4 partial) |

Small differences between tables are rollup arithmetic / dual-listed names (e.g. Credit note). Treat **this catalog + status doc** as the product inventory.

**Marketplace adapter summary (2026-07-13):**

| Brand | Product path | Live adapter |
|-------|--------------|--------------|
| Talabat | Channels + webhooks + accept/reject | **Real** Delivery Hero middleware |
| Deliveroo | Channels + Order Events + PATCH status | **Real** Deliveroo Order API |
| Keeta | Channels + event 1001 webhooks + confirm | **Real** Keeta Open API (signed) |
| Careem / Noon / Uber / Zomato | Channels + mock or generic live | Generic / mock until brand docs mapped |

---

## K. Related docs

| Doc | Contents |
|-----|----------|
| `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md` | Audit evidence per feature (incl. Cat 15 UI shell + real adapters) |
| `docs/ROLE_SCREEN_FEATURE_PLACEMENT.md` | **Waiter / Cashier / Kitchen / Owner** — which features go on which screens |
| `docs/superpowers/plans/2026-07-13-role-based-screens-implementation.md` | **Phased build plan** R0–R6 for role-based screens |
| `docs/superpowers/plans/2026-07-09-pos-frontend-uiux-redesign-phases.md` | UI/UX redesign phase plan (36 screens) |
| `docs/superpowers/plans/2026-07-09-phase-0-uiux-foundation.md` | Phase 0 foundation plan |
| `docs/PLATFORM_FEATURES_REFERENCE.md` | Engineering-oriented platform reference |
| `docs/API_REFERENCE.md` | HTTP API detail |
| `docs/architecture.md` | System diagram |
| `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` | Business rules SSOT |
| `src/app/aggregators/providers/` | Talabat / Deliveroo / Keeta / Uber Eats + Careem·Noon middleware adapters |

*End of catalog.*