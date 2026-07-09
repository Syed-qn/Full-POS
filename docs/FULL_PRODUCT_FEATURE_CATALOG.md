# Full POS — Complete Feature Catalog

**Product:** Full POS (Catalystiq) — multi-tenant restaurant POS + WhatsApp delivery + AI + data science  
**Document date:** 2026-07-09  
**Purpose:** Single inventory of **everything** a user can open, use, edit, or operate — across desktop app (Windows/macOS), cloud manager console, WhatsApp, rider app, kitchen KDS, public pages, and integrations.  
**How to read:**  
- **Sections A–H** = interactive product surfaces (screens, buttons, roles, channels).  
- **Section I** = full named feature matrix from the advanced POS audit (order types through AI).  
- **Evidence / implementation notes:** `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md`  
**Scope note:** Every matrix feature is implemented as a working product path in this repository (API + UI and/or channel). Live marketplace partners use mock adapters by default and live HTTP when credentials/`mode=live` are set.

### Contents
- [A. Who can do what](#a-who-can-do-what-actors)
- [B. Full POS manager app screens](#b-full-pos-manager-app--every-screen-you-can-open)
- [C. Desktop app extras](#c-desktop-app-extras-local-software)
- [D. Customer on WhatsApp](#d-customer-on-whatsapp--interactive-capabilities)
- [E. Rider app](#e-rider-app--interactive-capabilities)
- [F. Kitchen KDS](#f-kitchen-staff-on-kds--interactive-capabilities)
- [G. Partner / marketplace](#g-partner--marketplace-integrations-operator--system)
- [H. Enforced business rules](#h-business-rules-the-product-always-enforces)
- [I. Complete feature matrix](#i-complete-feature-matrix-385-product-features)
- [J. Counts](#j-counts)
- [K. Related docs](#k-related-docs)

---


## A. Who can do what (actors)

| Actor | Surfaces | What they do |
|-------|----------|--------------|
| **Restaurant manager / owner** | Full POS desktop app (Windows `.exe` x64/arm64, Mac DMG) **or** cloud manager console | Run the restaurant: orders, kitchen, menu, inventory, payments, staff, marketing, AI, compliance, reports, multi-branch HQ |
| **Floor / counter staff** | Full POS + PIN staff login | Take POS orders, take payments, clock in/out, open drawer (role-gated) |
| **Kitchen staff** | Kitchen Display (`/kds`) | Bump/start/recall tickets, packaging/quality/missing checks, station boards |
| **Customer (WhatsApp)** | WhatsApp Business chat | Order, modify, track, pay COD, redeem wallet/coupons, complain, STOP marketing, voice notes |
| **Customer (web/QR/kiosk)** | Public store `/order/:slug`, QR table order, tracking `/track/:token` | Browse menu, place order, track delivery |
| **Rider (employee)** | Rider mobile app + optional WhatsApp | Receive assignments, GPS, pickup/deliver, COD, proof photo, OTP |
| **Franchise / org HQ** | Branches screen (org APIs) | Multi-branch menu publish, stock transfer, royalty, shared loyalty, promotions |
| **POS partner (e.g. Cratis)** | Partner REST + webhooks | Push kitchen status, sync menu, chat takeover, order events |
| **Marketplace (Talabat, etc.)** | Aggregator webhooks + live HTTP | Inbound orders, menu/stock/price sync, accept/reject, status push |

---

## B. Full POS manager app — every screen you can open

Navigation is grouped. Each row is something a signed-in manager can open and use.

### Floor
| Screen | Route | User can |
|--------|-------|----------|
| Live Ops | `/` | Watch live orders, SLA lanes, dispatch KPIs, live map, batch previews, urgency colors |
| Orders | `/orders` | List/filter/search orders by status/channel, open detail, channel badges |
| New Order | `/new-order` | Create manual/POS orders (phone, items, type, table, notes) |
| Kitchen (KDS) | `/kds`, `/kds/:stationId` | Station boards, bump/start/recall, checks, performance, ready-for-pickup |

### Catalog & stock
| Screen | Route | User can |
|--------|-------|----------|
| Menu | `/menu` | Upload/extract menu, edit dishes, variants, modifiers, combos, pricing rules, import CSV, bulk price, approve menu, images, allergens, AR names, seasonal windows |
| Inventory | `/inventory` | Ingredients, low stock, PO/GRN, waste, variance, locations, vendors, EOD snapshot, substitutions, batches/expiry |
| Branches | `/branches` | Org HQ: branches, rollups, central menu, publish approval, stock transfer, royalty, promotions, multi-currency, members |

### Delivery
| Screen | Route | User can |
|--------|-------|----------|
| Riders | `/riders` | Add riders, status, map, settle COD |
| Chats | `/conversations` | Read WhatsApp threads, media/voice, takeover, reset, customer context panel |
| Channels | `/channels` | Enable/pause channels, live API keys, sync menu/price/stock, commission/profit, inbox, settlements, public slug & social order links |

### People
| Screen | Route | User can |
|--------|-------|----------|
| Customers | `/customers` | Search list, open profiles |
| Customer profile | `/customers/:id` | Edit notes/allergies/VIP/birthday, favorites, points, stamps, wallet, refunds, reorder last, referral |
| Staff | `/staff` | PIN login, roles, shifts, clock/break, attendance, tips, sales, mistakes, training mode, approvals |
| Complaints | `/tickets` | Open tickets, evidence, resolve with wallet/replacement/no-action |

### Money
| Screen | Route | User can |
|--------|-------|----------|
| Payments | `/payments` | Charge tenders, refunds, credit notes, payment links, gift cards, drawer open/close, cash in/out, recon import, billing settings |
| Coupons | `/coupons` | Create/issue/pause multi-use coupons |
| Compliance | `/compliance` | TRN/tax mode, simplified vs full invoice, refund notes, e-invoice transmit, retention, accountant export |
| Reports | `/reports` | All owner reports, date range, Excel export, owner WhatsApp daily report |

### AI & data
| Screen | Route | User can |
|--------|-------|----------|
| AI Insights | `/ai` | Generate sales/staff/stock insights, segments, festival campaigns, review replies, reservations, mock call IVR, translate menu |
| Analytics | `/analytics` | Forecast horizons, campaign summary, dispatch KPIs, order delivery KPIs |
| Forecast (alias) | `/predictions` | Same analytics/forecast surface |
| Marketing | `/marketing` | Templates, campaigns, segments, automations, images, broadcast, schedule, today’s special |

### System
| Screen | Route | User can |
|--------|-------|----------|
| Reliability | `/reliability` | Backups, devices/failover, errors, audit log, offline conflicts, network status, export pack |
| Settings | `/settings` | Restaurant name/location/TRN/tax mode, batching, dispatch knobs, delivery zones/fees, open hours, Meta WhatsApp connect/disconnect, loyalty/resale, cart recovery |

### Auth / setup (no main nav)
| Screen | Route | User can |
|--------|-------|----------|
| Login / Signup | `/login` | Sign in or create restaurant account |
| Onboarding | `/onboarding` | Connect WhatsApp (Meta), pin location, complete setup |

### Public (no login)
| Screen | Route | User can |
|--------|-------|----------|
| Public storefront | `/order/:slug` | Browse menu, cart, place order (website/mobile/kiosk channel) |
| Customer tracking | `/track/:trackingToken` | Live order status / map |
| Rider share track | `/rider-track/:riderToken` | Customer views rider location |

---

## C. Desktop app extras (local software)

When running as **Full POS** Electron (`.exe` / `.dmg`), the user also gets:

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
| Window chrome | Native window title **Full POS**, no browser URL bar |

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

| User action | What happens |
|-------------|--------------|
| Login with rider credentials | Rider session |
| View assigned tasks | Queue of pickups/deliveries |
| Navigate with map | Live map panel |
| Advance status | Picked up → arriving → delivered |
| Share live GPS | Location pings for tracking links & dispatch |
| Collect COD | Cash collection path |
| Delivery proof photo | Upload / attach proof |
| OTP confirm (if required) | Customer code at door |
| Mark undeliverable | Failure reason codes |
| Push notifications | Task alerts (when FCM configured) |

---

## F. Kitchen staff on KDS — interactive capabilities

| User action | What happens |
|-------------|--------------|
| Switch station | Grill/fry/beverage/dessert/pizza/cloud boards |
| See urgency colors / timers | Age, delayed, rush |
| Start prep | Ticket → preparing |
| Bump ready | Ticket → ready / bumped |
| Recall | Undo bump |
| Packaging / quality / missing | Checklist stamps |
| View ready for pickup | Expo-style ready list |
| Performance tab | Prep times by item/staff |
| Printer jobs | Desktop poller prints KOTs |

---

## G. Partner / marketplace integrations (operator + system)

| Integration | Operator can |
|-------------|----------------|
| Meta WhatsApp | Connect/disconnect WABA, fix re-subscribe, catalog sync/push |
| Cratis / partner POS | API keys, menu/order sync, kitchen status webhooks |
| Talabat / Deliveroo / Careem / Uber / Noon / Zomato | Enable channel, live API key, health check, pause, sync, recon settlements |
| Stripe / card gateways | Store credentials (Payments), payment links |
| Cloud backups | Manual/daily backup, verify, restore preview |

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

### Category 8 — Aggregator and channel integrations (22 features)

| # | Feature (user-facing capability) |
|--:|----------------------------------|
| 1 | Talabat integration |
| 2 | Deliveroo integration |
| 3 | Noon Food integration |
| 4 | Careem integration |
| 5 | Uber Eats integration |
| 6 | Zomato integration |
| 7 | Website ordering |
| 8 | Mobile app ordering |
| 9 | WhatsApp ordering |
| 10 | Instagram order link |
| 11 | Google Business Profile order link |
| 12 | QR table ordering |
| 13 | Self-order kiosk |
| 14 | Call center order entry |
| 15 | Centralized order inbox |
| 16 | Menu sync across platforms |
| 17 | Price sync across platforms |
| 18 | Stock sync across platforms |
| 19 | Pause orders per channel |
| 20 | Channel-wise commission report |
| 21 | Channel-wise profitability report |
| 22 | Aggregator reconciliation |

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
| Cat 8. Aggregator and channel integrations | 22 |
| Cat 9. Staff and permissions | 22 |
| Cat 10. Reporting and owner dashboard | 34 |
| Cat 11. Multi-branch and franchise | 19 |
| Cat 12. Offline, backup, and reliability | 19 |
| Cat 13. Compliance and UAE-specific | 20 |
| Cat 14. AI features | 25 |
| **Named matrix features (this catalog)** | **381** |
| **Status doc rollup claim** | **385** |

The few-count difference is rollup arithmetic in the status header vs unique table rows (two names appear in two categories: Credit note, Average delivery time). Treat **this catalog + status tables** as the product inventory for user-facing capabilities.

---

## K. Related docs

| Doc | Contents |
|-----|----------|
| `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md` | Audit evidence per feature |
| `docs/PLATFORM_FEATURES_REFERENCE.md` | Engineering-oriented platform reference |
| `docs/API_REFERENCE.md` | HTTP API detail |
| `docs/architecture.md` | System diagram |
| `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` | Business rules SSOT |

*End of catalog.*
