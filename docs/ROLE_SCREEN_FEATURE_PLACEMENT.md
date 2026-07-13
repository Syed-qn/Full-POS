# Role → Screen Feature Placement

**Product:** Full POS (Catalystiq)  
**Document date:** 2026-07-13  
**Purpose:** Map every feature from `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md` onto **role-specific screens** so Waiter, Cashier, Kitchen, and Owner each get a focused product surface — not 381 separate pages.  
**Status:** Placement SSOT for future role UI builds. **Does not change code by itself.**  
**Sources:** Status matrix (cats 1–15), UI/UX redesign plan, current `frontend/src/lib/navAccess.ts`.

## Access level key

| Code | Meaning |
|------|---------|
| **P** | **Primary** — main place this role uses the feature |
| **S** | **Secondary** — available, not the home workflow |
| **S-PIN** | Secondary, requires **manager PIN** / escalate |
| **H** | **Hidden** — not on this role’s nav or home |

**Manager** = same access as **Owner** for placement (full). Documented under Owner.

---

## 1. Role home screens (product IA)

| Role | Proposed home | Primary surfaces | Forbidden by default |
|------|---------------|------------------|----------------------|
| **Waiter** | `/floor` (or `/waiter`) | Floor Plan, table order, modify qty/notes, send to kitchen | Payments admin, void/refund, menu edit, inventory, reports, channels, AI |
| **Cashier** | `/new-order` (or `/cashier`) | New Order, Orders, Checkout/Bill, drawer, customer lookup | Menu/inventory/staff admin, kitchen stations, franchise HQ |
| **Kitchen** | `/kds` fullscreen | Station tickets, bump/start/recall, Expo ready, packaging/QC | Create order, take payment, admin modules |
| **Owner** | `/` Live Ops | Full Daily + Manage + More | — (PIN still on danger actions) |

### Recommended role → existing routes (today vs proposed)

| Role | Today (`navAccess`) | Proposed role string | Landing |
|------|---------------------|----------------------|---------|
| Waiter | maps roughly to `staff` | add **`waiter`** | `/floor` |
| Cashier | `cashier` | `cashier` | `/new-order` |
| Kitchen | `kitchen` | `kitchen` | `/kds` (no sidebar) |
| Owner | email/`manager`/`owner` | `owner` / `manager` | `/` |

---

## 2. Per-role screen inventory

### 2.1 Waiter screens

| Screen | Route | Purpose | Allowed | Forbidden |
|--------|-------|---------|---------|-----------|
| Waiter Floor | `/floor` | Table map, open table order | New table order, transfer/merge (confirm), status colors | Pay, void, refund |
| Waiter Order | `/new-order` (dine-in/tableside) | Take order | Qty +/−, item notes, kitchen notes, modifiers, courses, allergy strip, hold, send kitchen | Tender grid, manager void |
| Waiter Order Detail | `/orders/:id` | Modify before ready | Edit items/qty/notes, fire course, rush (optional), print KOT | Refund; void needs PIN escalate |
| Open orders (light) | `/orders` | Find table/order | Filter open/held | Channel admin, bulk finance |
| Shell | AppShell minimal | Offline badge, clock | Switch PIN (future) | Admin nav groups |

**Waiter must-have interactions:** change **quantity**, add **instructions** (item notes + kitchen notes), apply **modifiers**, attach **table**, **send to kitchen**, **modify until ready**.

### 2.2 Cashier screens

| Screen | Route | Purpose | Allowed | Forbidden |
|--------|-------|---------|---------|-----------|
| Cashier Terminal | `/new-order` | Create any order type | Full cart, delivery address fields, reorders | Menu price admin |
| Bill / Checkout | `/orders/:id/pay` | See bill & take payment | All tenders, split, tips, staff discount, loyalty/gift redeem | Manager discount / refund without PIN |
| Orders | `/orders` | Find bill by phone/number | Open, held, pay, print | Aggregator credentials |
| Order Detail | `/orders/:id` | Modify + jump to Pay | Edit, hold, pay CTA | Deep admin |
| Payments / Drawer | `/payments` | Drawer, cash in/out, links | Drawer ops, staff discount | Full recon/EOD optional → owner |
| Customers | `/customers` | Lookup for reorder/loyalty | Search, reorder last, apply points | Marketing campaigns |

**Cashier must-have interactions:** **see bill**, **create order**, **modify**, **take payment**, drawer, discounts (role/PIN), open/held orders.

### 2.3 Kitchen screens

| Screen | Route | Purpose | Allowed | Forbidden |
|--------|-------|---------|---------|-----------|
| Kitchen KDS | `/kds`, `/kds/:stationId` | See & cook tickets | Start, bump, recall, timers, allergens, modifiers display | Create order, pay |
| Expo | `/kds?view=expo` | Ready for pickup/delivery | Packaging, missing, QC, handoff ready | Dispatch assign rider (owner) |
| Shell | Fullscreen | No admin sidebar | Offline/printer badge | Manage nav |

**Kitchen must-have interactions:** **see orders**, **start prep**, **mark ready**, recall, packaging/QC/missing, allergen warnings.

### 2.4 Owner screens

| Group | Screens | Purpose |
|-------|---------|---------|
| Daily ops | Live Ops, Floor, Orders, New Order, Checkout, KDS, Payments, Riders, Chats | Full operational control |
| Manage | Menu, Inventory, Customers, Staff, Marketing, Reports, AI, Branches, Channels, Reliability, Settings | Admin |
| More | Tickets, Coupons, Compliance, Analytics, Forecast | Support & finance |
| Danger | Void, refund, stock adjust, channel pause, manager discount | Always Confirm + **PIN** where configured |

---

## 3. Category placement matrices

Columns: **W** Waiter · **C** Cashier · **K** Kitchen · **O** Owner · **Primary screen**

### Category 1 — Order management (32 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Dine-in orders | P | S | H | P | Floor Plan / Waiter Order | table-first |
| Takeaway orders | S | P | H | P | Cashier Terminal / New Order |  |
| Delivery orders | S | P | H | P | Cashier Terminal / New Order |  |
| Online orders | S | P | H | P | Cashier Terminal / New Order |  |
| QR code orders | S | P | H | P | Cashier Terminal / New Order |  |
| Tableside orders | P | S | H | P | Floor Plan / Waiter Order | table-first |
| Drive-thru orders | S | P | H | P | Cashier Terminal / New Order |  |
| Aggregator orders | S | P | H | P | Cashier Terminal / New Order |  |
| Open orders | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Held orders | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Scheduled orders | S | P | H | P | Cashier Terminal / New Order |  |
| Pre-orders | S | P | H | P | Cashier Terminal / New Order |  |
| Reorders | S | P | H | P | Cashier Terminal / New Order |  |
| Refund orders | H | S-PIN | H | P | Order Detail / Checkout | PIN or owner |
| Cancelled orders | H | S-PIN | H | P | Order Detail / Checkout | PIN or owner |
| Partial cancellation | H | S-PIN | H | P | Order Detail / Checkout | PIN or owner |
| Void order with manager approval | H | S-PIN | H | P | Order Detail / Checkout | PIN or owner |
| Edit order after sending to kitchen | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Add item notes | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Add kitchen notes | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Customer allergy notes | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Course-wise ordering | P | S | H | P | Floor Plan / Waiter Order | table-first |
| Fire course later | P | S | H | P | Floor Plan / Waiter Order | table-first |
| Rush order button | P | S | H | P | Floor Plan / Waiter Order | table-first |
| Priority order button | P | S | H | P | Floor Plan / Waiter Order | table-first |
| Duplicate order | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Repeat last order | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Split order by item | S | P | H | P | Cashier Terminal / New Order |  |
| Split order by seat | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Merge orders | P | P | H | P | Floor / New Order / Order Detail | qty + notes on cart |
| Transfer order between tables | P | S | H | P | Floor Plan / Waiter Order | table-first |
| Transfer order between staff | P | S | H | P | Floor Plan / Waiter Order | table-first |

### Category 2 — Kitchen and preparation (30 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Kitchen Display System | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Kitchen Order Ticket | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Station-wise routing | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Grill station | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Fry station | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Beverage station | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Dessert station | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Pizza station | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Cloud kitchen station | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Prep time tracking | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Estimated ready time | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Auto-prioritize old orders | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Color-coded order urgency | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Order bump screen | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Recall completed ticket | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Delayed ticket warning | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| KDS item timer | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Kitchen performance report | H | H | S | P | KDS Performance / Reports | kitchen uses KDS; owner reports |
| Average prep time by item | H | H | S | P | KDS Performance / Reports | kitchen uses KDS; owner reports |
| Average prep time by staff | H | H | S | P | KDS Performance / Reports | kitchen uses KDS; owner reports |
| Late order alerts | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Multi-kitchen routing | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Printer fallback if KDS fails | H | H | S | P | Reliability / KDS settings |  |
| Kitchen printer routing by item category | H | H | S | P | Reliability / KDS settings |  |
| Allergen warning on kitchen ticket | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Modifier display on ticket | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Packaging checklist | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Missing item confirmation | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Quality check status | H | H | P | S | Kitchen KDS | fullscreen kitchen home |
| Ready for pickup status | S | S | P | P | Expo / KDS | cashier counter pickup; kitchen expo |

### Category 3 — Menu and item control (35 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Menu categories | H | H | H | P | Menu Management | owner admin only |
| Subcategories | H | H | H | P | Menu Management | owner admin only |
| Item variants | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Item sizes | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Add-ons | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Modifiers | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Forced modifiers | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Optional modifiers | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Combo meals | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Meal bundles | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Upsell rules | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Cross-sell rules | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Happy hour pricing | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Time-based pricing | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Channel-based pricing | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Branch-based pricing | H | H | H | P | Menu Management | owner admin only |
| Delivery-only menu | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Dine-in-only menu | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| QR-only menu | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Cloud kitchen brand menus | H | H | H | P | Menu Management | owner admin only |
| Menu item availability | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Auto-hide out-of-stock item | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Item countdown | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Recipe linking | H | H | H | P | Menu Management | owner admin only |
| Ingredient linking | H | H | H | P | Menu Management | owner admin only |
| Allergen tags | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Nutrition data | H | H | H | P | Menu Management | owner admin only |
| Item images | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Multilingual menu | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Arabic menu | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| English menu | S | S | S | P | Order cart / KDS ticket / Menu admin | staff consume; owner edits |
| Menu approval workflow | H | H | H | P | Menu Management | owner admin only |
| Bulk menu import | H | H | H | P | Menu Management | owner admin only |
| Bulk price update | H | H | H | P | Menu Management | owner admin only |
| Seasonal menu scheduling | H | H | H | P | Menu Management | owner admin only |

### Category 4 — Inventory and food-cost (29 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Ingredient-level inventory | H | H | H | P | Inventory / Purchasing | owner/manager |
| Recipe-level costing | H | H | H | P | Inventory / Purchasing | owner/manager |
| Stock deduction by recipe | H | H | H | P | System on confirm | auto on order confirm |
| Wastage tracking | H | H | H | P | Inventory / Purchasing | owner/manager |
| Spoilage tracking | H | H | H | P | Inventory / Purchasing | owner/manager |
| Stock transfer | H | H | H | P | Inventory / Purchasing | owner/manager |
| Multi-location stock | H | H | H | P | Inventory / Purchasing | owner/manager |
| Stock count | H | H | H | P | Inventory / Purchasing | owner/manager |
| Stock variance report | H | H | H | P | Inventory / Purchasing | owner/manager |
| Par level | H | H | H | P | Inventory / Purchasing | owner/manager |
| Reorder point | H | H | H | P | Inventory / Purchasing | owner/manager |
| Supplier management | H | H | H | P | Inventory / Purchasing | owner/manager |
| Purchase orders | H | H | H | P | Inventory / Purchasing | owner/manager |
| Goods received note | H | H | H | P | Inventory / Purchasing | owner/manager |
| Cost price tracking | H | H | H | P | Inventory / Purchasing | owner/manager |
| Vendor price comparison | H | H | H | P | Inventory / Purchasing | owner/manager |
| Food cost percentage | H | H | H | P | Inventory / Purchasing | owner/manager |
| Gross margin by item | H | H | H | P | Inventory / Purchasing | owner/manager |
| Over-portioning alerts | H | H | H | P | Inventory / Purchasing | owner/manager |
| Theft/loss alerts | H | H | H | P | Inventory / Purchasing | owner/manager |
| Expiry date tracking | H | H | H | P | Inventory / Purchasing | owner/manager |
| Batch tracking | H | H | H | P | Inventory / Purchasing | owner/manager |
| Central kitchen inventory | H | H | H | P | Inventory / Purchasing | owner/manager |
| Commissary kitchen support | H | H | H | P | Inventory / Purchasing | owner/manager |
| Ingredient substitution | H | H | H | P | Inventory / Purchasing | owner/manager |
| Low-stock WhatsApp alert | H | S | H | P | Alert center / Inventory | cashier may see alert chip |
| Daily stock closing report | H | H | H | P | Inventory / Purchasing | owner/manager |
| Stock adjustment approval | H | H | H | P | Inventory / Purchasing | owner/manager |
| Recipe yield tracking | H | H | H | P | Inventory / Purchasing | owner/manager |

### Category 5 — Payment and billing (34 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Cash | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Card | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Tap to pay | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Apple Pay | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Google Pay | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Online payment | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Payment link | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Split payment | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Partial payment | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Pay later | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| House account | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Room charge for hotels | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Tips | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Service charge | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Delivery charge | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Packaging charge | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Minimum order charge | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Discount codes | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Staff discount | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Manager discount | H | S-PIN | H | P | Checkout / Payments | manager PIN |
| Loyalty redemption | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Gift card redemption | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Refunds | H | S-PIN | H | P | Checkout / Payments | manager PIN |
| Partial refunds | H | S-PIN | H | P | Checkout / Payments | manager PIN |
| Credit note | H | S-PIN | H | P | Checkout / Payments | manager PIN |
| Deposit payment | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Advance payment | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| End-of-day cash closing | H | S | H | P | Payments BO / Reports | EOD owner or senior cashier |
| Cash drawer management | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Cash in/out | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Over/short cash report | H | S | H | P | Payments BO / Reports | EOD owner or senior cashier |
| Payment reconciliation | H | S | H | P | Payments BO / Reports | EOD owner or senior cashier |
| Failed payment handling | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |
| Duplicate payment detection | S | P | H | P | Checkout / Cashier Terminal | waiter: view bill / send to pay |

### Category 6 — Customer, CRM, and loyalty (31 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Customer profile | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Phone number history | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| WhatsApp opt-in | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Order history | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Favorite items | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Last order shortcut | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Customer notes | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Allergy notes | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Birthday | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Anniversary | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| VIP tag | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Complaint history | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Refund history | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Loyalty points | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Cashback | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Stamp card | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Gift cards | S | S | H | P | Order / Checkout / Customer Profile | inline on order; full admin owner |
| Referral rewards | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Coupon campaigns | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Win-back campaigns | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Birthday offers | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Inactive customer campaigns | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Customer segmentation | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| High-value customer list | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Average order value by customer | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Customer lifetime value | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Feedback collection | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Review request automation | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| NPS survey | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Negative review escalation | H | H | H | P | Customers / Marketing | campaigns & CRM admin |
| Personalized offers | H | H | H | P | Customers / Marketing | campaigns & CRM admin |

### Category 7 — Delivery management (29 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Delivery order dashboard | H | H | H | P | Riders / Live Ops |  |
| Manual driver assignment | H | H | H | P | Riders / Live Ops |  |
| Auto driver assignment | H | H | H | P | Riders / Live Ops |  |
| Driver app | H | H | H | S | Rider App | rider role separate |
| Driver live location | H | H | H | P | Riders / Live Ops |  |
| Rider status | H | H | H | P | Riders / Live Ops |  |
| Pickup status | H | S | P | P | Expo / Rider |  |
| Out-for-delivery status | H | S | S | P | Live Ops / Tracking |  |
| Delivered status | H | S | S | P | Live Ops / Tracking |  |
| Failed delivery status | H | S | S | P | Live Ops / Tracking |  |
| Customer location pin | H | P | H | P | New Order (delivery) |  |
| Address notes | H | P | H | P | New Order (delivery) |  |
| Building/floor/apartment fields | H | P | H | P | New Order (delivery) |  |
| Delivery zone pricing | H | S | S | P | Live Ops / Tracking |  |
| Delivery distance calculation | H | S | S | P | Live Ops / Tracking |  |
| ETA calculation | H | S | S | P | Live Ops / Tracking |  |
| Delivery route optimization | H | S | S | P | Live Ops / Tracking |  |
| Priority delivery | H | H | H | P | Riders / Live Ops |  |
| Multi-order batching | H | H | H | P | Riders / Live Ops |  |
| Driver cash collection | H | S | S | P | Live Ops / Tracking |  |
| Driver settlement | H | H | H | P | Riders / Live Ops |  |
| Delivery proof photo | H | S | S | P | Live Ops / Tracking |  |
| OTP delivery confirmation | H | S | S | P | Live Ops / Tracking |  |
| Customer tracking link | H | S | S | P | Live Ops / Tracking |  |
| WhatsApp delivery updates | H | S | S | P | Live Ops / Tracking |  |
| Late delivery alert | H | H | H | P | Riders / Live Ops |  |
| Driver performance report | H | S | S | P | Live Ops / Tracking |  |
| Average delivery time | H | S | S | P | Live Ops / Tracking |  |
| Cancelled delivery reasons | H | P | H | P | New Order (delivery) |  |

### Category 8 — Aggregator and channel integrations (22 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Talabat integration | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Deliveroo integration | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Noon Food integration | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Careem integration | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Uber Eats integration | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Zomato integration | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Website ordering | H | S | H | P | Public / Channels | cashier sees inbound channel badge |
| Mobile app ordering | H | S | H | P | Public / Channels | cashier sees inbound channel badge |
| WhatsApp ordering | H | S | H | P | Public / Channels | cashier sees inbound channel badge |
| Instagram order link | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Google Business Profile order link | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| QR table ordering | H | S | H | P | Public / Channels | cashier sees inbound channel badge |
| Self-order kiosk | H | S | H | P | Public / Channels | cashier sees inbound channel badge |
| Call center order entry | H | P | H | P | New Order |  |
| Centralized order inbox | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Menu sync across platforms | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Price sync across platforms | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Stock sync across platforms | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Pause orders per channel | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Channel-wise commission report | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Channel-wise profitability report | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |
| Aggregator reconciliation | H | S | H | P | Channels / Orders inbox | cashier: channel badge; owner: config |

### Category 9 — Staff and permissions (22 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Staff login | P | P | P | P | Login | all roles |
| PIN login | P | P | P | P | Login | all roles |
| Role-based access | P | P | P | P | Login | all roles |
| Manager approval | H | S-PIN | H | P | PIN modal |  |
| Void approval | H | S-PIN | H | P | PIN modal |  |
| Discount approval | H | S-PIN | H | P | PIN modal |  |
| Refund approval | H | S-PIN | H | P | PIN modal |  |
| Shift open/close | H | H | H | P | Staff admin |  |
| Clock in/out | S | S | S | P | Staff / self-service | optional self clock |
| Break tracking | S | S | S | P | Staff / self-service | optional self clock |
| Attendance | H | H | H | P | Staff admin |  |
| Staff scheduling | H | H | H | P | Staff admin |  |
| Overtime tracking | H | H | H | P | Staff admin |  |
| Tip pooling | H | H | H | P | Staff admin |  |
| Tip by staff | H | H | H | P | Staff admin |  |
| Sales by staff | H | H | H | P | Staff admin |  |
| Mistake tracking | H | H | H | P | Staff admin |  |
| Cash drawer assignment | H | P | H | P | Payments / Drawer |  |
| Staff performance report | H | H | H | P | Staff admin |  |
| Training mode | S | S | S | P | Shell chrome |  |
| Audit log | H | H | H | P | Staff admin |  |
| Suspicious activity alerts | H | H | H | P | Staff admin |  |

### Category 10 — Reporting and owner dashboard (34 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Daily sales report | H | H | H | P | Reports / Analytics | owner dashboard |
| Hourly sales report | H | H | H | P | Reports / Analytics | owner dashboard |
| Weekly sales report | H | H | H | P | Reports / Analytics | owner dashboard |
| Monthly sales report | H | H | H | P | Reports / Analytics | owner dashboard |
| Sales by item | H | H | H | P | Reports / Analytics | owner dashboard |
| Sales by category | H | H | H | P | Reports / Analytics | owner dashboard |
| Sales by channel | H | H | H | P | Reports / Analytics | owner dashboard |
| Sales by branch | H | H | H | P | Reports / Analytics | owner dashboard |
| Sales by waiter | H | H | H | P | Reports / Analytics | owner dashboard |
| Sales by payment method | H | H | H | P | Reports / Analytics | owner dashboard |
| Gross profit report | H | H | H | P | Reports / Analytics | owner dashboard |
| Food cost report | H | H | H | P | Reports / Analytics | owner dashboard |
| Discount report | H | H | H | P | Reports / Analytics | owner dashboard |
| Void report | H | H | H | P | Reports / Analytics | owner dashboard |
| Refund report | H | H | H | P | Reports / Analytics | owner dashboard |
| Wastage report | H | H | H | P | Reports / Analytics | owner dashboard |
| Top-selling items | H | H | H | P | Reports / Analytics | owner dashboard |
| Slow-moving items | H | H | H | P | Reports / Analytics | owner dashboard |
| Dead menu items | H | H | H | P | Reports / Analytics | owner dashboard |
| Average order value | H | H | H | P | Reports / Analytics | owner dashboard |
| Average table turnover time | H | H | H | P | Reports / Analytics | owner dashboard |
| Average prep time | H | H | S | P | KDS Performance / Reports |  |
| Average delivery time | H | H | H | P | Reports / Analytics | owner dashboard |
| Customer repeat rate | H | H | H | P | Reports / Analytics | owner dashboard |
| Customer retention rate | H | H | H | P | Reports / Analytics | owner dashboard |
| New vs returning customers | H | H | H | P | Reports / Analytics | owner dashboard |
| Peak hour report | H | H | H | P | Reports / Analytics | owner dashboard |
| Branch comparison | H | H | H | P | Reports / Analytics | owner dashboard |
| Forecasted sales | H | H | H | P | Reports / Analytics | owner dashboard |
| Inventory valuation | H | H | H | P | Reports / Analytics | owner dashboard |
| Cash closing report | H | S | H | P | Payments / Reports |  |
| Tax report | H | H | H | P | Reports / Analytics | owner dashboard |
| Export to Excel | H | H | H | P | Reports / Analytics | owner dashboard |
| WhatsApp daily owner report | H | H | H | P | Reports / Analytics | owner dashboard |

### Category 11 — Multi-branch and franchise (19 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Central dashboard | H | H | H | P | Branches HQ |  |
| Branch-wise dashboard | H | H | H | P | Branches HQ |  |
| Centralized menu | H | H | H | P | Branches HQ |  |
| Branch-specific pricing | H | H | H | P | Branches HQ |  |
| Branch-specific stock | H | H | H | P | Branches HQ |  |
| Branch-wise staff | H | H | H | P | Branches HQ |  |
| Central kitchen support | H | H | H | P | Branches HQ |  |
| Stock transfer between branches | H | H | H | P | Branches HQ |  |
| Franchise royalty report | H | H | H | P | Branches HQ |  |
| Branch performance comparison | H | H | H | P | Branches HQ |  |
| Centralized customer database | H | H | H | P | Branches HQ |  |
| Shared loyalty across branches | H | H | H | P | Branches HQ |  |
| Centralized promotion control | H | H | H | P | Branches HQ |  |
| Region-wise reports | H | H | H | P | Branches HQ |  |
| Multi-currency support | H | H | H | P | Branches HQ |  |
| Multi-language support | H | H | H | P | Branches HQ |  |
| Role permissions by branch | H | H | H | P | Branches HQ |  |
| Menu publishing approval | H | H | H | P | Branches HQ |  |
| Bulk updates across locations | H | H | H | P | Branches HQ |  |

### Category 12 — Offline, backup, and reliability (19 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Offline order taking | S | P | H | P | Terminal + offline banner |  |
| Offline payment handling | H | P | H | P | Cashier terminal |  |
| Offline KOT printing | H | H | P | P | KDS / Reliability |  |
| Offline receipt printing | H | P | H | P | Cashier terminal |  |
| Local device cache | S | S | S | P | Top bar / Reliability | badge for all |
| Auto-sync when internet returns | S | S | S | P | Top bar / Reliability | badge for all |
| Conflict resolution | H | H | H | P | Reliability |  |
| Cloud backup | H | H | H | P | Reliability |  |
| Device failover | H | H | H | P | Reliability |  |
| Printer failover | H | H | P | P | KDS / Reliability |  |
| KDS fallback | H | H | P | P | KDS / Reliability |  |
| Daily automatic backup | H | H | H | P | Reliability |  |
| Data export | H | H | H | P | Reliability |  |
| Uptime monitoring | H | H | H | P | Reliability |  |
| Error logs | H | H | H | P | Reliability |  |
| Admin activity logs | H | H | H | P | Reliability |  |
| Disaster recovery | H | H | H | P | Reliability |  |
| Multi-device sync | H | H | H | P | Reliability |  |
| Network status dashboard | S | S | S | P | Top bar / Reliability | badge for all |

### Category 13 — Compliance and UAE-specific (20 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| VAT invoice | H | S | H | P | Bill / Checkout | shown on receipt; config owner |
| Simplified tax invoice | H | S | H | P | Bill / Checkout | shown on receipt; config owner |
| TRN field | H | H | H | P | Compliance |  |
| VAT breakdown | H | S | H | P | Bill / Checkout | shown on receipt; config owner |
| Tax-inclusive pricing | H | S | H | P | Bill / Checkout | shown on receipt; config owner |
| Tax-exclusive pricing | H | S | H | P | Bill / Checkout | shown on receipt; config owner |
| Credit note | H | H | H | P | Compliance |  |
| Refund note | H | H | H | P | Compliance |  |
| Z report | H | H | H | P | Compliance |  |
| Audit trail | H | H | H | P | Compliance |  |
| Invoice sequence control | H | H | H | P | Compliance |  |
| User action logs | H | H | H | P | Compliance |  |
| Data retention | H | H | H | P | Compliance |  |
| Export for accountant | H | H | H | P | Compliance |  |
| E-invoicing readiness | H | H | H | P | Compliance |  |
| Structured invoice data | H | H | H | P | Compliance |  |
| Accredited service provider integration readiness | H | H | H | P | Compliance |  |
| Arabic invoice support | H | H | H | P | Compliance |  |
| Bilingual receipt | H | S | H | P | Bill / Checkout | shown on receipt; config owner |
| Branch TRN support | H | H | H | P | Compliance |  |

### Category 14 — AI features (25 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| AI WhatsApp order taking | H | H | H | S | WhatsApp / Chats / AI | customer-facing AI; owner monitors |
| AI menu recommendation | H | H | H | S | WhatsApp / Chats / AI | customer-facing AI; owner monitors |
| AI upsell | H | H | H | S | WhatsApp / Chats / AI | customer-facing AI; owner monitors |
| AI combo suggestion | H | H | H | S | WhatsApp / Chats / AI | customer-facing AI; owner monitors |
| AI reorder prompt | H | H | H | P | AI Insights |  |
| AI abandoned order recovery | H | H | H | P | AI Insights |  |
| AI customer segmentation | H | H | H | P | AI Insights |  |
| AI daily sales summary | H | H | H | P | AI Insights |  |
| AI low-stock prediction | H | H | H | P | AI Insights |  |
| AI slow-moving item warning | H | H | H | P | AI Insights |  |
| AI food-cost anomaly detection | H | H | H | P | AI Insights |  |
| AI staff performance summary | H | H | H | P | AI Insights |  |
| AI customer complaint detection | H | H | H | P | AI Insights |  |
| AI review reply suggestion | H | H | H | P | AI Insights |  |
| AI negative review escalation | H | H | H | P | AI Insights |  |
| AI delivery ETA explanation | H | H | H | P | AI Insights |  |
| AI “why sales dropped” report | H | H | H | P | AI Insights |  |
| AI best menu bundle suggestion | H | H | H | P | AI Insights |  |
| AI promotion generator | H | H | H | P | AI Insights |  |
| AI festival campaign generator | H | H | H | P | AI Insights |  |
| AI menu translation | H | H | H | P | AI Insights |  |
| AI voice ordering | H | H | H | S | WhatsApp / Chats / AI | customer-facing AI; owner monitors |
| AI call answering | H | H | H | P | AI Insights |  |
| AI reservation handling | H | H | H | P | AI Insights |  |
| AI demand forecasting | H | H | H | P | AI Insights |  |

### Category 15 — Frontend UI shell & surfaces (31 features)

| Feature | W | C | K | O | Primary screen | Notes |
|---------|---|---|---|---|----------------|-------|
| Touch design tokens (56/64 targets, 16–28 type) | P | P | P | P | Shell | shared chrome |
| AppShell top status bar | P | P | P | P | Shell | shared chrome |
| Collapsible sidebar 88/240 + spec nav order | P | P | P | P | Shell | shared chrome |
| Alert center | P | P | P | P | Shell | shared chrome |
| TouchButton / primary action sizes | P | P | P | P | Shell | shared chrome |
| Bottom sticky action bar | P | P | P | P | Shell | shared chrome |
| Manager PIN modal | P | P | P | P | Shell | shared chrome |
| Money summary (≥28px totals) | S | P | H | P | Checkout |  |
| Empty / Error states | P | P | P | P | Shell | shared chrome |
| Login (email + staff PIN pad) | P | P | P | P | Shell | shared chrome |
| Onboarding wizard shell | H | H | H | P | Owner shell |  |
| Live Ops rush board | H | H | H | P | Owner shell |  |
| Floor Plan / table map | P | S | H | P | Floor Plan |  |
| Orders list (card-first) | P | P | H | P | Order screens |  |
| Order Detail full page | P | P | H | P | Order screens |  |
| New Order POS 3-pane | P | P | H | P | Order screens |  |
| Checkout / Payment tender UI | S | P | H | P | Checkout |  |
| Kitchen KDS touch redesign | H | H | P | P | KDS |  |
| Expo / ready pickup view | H | H | P | P | KDS |  |
| Rider Dispatch map + queue | H | H | H | P | Owner shell |  |
| WhatsApp inbox 3-pane | H | H | H | P | Owner shell |  |
| Public storefront mobile | H | H | H | S | Public / Rider | not staff home |
| QR table lock UX | H | H | H | S | Public / Rider | not staff home |
| Customer tracking page | H | H | H | S | Public / Rider | not staff home |
| Rider mobile web app | H | H | H | S | Public / Rider | not staff home |
| Manager screens touch polish | H | H | H | P | Owner shell |  |
| Role / license nav soft-gates | P | P | P | P | Shell | shared chrome |
| Offline limits on core screens | P | P | P | P | Shell | shared chrome |
| Accessibility baseline | P | P | P | P | Shell | shared chrome |
| Rush-hour load fixtures | H | H | H | P | Owner shell |  |
| Mac desktop package (redesign UI) | H | H | H | P | Owner shell |  |

---

## 4. Role feature packs (condensed must-haves)

### 4.1 Waiter pack

| Need | Features (from status doc) | Screen |
|------|----------------------------|--------|
| Take order | Dine-in, tableside, open/held | Floor + Waiter Order |
| Quantity | Cart qty on New Order / Order Detail | Waiter Order |
| Instructions | Add item notes, kitchen notes, allergy notes | Waiter Order / Detail |
| Modifiers | Forced/optional modifiers, variants, sizes, add-ons, combos | Waiter Order |
| Courses | Course-wise ordering, fire course later | Waiter Order Detail |
| Modify | Edit after kitchen (until ready) | Order Detail |
| Table ops | Transfer tables, merge, split by seat | Floor Plan |
| Urgency | Rush / priority (optional) | Order Detail |
| Not waiter | Refunds, voids, payments admin, menu edit, inventory, reports, AI, channels config | H |

### 4.2 Cashier pack

| Need | Features | Screen |
|------|----------|--------|
| Create order | All order types incl. takeaway/delivery/QR/call center | Cashier Terminal |
| See bill | Money summary, VAT breakdown on bill | Checkout |
| Modify | Edit items/qty/notes before ready | Order Detail |
| Pay | Cash, card, tap, wallets, links, split, partial, tips | Checkout |
| Discounts | Codes, staff discount; manager discount = PIN | Checkout |
| Loyalty | Points/gift/stamp redeem | Checkout |
| Drawer | Cash in/out, drawer management | Payments |
| Lookup | Phone search, reorder last | Customers / Terminal |
| Not cashier | Full inventory admin, franchise HQ, marketing campaigns, AI admin | H |

### 4.3 Kitchen pack

| Need | Features | Screen |
|------|----------|--------|
| See orders | KDS, station routing, all station types | `/kds` |
| Cook flow | Start prep, bump ready, recall | KDS ticket |
| Urgency | Color urgency, timers, delayed, auto-prioritize, late alerts | KDS |
| Safety | Allergen warning, modifier display | Ticket card |
| Quality | Packaging, missing item, QC | Ticket / Expo |
| Ready for delivery/pickup | Ready for pickup status, Expo handoff | `/kds?view=expo` |
| Print | KOT, printer fallback, category routing | System + KDS |
| Not kitchen | Create/pay orders, inventory PO, staff admin | H |

### 4.4 Owner pack

| Domain | Features | Screens |
|--------|----------|---------|
| Ops | All order + delivery dispatch + Live Ops | `/`, Floor, Orders, Riders, Chats |
| Money | All payments, EOD, recon, refunds (PIN) | Payments, Checkout, Reports |
| Catalog | Full menu control cat 3 | Menu |
| Stock | Full inventory cat 4 | Inventory |
| People | Staff, CRM, tickets, coupons | Staff, Customers, Tickets, Coupons |
| Growth | Marketing, AI cat 14 | Marketing, AI |
| Scale | Multi-branch cat 11 | Branches |
| Channels | Cat 8 incl. Talabat/Deliveroo/Keeta live | Channels |
| Trust | Compliance cat 13, Reliability cat 12 | Compliance, Reliability |
| Insight | Reports cat 10, Analytics | Reports, Analytics |

---

## 5. Cross-cutting rules

1. **PIN / Owner only:** void, refund, partial cancel after cook, manager discount, stock adjustment, channel pause, sensitive settings.  
2. **Quantity & instructions:** always on Waiter + Cashier order UIs (cart line controls + note fields). Kitchen **reads** notes/modifiers; does not edit order content.  
3. **Ready for delivery:** Kitchen marks ready → Expo/handoff; Owner assigns rider; Cashier may hand takeaway to customer.  
4. **No feature sprawl:** capabilities live as tabs/actions on role homes, not new top-level pages per feature.  
5. **Offline:** Waiter/Cashier/Kitchen see offline badge/limits; Owner manages Reliability.  

---

## 6. Gaps vs current implementation

| Gap | Status (2026-07-13) | Notes |
|-----|---------------------|-------|
| `waiter` role | **Closed** | `StaffRole` + ROUTE_ROLE_MAP + free-string staff model |
| Separate role homes | **Closed** | `getRoleHomePath` + Login PIN redirect |
| Waiter order mode | **Closed** | Send to kitchen; Bill at cashier; void escalate copy |
| Cashier bill home | **Closed** | Terminal strip; Place & Pay → checkout |
| Kitchen fullscreen | **Closed** | `getRoleChrome` hides sidebar; Expo tab |
| Owner | **Closed** | Live Ops + Admin nav + PIN matrix (Phase 5B) |
| In-shell staff switch | **Closed** | TopBar → `StaffSwitchModal` |
| Residual | Partial | Item notes + kitchen notes + open-bills count shipped; certified marketplace go-live still open |

---

## 7. Next build phases (after this doc)

**Full implementation plan (tasks, files, tests, exit criteria):**  
→ **`docs/superpowers/plans/2026-07-13-role-based-screens-implementation.md`**

| Phase | Work |
|-------|------|
| **R0** | Foundations: role helpers, landings, chrome API |
| **R1** | Add `waiter` role; ROUTE_ROLE_MAP; role-default landing routes |
| **R2** | Waiter chrome + Floor/Order mode (qty, instructions, no pay) |
| **R3** | Cashier terminal defaults + bill-first CTAs |
| **R4** | Kitchen fullscreen KDS/Expo defaults |
| **R5** | Owner Live Ops polish + alert center feeds |
| **R6** | Hardening: staff switch, e2e per role, placement audit |

---

## 8. Related docs

| Doc | Role |
|-----|------|
| `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md` | Feature evidence source |
| `docs/FULL_PRODUCT_FEATURE_CATALOG.md` | User-facing catalog |
| `docs/superpowers/plans/2026-07-09-pos-frontend-uiux-redesign-phases.md` | 36-screen IA |
| `docs/superpowers/plans/2026-07-13-role-based-screens-implementation.md` | **Implementation plan (this build)** |
| `frontend/src/lib/navAccess.ts` | Current route gates |

*End of placement document.*
