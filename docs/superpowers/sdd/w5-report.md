# W5 — Money & catalogue price integrity — Implementation Report

**Branch:** `remediation/w0-eval-harness`
**Base:** `5686001` (fix(ordering): preserve cart-line note through qty-set + note double-masala path)
**Closes:** R-019, R-049, R-050, R-051, F26, F41, F112, F31, RA-3, TX-31, TX-33 (money/price slice)

## Per-task commits

| Task | SHA | Subject |
|------|-----|---------|
| 1 — RED evals | `33d10a6` | test(w5): RED evals for money & catalogue price integrity |
| 2 — DB columns + migration | `dbe0710` | feat(ordering): add Order.coupon_discount_aed + distance_source columns |
| 3 — payments.py | `de910be` | feat(payments): recompute_order_total + apply_coupon single money path |
| 4 — modify_order | `a2a69ab` | fix(ordering): modify_order re-applies coupon + wallet via recompute (F26) |
| 5 — _redeem_coupon_at_checkout | `41cead3` | fix(engine): route _redeem_coupon_at_checkout through payments.apply_coupon (F41) |
| 6 — summary + renderer | `51d1117` | feat(summary): coupon + wallet credit + COD-due composition (R-049/RA-3) |
| 7 + 8 — catalogue snapshot + QuantityPolicy | `9360531` | feat(catalog): snapshot Meta item_price + block drift + qty guard (R-019/R-050/R-051) |
| 9 — distance_source | `601a640` | feat(geo): _road_distance_km returns (distance, source); persist distance_source (F112/F31) |
| 10 — graduate evals | `ff87317` | chore(evals): graduate W5 money & price-integrity evals |

## Migration

- **Revision id:** `m6f7a8b9c0d1` (down_revision `l5e6f7a8b9c0`, the real head at start).
- Adds `orders.coupon_discount_aed NUMERIC(8,2) NOT NULL DEFAULT 0` and
  `orders.distance_source VARCHAR(32) NULL`. Applied to `restaurant_test`; `alembic heads`
  now reports `m6f7a8b9c0d1 (head)`.
- `app.ordering.models` was already imported in both `alembic/env.py` and `tests/conftest.py`,
  so no new metadata registration was needed.

## What changed (design)

- **One money path.** New `payments.recompute_order_total(order)` re-derives subtotal from
  the persisted `OrderItem`s (falls back to the stored subtotal only when an order has no line
  rows), re-applies `order.coupon_discount_aed` (clamped ≥ 0, never below the delivery-fee
  floor), and clamps the wallet hold down to the new total — releasing and re-holding the
  capped amount on the ledger so a shrunk order can never over-capture (RA-3).
- **`payments.apply_coupon(order, coupon_code)`** validates/redeems through the coupon service
  (idempotent on `order:{id}:coupon`), persists `coupon_id` + `coupon_discount_aed`, then
  recomputes — the only sanctioned coupon money mutation (F41). `modify_order` and
  `_redeem_coupon_at_checkout` both route through this path; neither mutates `order.total` by
  hand anymore (F26/F41).
- **Catalogue price integrity.** `add_item` gained `price_aed_override`; `handle_catalog_order`
  snapshots the tapped Meta `item_price` onto the order line, and BLOCKS the item (with a
  price-mismatch reply) when it drifts >0.01 from the active `CatalogProduct.price_aed`
  (R-019/R-051). A new standalone `app.ordering.quantity_policy.QuantityPolicy`
  (`from_restaurant` / `check_line` / `QuantityError`) enforces the per-line max-qty guard on
  catalogue baskets at parity with the typed path (R-050); W8 imports it.
- **Truthful summary.** `_send_order_summary` and `renderer.render_cart_state` now render the
  coupon-discount line (if any), wallet credit applied = `min(available[+existing hold], total)`,
  and `COD due = total − applied`. Summary math == confirm math == door cash (R-049/RA-3).
- **Deterministic geo.** `_road_distance_km` returns `(distance_km, source)` where `source ∈
  {"road", "haversine_fallback"}`; all six call sites unpack it and persist `order.distance_source`
  (ordering, saved-address, pin, receiver-details, and both resale paths) (F112/F31).

## Evals

All 5 W5 evals in `tests/evals/test_w5_money_price_integrity.py` were written RED
(`xfail(strict=True)`), then **graduated** to permanent passing regression tests in Task 10:

- (a) `test_catalogue_snapshots_meta_item_price` — R-051
- (b) `test_catalogue_price_drift_blocks_item` — R-019
- (c) `test_summary_shows_wallet_credit_and_cod_due` — R-049 / RA-3
- (d) `test_modify_order_preserves_coupon_and_wallet` — F26
- (e) `test_distance_source_flags_haversine_fallback` — F112 / F31

No W5 eval was left xfail. `tests/evals/REGISTRY.md` updated with the W5 section.

## Final suite summary

`.venv/bin/pytest tests/ordering tests/catalog tests/conversation tests/evals -q`

```
471 passed, 7 xfailed, 0 failed
```

- The 7 remaining xfails are pre-existing other-workstream capability evals (W6/W8 — lakh
  qty, reactions, catalogue-keyword typo, idempotency, etc.); none are W5.
- No new failures introduced. Two pre-existing regression tests were updated for the
  intentional API change: `tests/conversation/test_road_distance.py` (tuple contract) and the
  `recompute_order_total` itemless-order guard keeps `test_checkout_redeem_options.py` green.

`ruff check` passes on every changed file.

## Files changed

- `alembic/versions/m6f7a8b9c0d1_order_coupon_discount_distance_source.py` (new)
- `src/app/ordering/models.py`
- `src/app/ordering/payments.py`
- `src/app/ordering/service.py`
- `src/app/ordering/quantity_policy.py` (new)
- `src/app/conversation/engine.py`
- `src/app/conversation/renderer.py`
- `src/app/catalog/service.py`
- `tests/evals/test_w5_money_price_integrity.py` (new)
- `tests/evals/REGISTRY.md`
- `tests/conversation/test_road_distance.py`

## BLOCKED items

None. The assumed coupon (`coupons.service.validate_and_redeem`) and wallet
(`wallet.service.get_or_create_account / available / hold / release / capture`) signatures
matched exactly; no reconciliation gaps.
