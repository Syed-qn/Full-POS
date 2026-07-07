# UAE Compliance & Tax Invoicing — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase H, scoped)

## 1. Scope decision

Real UAE Ministry of Finance e-invoicing requires certified Accredited Service
Provider (ASP) transmission — a formal vendor onboarding + certification
process, not something to fabricate. **Out of scope.**

What's real and buildable: VAT calculation on orders (5% standard UAE rate),
a TRN field on the restaurant profile, and a VAT-compliant tax invoice
document (structured JSON — the same shape an ASP integration would consume
later, so this isn't wasted work) generated from an order's actual line items.

## 2. Data model

- `restaurants` gets `trn` (nullable string, UAE Tax Registration Number)
- `orders` gets `vat_rate` (Numeric, default 0.05 — snapshotted at order time so a later rate change doesn't retroactively alter historical invoices) and `vat_amount_aed` (Numeric, computed from subtotal at confirm time)

## 3. Flow

1. Manager sets TRN once in settings: existing `PATCH` restaurant-settings endpoint pattern (reuse, not a new one).
2. On order confirm (`finalize_confirmation`, same hook point as KDS/inventory), compute `vat_amount_aed = subtotal * vat_rate` and snapshot both onto the order.
3. `GET /api/v1/orders/{id}/tax-invoice` — returns a structured invoice: restaurant name + TRN, invoice number (`order_number`), line items with pre-VAT price, VAT rate, VAT amount, and total — the UAE FTA's required tax-invoice fields for a simplified invoice.

## 4. API surface

- Reuses `PATCH /api/v1/restaurants/settings` (existing) — no new endpoint for TRN.
- `GET /api/v1/orders/{id}/tax-invoice` (new, in `ordering/router.py` — this is invoice presentation of existing order data, not a new bounded context)

## 5. Testing

Unit: VAT calc for a multi-item order; snapshot doesn't change if the platform's default rate changes later. Integration: confirm order → tax-invoice endpoint returns correct FTA-required fields.

## Related
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase H
- MoF ASP transmission and formal e-invoice XML/UBL format generation explicitly deferred (see §1) — the structured JSON this phase produces is designed to feed that later without rework.
