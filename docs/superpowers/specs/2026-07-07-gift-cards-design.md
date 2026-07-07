# Gift Cards — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase K1, scoped)

## 1. Scope decision

Phase K as a whole (aggregator integration, caller ID, AI upsell/voice/summary,
multi-currency, digital signage, third-party accounting/payroll) needs real
vendor accounts and API keys this session has none of — **out of scope, not
fabricable**. The one genuinely buildable, vendor-free piece: **gift cards**,
which reuse the existing `wallet/` ledger machinery (`WalletAccount`/`WalletEntry`)
already built and tested — a gift card is just a `promo_credit`-type wallet
entry created from a purchase instead of a refund.

## 2. Data model

No new tables. Reuses `app.wallet.models.WalletAccount`/`WalletEntry` as-is.
A gift card purchase is: find-or-create the recipient's `WalletAccount`, add a
`WalletEntry` with `type="promo_credit"`, `amount_aed=<card value>`,
`idempotency_key` derived from a purchase reference (so a retried purchase
request can't double-credit).

## 3. Flow

1. `POST /api/v1/gift-cards/purchase` — body: recipient phone, amount_aed, purchase_reference. Looks up or creates a `Customer` + `WalletAccount` for the recipient phone, credits the amount as a `promo_credit` wallet entry.
2. Redemption already works — the existing order-confirm wallet-apply path (`app.ordering.payments.apply_at_confirm`) already deducts available wallet balance from COD due. No new redemption code needed.
3. `GET /api/v1/gift-cards/balance/{phone}` — thin wrapper reading the customer's wallet balance (sum of `posted` entries).

## 4. API surface (new `src/app/giftcards/` module — thin, delegates to `wallet/`)

- `POST /api/v1/gift-cards/purchase`
- `GET /api/v1/gift-cards/balance/{phone}`

## 5. Testing

Unit: purchase creates a wallet entry with correct type/amount; duplicate purchase_reference doesn't double-credit (idempotency_key collision). Integration: purchase → balance query reflects it → (existing wallet apply-at-confirm test coverage already proves redemption works, not re-tested here).

## Related
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase K
- Aggregator integration, caller ID, AI voice/upsell/summary, multi-currency, digital signage explicitly deferred (see §1) — each needs a real third-party vendor relationship this session cannot establish.
