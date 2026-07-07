# Aggregator Integration — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase K1-extended, scoped)

## 1. Scope decision

Talabat/Deliveroo/Careem/Uber Eats each require a signed partner agreement
and real API credentials issued by that company — no amount of code makes
that "100% done" without the actual business relationship. **Not fabricable.**

What's real and buildable, matching the exact Mock/Real port pattern already
used for `llm/`, `whatsapp/`, and `payments/`: an `AggregatorPort` abstraction
+ a `MockAggregator` that simulates an inbound order webhook exactly the shape
a real Talabat/Deliveroo webhook would take, wired all the way through order
creation, so the day a real contract exists, only `aggregator_provider=talabat`
+ real credentials need to be added — zero changes to the ingestion pipeline.

## 2. Data model

- `orders` gets `aggregator_source` (nullable string: null=native WhatsApp order, else "talabat"|"deliveroo"|"careem"|"ubereats") and `aggregator_order_ref` (nullable string, the aggregator's own order ID, for reconciliation)

## 3. Flow

1. `POST /api/v1/aggregators/{provider}/webhook` — inbound order notification. Validates against `AggregatorPort.parse_inbound(payload)` which normalizes the aggregator's order shape into this platform's `Order`/`OrderItem` creation call (reusing `get_or_create_customer`, same as every other order-creation path).
2. `GET /api/v1/aggregators/reconciliation?start_date=&end_date=` — per-provider order count + revenue, for the "aggregator reconciliation" checklist item — pure aggregation over `orders.aggregator_source`, same pattern as `reports/analytics.py`.

## 4. API surface (new `src/app/aggregators/` module)

- `POST /api/v1/aggregators/{provider}/webhook`
- `GET /api/v1/aggregators/reconciliation`

## 5. Testing

Unit: `MockAggregator.parse_inbound` normalizes a sample payload correctly. Integration: webhook → order created with correct `aggregator_source`; reconciliation sums correctly across providers.

## Related
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase K
- Real Talabat/Deliveroo/Careem/Uber Eats credentials and signed partner agreements explicitly out of scope — this ships the ingestion pipeline ready to receive them.
