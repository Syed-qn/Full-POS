# 100% Feature Audit — Advanced Restaurant POS List (2026-07-08)

**Method:** 7 parallel read-only agents grepped/read actual code (`src/app/`, `apps/workers/`, `frontend/src/`, `alembic/`) against the 14-category feature list supplied by the user (based on Lightspeed/Oracle/Square/Stripe advanced-POS feature sets). Status per item: **FULL** (model+service+router+tests, and frontend UI where applicable) / **PARTIAL** (some layer missing — usually frontend UI, or enforcement) / **MISSING** (not found).

**Status: COMPLETE — all 7 audit batches landed (14 categories, ~365 items).**

**Tally: 128 FULL · 96 PARTIAL · 141 MISSING.** Not close to 100%. Biggest single driver: backend built, frontend not (staff, tables, aggregators, most of reporting, inventory all have zero manager-dashboard screens). Second driver: whole feature families genuinely absent (course-wise/split/merge orders, allergen data, dynamic/time-based pricing, franchise hierarchy, most AI-narrative features, e-invoicing).

**Supersedes:** `docs/POS_FEATURE_GAP_ANALYSIS.md` (2026-07-07, pre-dates the tables/staff/aggregators/combos modules landed later that day) for the categories covered here.

---

## Cross-cutting finding (applies to every category below)

**Backend is far ahead of frontend.** Staff (PIN login, clock in/out, shifts, tip pool, cash drawer), tables, aggregators, menu combos/modifiers/upsell — all have full backend model+service+router+tests, but **zero corresponding screens in `frontend/src/screens/`**. Confirmed via grep across `frontend/src/screens/*.tsx` and `frontend/src/api/*` — no matches for staff/PIN/clock/shift/tip-pool/drawer/tables/aggregator UI. A feature marked FULL below is backend-only unless a frontend file is explicitly cited as evidence.

**COD-only rule intact for delivery.** `src/app/payments/` (cash/card/Apple Pay/Google Pay via Stripe, splits, refunds) is a separate in-restaurant/POS till-checkout module — the WhatsApp/delivery money path (`src/app/cod/`, `ordering/payments.py:cod_due_aed`) stays cash-on-delivery only, consistent with CLAUDE.md's non-negotiable rule. The till-checkout module itself is **not described in the spec at all** — worth a scoping decision (see Open Questions).

---

## Category 8 — Aggregator & channel integrations

| Item | Status | Evidence |
|---|---|---|
| Talabat integration | PARTIAL | `src/app/aggregators/factory.py:4` lists "talabat", routes to `MockAggregator` only — no real SDK/credentials. |
| Deliveroo integration | PARTIAL | Same, mock-only. |
| Noon Food integration | MISSING | Not in `_SUPPORTED` set, no code. |
| Careem integration | PARTIAL | In `_SUPPORTED`, mock-only. |
| Uber Eats integration | PARTIAL | In `_SUPPORTED`, mock-only. |
| Zomato integration | MISSING | Only incidental UI comment, no integration code. |
| Website ordering | MISSING | No web-order module/route/frontend found. |
| Mobile app ordering | MISSING | No mobile client found. |
| WhatsApp ordering | **FULL** | `src/app/conversation/` + `src/app/whatsapp/` adapter, router/service/tests — primary channel by design. |
| Instagram order link | MISSING | Not found. |
| Google Business Profile order link | MISSING | Not found. |
| QR table ordering | PARTIAL | `src/app/tables/` (labels, seats, position, status, transfer) exists; no QR-code generate/scan-to-order endpoint. |
| Self-order kiosk | MISSING | No kiosk ordering flow. |
| Call center order entry | MISSING | POS manual order entry exists, not phone/call-center specific. |
| Centralized order inbox | PARTIAL | `OrdersScreen.tsx` + `LiveOpsScreen.tsx` aggregate by `Order.aggregator_source`, but no unified inbox/routing concept. |
| Menu sync across platforms | PARTIAL | `pos/sync_service.py` syncs one direction only (POS→internal catalog), no aggregator-side push. |
| Price sync across platforms | MISSING | Not found. |
| Stock sync across platforms | MISSING | Not found. |
| Pause orders per channel | MISSING | No pause field/endpoint. |
| Channel-wise commission report | MISSING | Reconciliation is revenue-only, no commission %. |
| Channel-wise profitability report | MISSING | Not found. |
| Aggregator reconciliation | PARTIAL | `aggregators/service.py:79 reconciliation()` sums order_count/revenue by provider; no statement-matching. |

## Category 9 — Staff & permissions

| Item | Status | Evidence |
|---|---|---|
| Staff login | FULL (backend) | `staff/router.py:27`, hashed PIN, JWT+role. |
| PIN login | FULL (backend) | `StaffLoginIn.pin`, `pin_hash` on model. |
| Role-based access | FULL (backend) | `require_role()` dep, `tests/staff/test_rbac.py`. |
| Manager approval | PARTIAL | Only gates order cancel/edit + refund; no generic approval workflow. |
| Void approval | FULL (backend) | `cancel_order_endpoint` requires manager role. |
| Discount approval | MISSING | Coupons are self-service, no approval gate. |
| Refund approval | FULL (backend) | `payments/router.py:44-47` requires manager role. |
| Shift open/close | PARTIAL | Only scheduled-shift creation, no actual open/close state. |
| Clock in/out | FULL (backend) | `ClockEvent` model, `service.py`, `router.py:69`. |
| Break tracking | MISSING | `ClockEvent.type` has no break_start/end. |
| Attendance | PARTIAL | Derivable from clock events, no dedicated report. |
| Staff scheduling | PARTIAL | Basic weekly shift list, no conflict/availability/swap. |
| Overtime tracking | MISSING | `compute_hours` has no OT threshold. |
| Tip pooling | FULL (backend) | `staff/tips.py:distribute_tip_pool`. |
| Tip by staff | PARTIAL | Even split only, not per-order attribution. |
| Sales by staff | FULL (backend) | `service.py:71 compute_sales`. |
| Mistake tracking | MISSING | Not found. |
| Cash drawer assignment | PARTIAL | `opened_by/closed_by` free-text, not FK to staff. |
| Staff performance report | PARTIAL | Pieces exist (sales, hours) but no consolidated report. |
| Training mode | MISSING | Not found. |
| Audit log | PARTIAL | `record_audit` used in ordering, **not called anywhere in `staff/` or `cashdrawer/`** — clock/shift/drawer events unaudited. |
| Suspicious activity alerts | MISSING | Not found. |

---

## Category 5 — Payment & billing

| Item | Status | Evidence |
|---|---|---|
| Cash | FULL | `payments/models.py:17`, `service.py:40-43`. |
| Card | FULL | `stripe_gateway.py:12-14`. |
| Tap to pay | MISSING | No NFC/terminal integration. |
| Apple Pay | PARTIAL | Listed as tender_type, routed through generic Stripe card, no native wallet button. |
| Google Pay | PARTIAL | Same pattern. |
| Online payment | PARTIAL | Server-initiated Payment Intents, no hosted checkout link. |
| Payment link | MISSING | Not found. |
| Split payment | FULL | `payments/models.py:10`, `service.py:49-54`. |
| Partial payment | FULL | `total_paid()`, `cod_due_aed`. |
| Pay later | MISSING | Not found. |
| House account | MISSING | Not found. |
| Room charge (hotels) | MISSING | Not found. |
| Tips | FULL | `payments/models.py:19`, `staff/tips.py`. |
| Service charge | MISSING | Not found anywhere. |
| Delivery charge | FULL | `geo/fees.py:22-36 delivery_fee_aed` (matches spec tiers). |
| Packaging charge | MISSING | Not found. |
| Minimum order charge | MISSING | Only coupon-eligibility floor exists, not a fee. |
| Discount codes | FULL | `coupons/service.py`, `CouponsScreen.tsx`. |
| Staff discount | MISSING | No role-scoped discount type. |
| Manager discount | PARTIAL | Reuses generic coupon issuance, no dedicated till override. |
| Loyalty redemption | FULL | `loyalty/service.py`, wallet hold/capture. |
| Gift card redemption | FULL | `giftcards/service.py`. |
| Refunds | FULL | `payments/service.py:57-75`. |
| Partial refunds | FULL | Arbitrary amount up to remaining. |
| Credit note | MISSING | No distinct document/model. |
| Deposit payment | MISSING | Not found. |
| Advance payment | MISSING | Not found. |
| End-of-day cash closing (Z-report) | PARTIAL | `cashdrawer/service.py:58-78` computes variance; no printable Z-report artifact or frontend. |
| Cash drawer management | FULL | `cashdrawer/models.py`, full router+tests. |
| Cash in/out | FULL | `CashDrawerEvent.type`. |
| Over/short cash report | FULL | `service.py:70-76`. |
| Payment reconciliation | PARTIAL | COD side full (`cod/service.py:reconcile_shift`); no Stripe↔PSP settlement tie-out. |
| Failed payment handling | FULL | `PaymentFailedError`, `status="failed"`. |
| Duplicate payment detection | PARTIAL | Generic idempotency middleware exists but not confirmed wired to `/payments/charge`. |

---

## Category 3 — Menu & item control

| Item | Status | Evidence |
|---|---|---|
| Menu categories | PARTIAL | `Dish.category` free-text, no dedicated model/CRUD. |
| Subcategories | MISSING | Not found. |
| Item variants | FULL | `Dish.variants` JSONB + validation. |
| Item sizes | FULL | Same variants mechanism. |
| Add-ons | FULL | `ModifierGroup`/`Modifier` + CRUD. |
| Modifiers | FULL | Same, tested. |
| Forced modifiers | PARTIAL | `required` field stored, not enforced in cart flow. |
| Optional modifiers | FULL | `min_select`/`max_select`. |
| Combo meals | FULL | `Combo`/`ComboItem`, service, router, tests. |
| Meal bundles | FULL | Same combo feature. |
| Upsell rules | FULL | Market-basket engine + endpoint + tests. |
| Cross-sell rules | PARTIAL | Same engine, no dedicated cross-sell config. |
| Happy hour pricing | MISSING | Not found. |
| Time-based pricing | MISSING | Not found. |
| Channel-based pricing | MISSING | Not found. |
| Branch-based pricing | MISSING | Not found. |
| Delivery-only menu | MISSING | Not found. |
| Dine-in-only menu | MISSING | Not found. |
| QR-only menu | MISSING | Not found. |
| Cloud kitchen brand menus | MISSING | Not found. |
| Menu item availability | FULL | `Dish.is_available`, `PATCH .../availability`. |
| Auto-hide out-of-stock item | MISSING | Toggle is manual only, stock deduction never flips it. |
| Item countdown | MISSING | Not found. |
| Recipe linking | FULL | `DishIngredient` + router. |
| Ingredient linking | FULL | Same. |
| Allergen tags | MISSING | Only LLM prompt mentions allergens, no structured field. |
| Nutrition data | MISSING | Not found. |
| Item images | FULL | `Dish.image_url` + upload endpoint. |
| Multilingual menu | PARTIAL | Bot converses multilingually at runtime; no per-language dish fields. |
| Arabic menu | PARTIAL | Bilingual receipt labels exist; no per-dish Arabic field. |
| English menu | FULL | Default content language. |
| Menu approval workflow | MISSING | `Menu.status` has no manager-approval gate. |
| Bulk menu import | PARTIAL | AI-extraction multi-file upload, no CSV bulk import. |
| Bulk price update | MISSING | Only single-dish PATCH exists. |
| Seasonal menu scheduling | MISSING | Not found. |

## Category 4 — Inventory & food cost

| Item | Status | Evidence |
|---|---|---|
| Ingredient-level inventory | FULL | `Ingredient` model + CRUD. |
| Recipe-level costing | FULL | `costing.py:dish_cost()`. |
| Stock deduction by recipe | FULL | `service.py:deduct_for_order`. |
| Wastage tracking | FULL | `WasteLog`, `record_waste`. |
| Spoilage tracking | PARTIAL | Not distinguished from wastage. |
| Stock transfer | FULL | `StockTransfer`/`StockTransferLine`, cross-branch. |
| Multi-location stock | FULL | Ingredients scoped per branch + transfer. |
| Stock count | FULL | `record_stock_count`. |
| Stock variance report | PARTIAL | Per-ingredient only, no aggregate report. |
| Par level | PARTIAL | Approximated via `low_stock_threshold`. |
| Reorder point | PARTIAL | Same field reused, no auto-suggestion. |
| Supplier management | FULL | `Vendor` model + router. |
| Purchase orders | FULL | `PurchaseOrder`/`PurchaseOrderLine`. |
| Goods received note | FULL | `receive_purchase_order` increments stock. |
| Cost price tracking | FULL | `Ingredient.cost_per_unit_aed` + PATCH. |
| Vendor price comparison | MISSING | Not found. |
| Food cost percentage | MISSING | `dish_cost()` exists, no cost/price ratio computed. |
| Gross margin by item | MISSING | Not found. |
| Over-portioning alerts | MISSING | Not found. |
| Theft/loss alerts | MISSING | Not found. |
| Expiry date tracking | FULL | `IngredientBatch.expiry_date`, `list_expiring_soon`. |
| Batch tracking | FULL | `IngredientBatch`, `add_batch`. |
| Central kitchen inventory | MISSING | Not found. |
| Commissary kitchen support | MISSING | Not found. |
| Ingredient substitution | MISSING | Not found (customer dish-substitution ≠ this). |
| Low-stock WhatsApp alert | PARTIAL | `list_low_stock` exists, never wired to whatsapp/workers — no outbound alert sent. |
| Daily stock closing report | MISSING | Not found. |
| Stock adjustment approval | MISSING | `record_stock_count` applies immediately, no gate. |
| Recipe yield tracking | MISSING | Quantity-per-dish only, no prep-loss/yield tracking. |

---

## Category 13 — UAE compliance

| Item | Status | Evidence |
|---|---|---|
| VAT invoice | FULL | `ordering/tax.py:15 build_tax_invoice()`, `GET /orders/{id}/tax-invoice`. |
| Simplified tax invoice | MISSING | No distinct simplified/B2C variant. |
| TRN field | FULL | `Restaurant.settings["trn"]`, SettingsScreen.tsx UI. |
| VAT breakdown | PARTIAL | Single order-level vat_rate/amount only, no per-line or zero-rated/exempt breakdown. |
| Tax-inclusive pricing | MISSING | No inclusive-VAT mode. |
| Tax-exclusive pricing | PARTIAL | Additive VAT only, no configurable mode toggle. |
| Credit note | MISSING | Not found. |
| Refund note | MISSING | Payment refund exists, no compliance refund-note document. |
| Z report | FULL | `reports/zreport.py:build_z_report()`, `GET /reports/z-report`. |
| Audit trail | FULL | `AuditLog`, `record_audit`, `GET /audit-log`. |
| Invoice sequence control | FULL | `analytics.py:invoice_sequence_report()`, gap-free advisory-lock allocation. |
| User action logs | FULL | Same AuditLog infra, actor-tracked. |
| Data retention | MISSING | No retention/deletion policy code. |
| Export for accountant | PARTIAL | CSV export for item-performance only, no full ledger export. |
| E-invoicing readiness | MISSING | Explicitly out-of-scope per code comment (`receipt_i18n.py:8-10`). |
| Structured invoice data | PARTIAL | Structured JSON, not UBL/PINT AE standard format. |
| Accredited service provider readiness | MISSING | No ASP/Peppol transmission code. |
| Arabic invoice support | PARTIAL | Static label translation only, dish names/addresses not translated. |
| Bilingual receipt | FULL | `bilingual_labels()` en/ar on every invoice, tested. |
| Branch TRN support | PARTIAL | Each branch = own Restaurant row w/ own TRN, works structurally, no dedicated test. |

## Category 14 — AI features

*(re-verified pass — supersedes first-pass row values below where they differ)*

| Item | Status | Evidence |
|---|---|---|
| AI WhatsApp order taking | FULL | `conversation/engine.py` calls real LLM (`llm/claude.py`/`deepseek.py`) via webhook, tested. |
| AI menu recommendation | FULL | `llm/suggestion_agent.py` — DeepSeek then Claude-haiku fallback, triggered on suggest/recommend intents. |
| AI upsell | PARTIAL | `menu/upsell.py` explicitly rule-based ("Deterministic, statistics-only... No ML/LLM vendor call"), no LLM, no frontend UI. |
| AI combo suggestion | MISSING | `menu/combos.py` is pure admin CRUD for static bundles, no scoring/LLM. |
| AI reorder prompt | MISSING | Only a static marketing-automation preset key, not conversation-triggered. |
| AI abandoned order recovery | PARTIAL | Celery beat task fires, but sends a hard-coded static template (`_NUDGE_BODY`), no LLM call. |
| AI customer segmentation | PARTIAL | Segment classification (RFM) is rule-based; but `compile_segment_from_english` does call a real LLM for plain-English→DSL, wired to router+frontend. |
| AI daily sales summary | MISSING | Z-report is pure numeric aggregation, no LLM narration. |
| AI low-stock prediction | PARTIAL | `list_low_stock` is a simple threshold comparison, not ML/forecast-driven; no link to `predictions` module. |
| AI slow-moving item warning | MISSING | Not found. |
| AI food-cost anomaly detection | MISSING | Not found. |
| AI staff performance summary | MISSING | No summary/scoring logic; only raw `on_time_pct` feeding dispatch scoring, not staff-facing narration. |
| AI customer complaint detection | FULL | `llm/complaint_agent.py` real LLM agent, tested, frontend in `TicketsScreen.tsx`. |
| AI review reply suggestion | MISSING | No free-text review entity exists at all (only numeric NPS). |
| AI negative review escalation | MISSING | Same — no review-text escalation logic. |
| AI delivery ETA explanation | PARTIAL | `dispatch/explain.py` builds numeric/template projections only, no LLM call. |
| AI "why sales dropped" report | MISSING | No LLM/narration code in reports module. |
| AI best menu bundle suggestion | MISSING | Deterministic serving-size matching + static combo CRUD, not AI-generated. |
| AI promotion generator | FULL | `marketing/copywriter.py` real LLM call w/ non-LLM fallback, wired to router+frontend, tested. |
| AI festival campaign generator | MISSING | No festival/holiday campaign-generation code (only unrelated `is_holiday` demand-forecast feature flag). |
| AI menu translation | MISSING | No menu-language-translation code; existing "translat" hits are unrelated (action-schema, marketing-audience DSL). |
| AI voice ordering | FULL | `speech/elevenlabs.py` real ElevenLabs STT, wired end-to-end in engine.py, tested, frontend in `MessageBubble.tsx`. |
| AI call answering | MISSING | Zero IVR/telephony code found. |
| AI reservation handling | MISSING | Tables module is floor-plan/CRUD only, no WhatsApp/LLM booking flow. |
| AI demand forecasting | FULL (statistical, not LLM) | `predictions/rolling.py` real numpy statistical model, Celery-scheduled, full test+frontend coverage. Note: not an LLM call — "AI" here means ML, not GenAI. |

---

## Category 10 — Reporting & owner dashboard

**Pattern: backend service+router exists for nearly everything, but almost zero frontend wiring.**

| Item | Status | Evidence |
|---|---|---|
| Daily/Hourly/Weekly/Monthly sales report | PARTIAL (x4) | `reports/analytics.py:262 sales_rollup(granularity=...)`, `/sales-rollup`; no frontend. |
| Sales by item | PARTIAL | `item_performance`, `/item-performance`; no frontend. |
| Sales by category | MISSING | Not found. |
| Sales by channel | MISSING | No channel dimension. |
| Sales by branch | PARTIAL | `organizations/service.py:57 branch_comparison`, tested; no frontend. |
| Sales by waiter | MISSING | Only labor_hours by staff exists, not sales. |
| Sales by payment method | MISSING | Not found. |
| Gross profit report | PARTIAL | `item_performance` computes margin_aed/pct; no frontend. |
| Food cost report | PARTIAL | Via `inventory/costing.py:dish_cost`; no frontend. |
| Discount report | PARTIAL | Only aggregate total in zreport, no itemized report/frontend. |
| Void report | MISSING | Only order cancellation FSM exists. |
| Refund report | MISSING | `refund_transaction` exists, no report endpoint. |
| Wastage report | PARTIAL | `waste_log` model/service exist, no report endpoint/frontend. |
| Top-selling items | PARTIAL | `item_performance` sorted by revenue, no dedicated endpoint/frontend. |
| Slow-moving items | MISSING | Not found. |
| Dead menu items | MISSING | Not found. |
| Average order value | MISSING | Not found. |
| Average table turnover time | PARTIAL | `table_turn_time`; no frontend. |
| Average prep time | PARTIAL | `avg_prep_time_by_item/staff`; no frontend. |
| Average delivery time | MISSING | Not found. |
| Customer repeat/retention rate | PARTIAL | `retention_report`; no frontend. |
| New vs returning customers | PARTIAL | Same `retention_report`; no frontend. |
| Peak hour report | MISSING | Not found. |
| Branch comparison | PARTIAL | Tested backend, no frontend. |
| Forecasted sales | PARTIAL | `predictions/` full stack, frontend wired via `AnalyticsScreen.tsx`. |
| Inventory valuation | MISSING | Not found. |
| Cash closing report | PARTIAL | `zreport.py`; no frontend. |
| Tax report | PARTIAL | Invoice-level only, no aggregate VAT report/frontend. |
| Export to Excel | PARTIAL | CSV only, not xlsx; no frontend. |
| WhatsApp daily owner report | MISSING | Not found — no beat task, no owner_report code. |

## Category 11 — Multi-branch/franchise

**Architectural note: `restaurant_id` is the sole tenant scope — a "restaurant" IS the branch unit. No parent franchise/organization table exists above it; `organizations/service.py` is an ad-hoc rollup querying restaurant rows by ID list. True franchise-hierarchy features are MISSING by design, not oversight.**

| Item | Status | Evidence |
|---|---|---|
| Central dashboard | PARTIAL | `organizations/router.py:69 /rollup-sales`; no frontend. |
| Branch-wise dashboard | PARTIAL | Same rollup, per-branch breakdown; no frontend. |
| Centralized menu | MISSING | Menu strictly restaurant_id-scoped, no org-level template. |
| Branch-specific pricing | FULL | Restaurant_id-scoped Dish/price rows, tested. |
| Branch-specific stock | FULL | Ingredient rows restaurant_id-scoped, tested. |
| Branch-wise staff | FULL | StaffMember restaurant_id-scoped. |
| Central kitchen support | MISSING | No commissary concept. |
| Stock transfer between branches | FULL | `StockTransfer`/`StockTransferLine`, tested. |
| Franchise royalty report | MISSING | Not found. |
| Branch performance comparison | PARTIAL | Same as branch comparison, no frontend. |
| Centralized customer database | MISSING | Customer unique(restaurant_id, phone), no org-level table. |
| Shared loyalty across branches | MISSING | Loyalty tables restaurant_id-scoped. |
| Centralized promotion control | MISSING | Coupons restaurant_id-scoped. |
| Region-wise reports | MISSING | No region concept. |
| Multi-currency support | MISSING | All money hardcoded AED. |
| Multi-language support | PARTIAL | WhatsApp layer is language-agnostic; no i18n on manager dashboard. |
| Role permissions by branch | PARTIAL | StaffMember.role scoped to one restaurant by construction, no cross-branch RBAC matrix. |
| Menu publishing approval | MISSING | Menu router auto-publishes to Meta catalog, no approval workflow. |
| Bulk updates across locations | MISSING | "Bulk" ops are within one restaurant only, not cross-branch. |

## Category 12 — Offline/backup/reliability

| Item | Status | Evidence |
|---|---|---|
| Offline order taking | FULL | `desktop/src/main/db.ts` (pending_ops), `sync.ts` pushSync/pullSync, tested. |
| Offline payment handling | MISSING | Generic offline queue only, no payment-specific flow. |
| Offline KOT printing | PARTIAL | `printJobPoller.ts` polls pending jobs, but printer driver is a stub (`NotImplementedPrinter` throws). |
| Offline receipt printing | MISSING | Only KOT print jobs exist. |
| Local device cache | FULL | `db.ts initSchema` (local_menu/local_orders/sync_state SQLite), tested. |
| Auto-sync when internet returns | FULL | `sync.ts` retry-on-failure, `scheduler.ts` periodic ticks, tested. |
| Conflict resolution | PARTIAL | `pending_ops` has 'conflict' status + `SyncConflictBanner.tsx` for manual review; no automated merge logic. |
| Cloud backup | MISSING | `audit/backup_status.py` explicitly states no real backup integration — readiness self-check only. |
| Device failover | MISSING | Not found. |
| Printer failover | MISSING | Single stub PrinterPort, no secondary/failover. |
| KDS fallback | MISSING | Not found. |
| Daily automatic backup | MISSING | No scheduled backup task in celery beat_schedule. |
| Data export | PARTIAL | CSV export only, no full account export. |
| Uptime monitoring | PARTIAL | External health endpoints exist, no internal dashboard. |
| Error logs | PARTIAL | Sentry integration (no-op unless DSN set), no in-app viewer. |
| Admin activity logs | PARTIAL | Audit log backend built, no frontend viewer screen. |
| Disaster recovery | MISSING | Not found in code, docs-only mentions. |
| Multi-device sync | FULL | Cursor-based pull/push, tested. |
| Network status dashboard | PARTIAL | Per-screen `navigator.onLine` indicator only, no dedicated dashboard. |

---

## Category 6 — Customer/CRM/loyalty

| Item | Status | Evidence |
|---|---|---|
| Customer profile | FULL | `ordering/models.py:22`, `customer_router.py`, `CustomerProfileScreen.tsx`, tested. |
| Phone number history | MISSING | Only current phone field, no history. |
| WhatsApp opt-in | FULL | `marketing/optout.py`, wired in router+frontend, tested. |
| Order history | FULL | `customer_router.py`, rendered in `CustomerProfileScreen.tsx`. |
| Favorite items | PARTIAL | Only internal upsell "most-ordered" logic, no customer-facing favorites UI. |
| Last order shortcut | PARTIAL | `duplicate_order` exists, no confirmed frontend reorder button. |
| Customer notes | MISSING | Only per-order item notes, no free-text note on Customer model. |
| Allergy notes | MISSING | Not found. |
| Birthday | MISSING | Not found. |
| Anniversary | MISSING | Not found. |
| VIP tag | PARTIAL | Generic `Customer.tags` JSONB, no dedicated VIP flag/UI. |
| Complaint history | FULL | `Ticket` model/service/router. |
| Refund history | FULL | Tickets wallet-refund + payments refund service. |
| Loyalty points | PARTIAL | Tier-based, no separate points ledger/counter. |
| Cashback | FULL | `loyalty/service.py:earn()` + reversal, tested. |
| Stamp card | MISSING | Not found. |
| Gift cards | FULL | `giftcards/service.py` + router, tested. |
| Referral rewards | FULL | `loyalty/referrals.py`, referral_router, tested. |
| Coupon campaigns | FULL | `coupons/` full stack + `CouponsScreen.tsx`. |
| Win-back campaigns | FULL | `marketing/automations.py`, tested. |
| Birthday offers | MISSING | Not found — only welcome/winback/reorder/recurring presets. |
| Inactive customer campaigns | FULL | Same win-back preset infra. |
| Customer segmentation | FULL | `marketing/segments.py`, tested. |
| High-value customer list | PARTIAL | Achievable via segment filter on total_spend, no dedicated report. |
| Average order value by customer | MISSING | Not found. |
| Customer lifetime value | MISSING | Only running total_spend field, no CLV calc. |
| Feedback collection | FULL | `loyalty/nps.py:record_nps_response`, tested. |
| Review request automation | MISSING | No outbound review-request trigger. |
| NPS survey | FULL | `NpsResponse` model + service, tested. |
| Negative review escalation | PARTIAL | Complaint escalation exists, not tied to NPS detractor scores. |
| Personalized offers | PARTIAL | "Today's Special" personalized by predicted order time; no per-customer offer-content personalization. |

## Category 7 — Delivery management

| Item | Status | Evidence |
|---|---|---|
| Delivery order dashboard | FULL | `OrdersScreen.tsx`, tested. |
| Manual driver assignment | FULL | `dispatch/service.py:reassign_order`, wired frontend. |
| Auto driver assignment | FULL | `run_dispatch_engine` (greedy/OR-tools, no accept/reject — matches "riders are employees" rule). |
| Driver app | FULL | `rider-app/App.tsx` + `dispatch/rider_app_router.py` (no accept/decline endpoint by design). |
| Driver live location | FULL | `dispatch/rider_location.py`, `LiveOpsMap.tsx`. |
| Rider status | FULL | `identity/models.py:185-191`, `RiderCard.tsx`. |
| Pickup / Out-for-delivery / Delivered / Failed delivery status | FULL (x4) | `dispatch/delivery.py` FSM, `rider_app_router.py`, `ordering/fsm.py:UNDELIVERABLE`. |
| Customer location pin | FULL | `ordering/models.py:57-59` (lat/lng), `LocationPicker`. |
| Address notes | FULL | `additional_details` field, `NewOrderScreen.tsx`. |
| Building/floor/apartment fields | PARTIAL | building + room_apartment exist, no dedicated "floor" field. |
| Delivery zone pricing | FULL | `geo/fees.py` — exact spec tiers (≤3km free/3-5km AED5/>5-10km AED10), tested. |
| Delivery distance calculation | FULL | `geo/haversine.py`, Google Maps w/ fallback, tested. |
| ETA calculation | FULL | `geo/fake.py`, `google_maps.py`, `dispatch/service.py`. |
| Delivery route optimization | FULL | `dispatch/optimizer.py` (OR-Tools VRP), `batching.py`. |
| Priority delivery | FULL | `optimizer.py:_assign_priority`. |
| Multi-order batching | FULL | `dispatch/batching.py`, `batch_plan.py`, tested. |
| Driver cash collection | FULL (backend only) | `cod/models.py CodCollection`, `service.py:record_collection`; no dedicated frontend UI. |
| Driver settlement | PARTIAL | `reconcile_shift` exists but `expected = collected` is stubbed — variance always zero, not wired to router/worker/frontend. |
| Delivery proof photo | FULL (backend only) | `dispatch/delivery_proof.py`, no frontend/rider-app upload UI. |
| OTP delivery confirmation | FULL | `delivery_proof.py:generate/verify_delivery_otp`, tested. |
| Customer tracking link | FULL | `dispatch/tracking_live.py`, `RiderTrackingScreen.tsx`. |
| WhatsApp delivery updates | FULL | `rider_flow.py:_notify_customer_status`. |
| Late delivery alert | FULL | `sla/monitor.py` (yellow_30/red_35/breach_40, auto-coupon skipped on weather_delay_disclosed — matches spec exactly), idempotent. |
| Driver performance report | MISSING | No per-rider report endpoint/screen. |
| Average delivery time | MISSING | Not found — dispatch KPIs have no delivery-duration metric. |
| Cancelled delivery reasons | FULL | `cancellation_reason`/`cancelled_reason` fields, wired frontend. |

---

## Category 1 — Order management

| Item | Status | Evidence |
|---|---|---|
| Dine-in orders | PARTIAL | `tables/` module exists, but `Order` has no order_type/dine-in field. |
| Takeaway orders | MISSING | No order-type/channel field distinguishing takeaway. |
| Delivery orders | FULL | Full FSM, `NewOrderScreen.tsx`. |
| Online orders | FULL | WhatsApp is the native online-order path. |
| QR code orders | MISSING | No "qr" reference anywhere. |
| Tableside orders | PARTIAL | Tables module exists, not tied to order-creation flow. |
| Drive-thru orders | MISSING | Not found. |
| Aggregator orders | FULL | `aggregators/service.py:ingest_inbound_order`, `Order.aggregator_source`. |
| Open orders | FULL | `_OPEN_STATUSES` frozenset, `OrdersScreen.tsx`. |
| Held orders | MISSING | No held/on_hold status in FSM. |
| Scheduled orders | FULL | `Order.scheduled_for`, tested. |
| Pre-orders | FULL | Same scheduled-order mechanism. |
| Reorders / Duplicate order / Repeat last order | FULL (x3, same feature) | `ordering/duplicate.py:duplicate_order`, tested. |
| Refund orders | PARTIAL | Only wallet refund on complaint tickets, no order-level payment refund (COD-only). |
| Cancelled orders | FULL | CANCELLED FSM state, tested. |
| Partial cancellation | FULL | `cancel_order_item`, tested. |
| Void order w/ manager approval | FULL | `require_role("manager")` gate, tested. |
| Edit order after sending to kitchen | FULL (blocked by design) | `_assert_order_modifiable` blocks post-ready edits, tested. |
| Add item notes | FULL | `OrderItem.notes`, `set_item_note`. |
| Add kitchen notes | PARTIAL | Same `notes` field doubles as kitchen note — not distinct, and KDS ticket payload doesn't surface it. |
| Customer allergy notes | MISSING | Not modeled anywhere. |
| Course-wise ordering | MISSING | No "course" concept. |
| Fire course later | MISSING | Not found. |
| Rush order button | MISSING | Not found. |
| Priority order button | PARTIAL | `Order.priority` field exists, no dedicated set-priority endpoint/button. |
| Split order by item | MISSING | Not found. |
| Split order by seat | MISSING | `DiningTable.seats` is just a capacity int. |
| Merge orders | MISSING | Only same-dish cart-line merge exists, not order merge. |
| Transfer order between tables | FULL | `tables/service.py:transfer_order`, tested. |
| Transfer order between staff | MISSING | Not found. |

## Category 2 — Kitchen/KDS

| Item | Status | Evidence |
|---|---|---|
| Kitchen Display System | FULL | `kds/router.py`, `KdsScreen.tsx`, tested. |
| Kitchen Order Ticket | FULL | `create_tickets_for_order`. |
| Station-wise routing | PARTIAL | `KitchenStation` is generic user-named, no grill/fry/dessert presets or cloud-kitchen concept. |
| Prep time tracking | FULL | `OrderItem.bumped_at`, `_prep_minutes`. |
| Estimated ready time | MISSING | No ETA field on ticket/station. |
| Auto-prioritize old orders | MISSING | Station-tickets query has no order_by/priority sort. |
| Color-coded order urgency | FULL | `ticketUrgency`/`URGENCY_COLOR` in frontend. |
| Order bump screen | FULL | `PATCH /items/{id}/bump`. |
| Recall completed ticket | FULL | `PATCH /items/{id}/recall`. |
| Delayed ticket warning | PARTIAL | SLA-level manager alerts exist, no per-item KDS-ticket warning. |
| KDS item timer | PARTIAL | Elapsed age recomputed for color only, no visible timer element. |
| Kitchen performance report | PARTIAL | Prep-time metrics exist, no broader throughput/station-load report. |
| Avg prep time by item | FULL | `analytics.py:191-210`. |
| Avg prep time by staff | PARTIAL | Actually groups by station, not per-staff (code comment admits this). |
| Late order alerts | FULL | SLA yellow_30/red_35/breach_40. |
| Multi-kitchen routing | MISSING | Stations scoped per single restaurant only. |
| Printer fallback if KDS fails | PARTIAL | Heartbeat/health tracked, no fallback rerouting logic. |
| Kitchen printer routing by item category | FULL | `CategoryStationDefault`/`resolve_station`. |
| Allergen warning on kitchen ticket | MISSING | No allergen field anywhere. |
| Modifier display on ticket | PARTIAL | `selected_modifiers` exists on OrderItem but omitted from ticket payload/schema. |
| Packaging checklist | MISSING | Not found. |
| Missing item confirmation | MISSING | Only a customer-complaint ticket category, not a KDS packing feature. |
| Quality check status | MISSING | Not found. |
| Ready for pickup status | PARTIAL | `kitchen_status="ready"` set on bump, no distinct customer/rider-facing endpoint. |

---

## Scoping decisions (resolved 2026-07-08)

1. **Till-checkout `payments/` module** — IN SCOPE, finish it. Close gaps: tap-to-pay, service charge, credit note, deposit/advance payment, Z-report UI, payment reconciliation vs PSP.
2. **Aggregator integrations** — BUILD REAL ADAPTERS for Talabat/Deliveroo/Careem/Uber Eats (Noon Food, Zomato stay out unless requested later). Real credentials, webhook auth, menu/price/stock push, commission/profitability reporting.
3. **Multi-branch/franchise** — ADD PARENT `Organization` ENTITY. New table owns multiple `Restaurant` rows. Enables centralized menu/customer-db/shared loyalty/promotions/region reports. This is a multi-tenancy core change — touches `identity/deps.py:current_restaurant` resolution and needs careful migration (existing restaurants become orgs-of-one by default).
