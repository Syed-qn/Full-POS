# Outbound Webhook Events (Platform → POS)

We POST JSON to the URL configured in `partner_webhook_url` when business events occur.
All webhooks share the same envelope format and HMAC signing.

## HTTP delivery

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |
| `X-Partner-Event` | Event type (e.g. `order.created`) |
| `X-Partner-Idempotency-Key` | Same as `idempotency_key` in body |
| `X-Partner-Signature` | `sha256=<hmac_hex>` of raw body bytes |

**POS must:**

1. Verify HMAC before processing
2. Return **2xx within 5 seconds** (we time out slow endpoints)
3. Deduplicate on `idempotency_key` (we may retry the same payload)

## Retry policy

| Attempt | Backoff |
|---------|---------|
| 1 | immediate |
| 2 | 10s |
| 3 | 20s |
| 4 | 40s |
| 5 | 80s |
| 6 | dead (no more retries) |

After **5 retries** the delivery is marked `dead` in our queue. POS should expose
a poll backup (`GET /api/v1/partner/orders`, `GET .../delivery`) for missed events.

## Envelope (all events)

```json
{
  "event": "order.created",
  "idempotency_key": "pos-order-created-42",
  "timestamp": "2026-07-01T13:37:00+00:00",
  "data": { }
}
```

## Event types

| Event | When fired | POS action |
|-------|------------|------------|
| `integration.ping` | Manager test button | Verify receiver works |
| `order.created` | Customer confirms order | Show on kitchen screen |
| `order.rider_assigned` | Dispatch assigns rider | Show rider + ETA |
| `order.picked_up` | Rider taps pickup | Show "out for delivery" |
| `order.delivered` | Rider taps delivered | Close order, record COD |
| `order.late` | SLA breach (40 min) | Flag late + show coupon |

### `order.created`

```json
{
  "event": "order.created",
  "idempotency_key": "pos-order-created-42",
  "timestamp": "2026-07-01T13:37:00+00:00",
  "data": {
    "order_id": 42,
    "order_number": "R1-0042",
    "pos_store_id": "CRT-DXB-014",
    "status": "confirmed",
    "customer": { "id": 7, "name": "Asfer", "phone": "+9715..." },
    "items": [
      { "dish_number": 110, "name": "Grill Mandi", "qty": 2, "price": 100.0 }
    ],
    "address": {
      "building": "Tower B",
      "room_apartment": "123",
      "latitude": 25.1,
      "longitude": 55.2
    },
    "subtotal": 200.0,
    "delivery_fee": 10.0,
    "total": 210.0,
    "cod_due": 210.0,
    "payment": "COD"
  }
}
```

### `order.rider_assigned`

Same delivery snapshot as poll endpoint — includes `rider`, `batch_id`, `eta_minutes`.

### `order.picked_up` / `order.delivered`

```json
{
  "event": "order.delivered",
  "idempotency_key": "pos-order-delivered-42",
  "data": {
    "order_id": 42,
    "order_number": "R1-0042",
    "status": "delivered",
    "rider": { "id": 3, "name": "Ahmed", "phone": "+97150..." },
    "delivered_at": "2026-07-01T14:22:00+00:00",
    "cod_due": 210.0,
    "cod_collected": 210.0
  }
}
```

### `order.late`

```json
{
  "event": "order.late",
  "idempotency_key": "pos-order-late-42",
  "data": {
    "order_id": 42,
    "order_number": "R1-0042",
    "sla_breach": true,
    "coupon_code": "R1-ABCD1234",
    "coupon_discount_aed": 10.0
  }
}
```

## Signature verification

### Python

```python
import hashlib
import hmac

def verify(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

### Node.js

```javascript
const crypto = require("crypto");

function verify(secret, rawBody, signatureHeader) {
  if (!signatureHeader?.startsWith("sha256=")) return false;
  const digest = crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
  const expected = `sha256=${digest}`;
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(signatureHeader)
  );
}
```

## POS receiver (minimal)

```python
# Flask example — one endpoint for all events
@app.post("/hooks/whatsapp")
def receive():
    raw = request.get_data()
    if not verify(WEBHOOK_SECRET, raw, request.headers.get("X-Partner-Signature")):
        return "", 401
    envelope = request.get_json()
    event = envelope["event"]
    idem = envelope["idempotency_key"]
    if already_processed(idem):
        return "", 200
    dispatch(event, envelope["data"])
    mark_processed(idem)
    return "", 200
```