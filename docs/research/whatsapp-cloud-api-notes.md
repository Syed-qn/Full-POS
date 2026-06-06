# WhatsApp Cloud API — Engineering Reference Notes
**Last verified:** 2026-06-06
**Source pages last updated:** May 21, 2026 (all Meta developer docs below)
**Graph API version used in examples:** v23.0 / v25.0

---

## Table of Contents
1. [Webhook Payload Shapes — Inbound Messages & Status Callbacks](#1-webhook-payload-shapes)
2. [Webhook Setup — GET Verification & X-Hub-Signature-256](#2-webhook-setup)
3. [Send API — POST /{phone_number_id}/messages](#3-send-api)
4. [24-Hour Customer Service Window & Template Categories / Pricing](#4-csw-and-pricing)
5. [Template Management API](#5-template-management-api)
6. [Media Upload & Download](#6-media-upload--download)
7. [Phone Number Throughput Tiers & Messaging Limits](#7-throughput-and-messaging-limits)
8. [Rider Use Case — Location Pins & Location Requests](#8-rider-use-case)

---

## 1. Webhook Payload Shapes

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/

All inbound webhook payloads share the outer envelope:
```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "<WABA_ID>",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "15550783881",
          "phone_number_id": "106540352242922"
        },
        "contacts": [{"profile": {"name": "Sheena Nelson"}, "wa_id": "16505551234"}],
        "messages": [ /* ... inbound message object ... */ ]
      },
      "field": "messages"
    }]
  }]
}
```
Status callbacks use `"statuses"` instead of `"messages"` in `value`.

### 1.1 Inbound Text Message

```json
{
  "messages": [{
    "from": "16505551234",
    "id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQzQTRBNjU5OUFFRTAzODEwMTQ0RgA=",
    "timestamp": "1749416383",
    "type": "text",
    "text": {"body": "Does it come in another color?"}
  }]
}
```

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text/

### 1.2 Inbound Interactive Button Reply

```json
{
  "messages": [{
    "context": {"from": "15550783881", "id": "wamid.PREV_MSG_ID"},
    "from": "16505551234",
    "id": "wamid.REPLY_MSG_ID",
    "timestamp": "1714510003",
    "type": "interactive",
    "interactive": {
      "type": "button_reply",
      "button_reply": {"id": "change-button", "title": "Change"}
    }
  }]
}
```

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/interactive/

### 1.3 Inbound Interactive List Reply

```json
{
  "messages": [{
    "context": {"from": "15550783881", "id": "wamid.PREV_MSG_ID"},
    "from": "16505551234",
    "id": "wamid.REPLY_MSG_ID",
    "timestamp": "1749854575",
    "type": "interactive",
    "interactive": {
      "type": "list_reply",
      "list_reply": {
        "id": "priority_express",
        "title": "Priority Mail Express",
        "description": "Next Day to 2 Days"
      }
    }
  }]
}
```

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/interactive/

### 1.4 Inbound Location Share

```json
{
  "messages": [{
    "from": "16505551234",
    "id": "wamid.LOCATION_MSG_ID",
    "timestamp": "1744344496",
    "type": "location",
    "location": {
      "address": "101 Forest Ave, Palo Alto, CA 94301",
      "latitude": 37.44221496582,
      "longitude": -122.16165924072,
      "name": "Philz Coffee",
      "url": "https://philzcoffee.com/"
    }
  }]
}
```
Note: `name`, `address`, `url` are optional — may be absent if user shares a plain pin.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/location/

### 1.5 Inbound Image Message

```json
{
  "messages": [{
    "from": "16505551234",
    "id": "wamid.IMAGE_MSG_ID",
    "timestamp": "1744344496",
    "type": "image",
    "image": {
      "caption": "Taj Mahal",
      "mime_type": "image/jpeg",
      "sha256": "SfInY0gGKTsJlUWbwxC1k+FAD0FZHvzwfpvO0zX0GUI=",
      "id": "1003383421387256",
      "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=133..."
    }
  }]
}
```
**Gotcha:** The `image.url` field is being **gradually released** starting November 12, 2025. It may be absent on some accounts. Always support the `id`-based download flow (GET `/{media_id}` → URL → fetch binary) as the primary path; treat `url` as an optional shortcut.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/image/

### 1.6 Status Callbacks

Status values: `sent`, `delivered`, `read`, `failed`

#### Sent (marketing template, PMP pricing)
```json
{
  "statuses": [{
    "id": "wamid.STATUS_MSG_ID",
    "status": "sent",
    "timestamp": "1750030073",
    "recipient_id": "16505551234",
    "conversation": {
      "id": "72b14d6bd5407799e66f64d1b338e567",
      "expiration_timestamp": "1750116480",
      "origin": {"type": "marketing"}
    },
    "pricing": {
      "billable": true,
      "pricing_model": "PMP",
      "type": "regular",
      "category": "marketing"
    }
  }]
}
```

#### Delivered (service conversation, CBP pricing — legacy pre-July 2025)
```json
{
  "statuses": [{
    "id": "wamid.STATUS_MSG_ID",
    "status": "delivered",
    "timestamp": "1750263773",
    "recipient_id": "16505551234",
    "conversation": {
      "id": "6ceb9d929c9bdc4f90e967a32f8639b4",
      "origin": {"type": "service"}
    },
    "pricing": {"billable": true, "pricing_model": "CBP", "category": "service"}
  }]
}
```

#### Failed
```json
{
  "statuses": [{
    "id": "wamid.STATUS_MSG_ID",
    "status": "failed",
    "timestamp": "1751142888",
    "recipient_id": "16505551234",
    "errors": [{
      "code": 131049,
      "title": "This message was not delivered to maintain healthy ecosystem engagement.",
      "message": "This message was not delivered to maintain healthy ecosystem engagement.",
      "error_data": {"details": "In order to maintain a healthy ecosystem engagement..."},
      "href": "/documentation/business-messaging/whatsapp/support/error-codes"
    }]
  }]
}
```

**Gotchas on statuses:**
- In API v24.0+, `conversation` object is **omitted** except during free entry point windows. Do not rely on its presence.
- `pricing` field appears only in `sent` **or** `delivered`, not both. Which one depends on implementation detail.
- `pricing_model`: `"PMP"` = per-message pricing (after July 1, 2025); `"CBP"` = conversation-based (legacy).
- `pricing.type`: `"regular"` = billable, `"free_customer_service"` = utility in open CSW (free after July 1 2025), `"free_entry_point"` = 72-hour free window from click-to-WhatsApp ad.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/statuses/

---

## 2. Webhook Setup

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started/

### 2.1 GET Verification Handshake

When you register a webhook URL, Meta sends a GET request with three query parameters:

| Parameter | Description |
|---|---|
| `hub.mode` | Always `"subscribe"` |
| `hub.challenge` | Random integer string Meta expects echoed back |
| `hub.verify_token` | The token you configured in Meta App Dashboard |

Your endpoint must:
1. Verify `hub.mode == "subscribe"`
2. Verify `hub.verify_token` matches your configured token
3. Respond with HTTP 200 and the plain-text body of `hub.challenge`

```python
# Django/Flask-style pseudocode
def webhook_verify(request):
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token")
    challenge = request.GET.get("hub.challenge")
    if mode == "subscribe" and token == YOUR_VERIFY_TOKEN:
        return HttpResponse(challenge, status=200)
    return HttpResponse(status=403)
```

### 2.2 X-Hub-Signature-256 Validation

Every POST webhook carries the header `X-Hub-Signature-256: sha256=<hex_digest>`.

**Algorithm:**
1. Read the **raw request body bytes** (before any JSON parsing)
2. Compute `HMAC-SHA256(key=APP_SECRET_bytes, msg=raw_body_bytes)`
3. Hex-encode the digest
4. Compare `"sha256=" + hex_digest` to the header value using a **timing-safe comparison**

```python
import hmac, hashlib

def validate_signature(raw_body: bytes, app_secret: str, header_value: str) -> bool:
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header_value)
```

**Gotcha:** Use the raw body bytes — not the decoded JSON string. Any re-serialisation will produce a different digest and fail validation.

**Source:** https://developers.facebook.com/docs/messenger-platform/webhooks#validate-payloads (same algorithm; WhatsApp uses same mechanism)

---

## 3. Send API

**Endpoint:** `POST https://graph.facebook.com/v23.0/{phone_number_id}/messages`
**Auth:** `Authorization: Bearer {SYSTEM_USER_ACCESS_TOKEN}`
**Content-Type:** `application/json`

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages/

### 3.1 Send Text Message

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+16505551234",
  "type": "text",
  "text": {
    "body": "Hello! Your order has been confirmed.",
    "preview_url": false
  }
}
```
Set `"preview_url": true` to enable link preview rendering.

### 3.2 Send Interactive Reply Buttons

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+16505551234",
  "type": "interactive",
  "interactive": {
    "type": "button",
    "header": {"type": "image", "image": {"id": "2762702990552401"}},
    "body": {"text": "Hi Pablo! Your gardening workshop is scheduled for 9am tomorrow. Would you like to change or cancel it?"},
    "footer": {"text": "Lucky Shrub: Your gateway to succulents!"},
    "action": {
      "buttons": [
        {"type": "reply", "reply": {"id": "change-button", "title": "Change"}},
        {"type": "reply", "reply": {"id": "cancel-button", "title": "Cancel"}}
      ]
    }
  }
}
```

**Limits:**
| Field | Limit |
|---|---|
| Buttons | Max **3** |
| Button title | Max **20 characters** |
| Button ID | Max **256 characters** |
| Body text | Max **1024 characters** |
| Footer text | Max **60 characters** |
| Header text (if text type) | Max **60 characters** |

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-messages/reply-buttons/

### 3.3 Send Interactive List Message

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+16505551234",
  "type": "interactive",
  "interactive": {
    "type": "list",
    "header": {"type": "text", "text": "Choose Shipping Option"},
    "body": {"text": "Which shipping option do you prefer?"},
    "footer": {"text": "Lucky Shrub: Your gateway to succulents"},
    "action": {
      "button": "Shipping Options",
      "sections": [
        {
          "title": "I want it ASAP!",
          "rows": [
            {"id": "priority_express", "title": "Priority Mail Express", "description": "Next Day to 2 Days"},
            {"id": "priority_mail", "title": "Priority Mail", "description": "1-3 Days"}
          ]
        }
      ]
    }
  }
}
```

**Limits:**
| Field | Limit |
|---|---|
| Sections | Max **10** |
| Rows total (across all sections) | Max **10** |
| Row title | Max **24 characters** |
| Row description | Max **72 characters** |
| Row ID | Max **200 characters** |
| Section title | Max **24 characters** |
| Button text (`action.button`) | Max **20 characters** |
| Body text | Max **4096 characters** |
| Header text | Max **60 characters** (text type only; lists do NOT support image headers) |
| Footer text | Max **60 characters** |

**Gotcha:** List messages only support a **text header** — no image, video, or document headers.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-messages/list-messages/

### 3.4 Send Location Request (Ask User to Share Location)

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "type": "interactive",
  "to": "+16505551234",
  "interactive": {
    "type": "location_request_message",
    "body": {"text": "Let's start with your pickup address. Please share your location."},
    "action": {"name": "send_location"}
  }
}
```
Body text max **1024 characters**. `action.name` must be exactly `"send_location"`.

Response from user arrives as a `type: "location"` webhook (see Section 1.4).

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-messages/location-messages/

### 3.5 Send Image Message

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+16505551234",
  "type": "image",
  "image": {
    "id": "1037543291543636",
    "caption": "Today's special: Grilled Sea Bass"
  }
}
```
Alternatively use `"link": "https://..."` instead of `"id"` if hosting the image yourself (not recommended at high throughput — see Section 7).

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/media-messages/

### 3.6 Send Template Message

#### Named parameter format (recommended — v23.0+):
```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+16505551234",
  "type": "template",
  "template": {
    "name": "order_confirmation",
    "language": {"code": "en_US"},
    "components": [
      {
        "type": "header",
        "parameters": [
          {"type": "image", "image": {"id": "2762702990552401"}}
        ]
      },
      {
        "type": "body",
        "parameters": [
          {"type": "text", "parameter_name": "first_name", "text": "Jessica"},
          {"type": "text", "parameter_name": "order_number", "text": "SKBUP2-4CPIG9"}
        ]
      },
      {
        "type": "button",
        "sub_type": "quick_reply",
        "index": "0",
        "parameters": [{"type": "payload", "payload": "STOP_PROMO"}]
      }
    ]
  }
}
```

#### Positional parameter format (legacy `{{1}}` style):
```json
{
  "messaging_product": "whatsapp",
  "to": "+16505551234",
  "type": "template",
  "template": {
    "name": "coupon_expiration_reminder",
    "language": {"code": "en"},
    "components": [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": "SUMMER20"},
          {"type": "text", "text": "10"}
        ]
      }
    ]
  }
}
```

**Gotcha:** Use `"parameter_name"` field only when the template was created with `"parameter_format": "named"`. For positional templates use positional array order. Starting v23.0, component parameter issues at send time return error `132018`.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/template-messages/

### 3.7 Send Static Location Pin to User

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+16505551234",
  "type": "location",
  "location": {
    "latitude": "37.44216251868683",
    "longitude": "-122.16153582049394",
    "name": "Philz Coffee",
    "address": "101 Forest Ave, Palo Alto, CA 94301"
  }
}
```
**Gotcha:** `latitude` and `longitude` are **strings** (quoted) in the send payload, even though they arrive as numbers in inbound location webhooks. `name` and `address` are optional.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/location-messages/

---

## 4. CSW and Pricing

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/

### 4.1 Customer Service Window (CSW)

- A **24-hour rolling window** opens whenever a user sends **any inbound message** to the business
- Within an open CSW: business can send **any message type** — free-form text, images, interactive messages — without a template
- Outside a CSW (no inbound message in last 24 hours): only **approved Message Templates** can initiate a conversation
- The window resets (extends 24 hours) with each new inbound message

### 4.2 Per-Message Pricing (PMP) — Effective July 1, 2025

Since July 1, 2025, pricing moved from conversation-based (CBP, 24-hour conversation windows) to **per-message pricing (PMP)**:

| Message Type | Cost |
|---|---|
| Marketing template | Billed per message sent |
| Utility template (outside open CSW) | Billed per message sent |
| Utility template (inside open CSW) | **FREE** from July 1, 2025 |
| Authentication template | Billed per message sent |
| Service messages (free-form within CSW) | **FREE** |
| Free entry point window (72 hrs after click-to-WhatsApp ad) | **FREE** — all message types |

**Gotcha:** `pricing.pricing_model` in status webhooks will be `"PMP"` for messages sent after July 1, 2025 and `"CBP"` for messages sent on the old system.

### 4.3 Template Categories

| Category | Use Case | Pricing (PMP) | Notes |
|---|---|---|---|
| `marketing` | Promotions, offers, daily specials | Billed per send | Subject to per-user frequency cap (see Section 5 in compliance doc) |
| `utility` | Order confirmations, shipping updates, appointment reminders | Billed per send outside CSW; **free inside CSW** | Must be triggered by customer action, not purely promotional |
| `authentication` | OTP, verification codes | Billed per send | Strict content rules (no emojis, no links in body) |

**Category auto-reclassification (from April 9, 2025):** Meta will auto-reclassify templates submitted as `utility` if the content is determined to be promotional. Reclassified templates are charged at `marketing` rates. Appeals allowed within 60 days.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-categorization/

---

## 5. Template Management API

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-management/

### 5.1 Create Template

**Endpoint:** `POST https://graph.facebook.com/v23.0/{waba_id}/message_templates`

#### With IMAGE header (named params, requires resumable upload handle):
```json
{
  "name": "reservation_confirmation",
  "category": "utility",
  "language": "en_US",
  "parameter_format": "named",
  "components": [
    {
      "type": "HEADER",
      "format": "IMAGE",
      "example": {
        "header_handle": ["4::aW1h..."]
      }
    },
    {
      "type": "BODY",
      "text": "*You're all set!*\n\nYour reservation for {{number_of_guests}} at Lucky Shrub Eatery on {{day}}, {{date}}, at {{time}}, is confirmed.",
      "example": {
        "body_text_named_params": [
          {"param_name": "number_of_guests", "example": "4"},
          {"param_name": "day", "example": "Saturday"},
          {"param_name": "date", "example": "August 30th, 2025"},
          {"param_name": "time", "example": "7:30 pm"}
        ]
      }
    },
    {
      "type": "FOOTER",
      "text": "Lucky Shrub Eatery: The Luckiest Eatery in Town!"
    },
    {
      "type": "BUTTONS",
      "buttons": [
        {"type": "URL", "text": "Change reservation", "url": "https://www.luckyshrubeater.com/reservations"},
        {"type": "PHONE_NUMBER", "text": "Call us", "phone_number": "+16467043595"},
        {"type": "QUICK_REPLY", "text": "Cancel reservation"}
      ]
    }
  ]
}
```

**Getting the image `header_handle`:** Use the **Resumable Upload API** to upload the example image:
1. `POST https://graph.facebook.com/v23.0/{app_id}/uploads?file_name={name}&file_length={bytes}&file_type=image/jpeg&access_token={token}` → returns `{"id": "upload:..."}` 
2. `POST https://graph.facebook.com/v23.0/{upload_session_id}` with `Authorization: OAuth {token}` and `file_offset: 0`, body = raw image bytes → returns `{"h": "4::aW1h..."}`
3. Use the returned `h` value as the `header_handle` in the template create payload

**Source:** https://developers.facebook.com/docs/graph-api/guides/upload

#### With positional variables (legacy `{{1}}` style):
```json
{
  "name": "coupon_expiration_reminder_number_vars",
  "category": "MARKETING",
  "language": "en",
  "parameter_format": "positional",
  "components": [
    {
      "type": "HEADER",
      "format": "TEXT",
      "text": "Act fast, {{1}}!",
      "example": {"header_text": ["Pablo"]}
    },
    {
      "type": "BODY",
      "text": "Your coupon code {{1}} expires in {{2}} days!",
      "example": {"body_text": [["SUMMER20", "10"]]}
    },
    {
      "type": "FOOTER",
      "text": "Lucky Shrub Succulents"
    },
    {
      "type": "BUTTONS",
      "buttons": [
        {"type": "URL", "text": "See deals", "url": "https://www.luckyshrub.com/deals"},
        {"type": "QUICK_REPLY", "text": "Unsubscribe"}
      ]
    }
  ]
}
```

**Template naming rules:**
- Regex: `^[a-z0-9_]+$` — lowercase alphanumeric + underscores only
- Max 512 characters
- Must be **unique per WABA per language**; same name + different language = separate template object
- Error `100` subcode `2388024` if name+language already exists

### 5.2 Template Status Values

| Status | Meaning |
|---|---|
| `PENDING` | Submitted, under review |
| `APPROVED` | Ready to use |
| `REJECTED` | Failed review |
| `PAUSED` | Quality degradation — temporary send block |
| `DISABLED` | Permanently disabled; cannot be re-enabled or deleted |
| `PENDING_DELETION` | Delete requested but pending delivery of in-flight messages (up to 30 days) |
| `ARCHIVED` | Inactive 12+ months; scheduled for deletion in 28 days |

### 5.3 Template Status Webhook

Meta sends a `message_template_status_update` webhook when template status changes:
```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "<WABA_ID>",
    "changes": [{
      "value": {
        "event": "APPROVED",
        "message_template_id": 1304694804498707,
        "message_template_name": "coupon_expiration_reminder_number_vars",
        "message_template_language": "en",
        "reason": null
      },
      "field": "message_template_status_update"
    }]
  }]
}
```
For `REJECTED`, `reason` contains the rejection reason string.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/message-template-status-updates/

### 5.4 Get Templates

```
GET https://graph.facebook.com/v23.0/{waba_id}/message_templates
    ?fields=name,category,status,language
    &status=approved
    &limit=5
Authorization: Bearer {token}
```

### 5.5 Edit Template

```
POST https://graph.facebook.com/v23.0/{template_id}
```
Body: updated `components` array (all components replaced wholesale — no partial update).

**Edit limits:**
- Approved template: max **10 edits per 30-day window**, or **1 edit per 24-hour window**
- Rejected/paused template: **unlimited edits**
- Cannot edit `category` of an approved template via this endpoint

### 5.6 Delete Template

#### By name (deletes ALL language variants with that name):
```
DELETE https://graph.facebook.com/v23.0/{waba_id}/message_templates?name=order_confirmation
Authorization: Bearer {token}
```
Response: `{"success": true}`

#### By ID (single variant):
```
DELETE https://graph.facebook.com/v23.0/{waba_id}/message_templates?hsm_id=1407680676729941&name=order_confirmation
```

#### By multiple IDs (up to 100):
```
DELETE https://graph.facebook.com/v23.0/{waba_id}/message_templates?hsm_ids=[1387372356726668,1304694804498707]
```
`hsm_ids` cannot be combined with `name` or `hsm_id`. If any ID is invalid, entire request fails.

**Delete constraints:**
- Deleted template that had undelivered in-flight messages: status set to `PENDING_DELETION`; delivery attempted for **30 days**
- After deleting an approved template: **same name cannot be reused for 30 days**
- `DISABLED` templates cannot be deleted
- Requires `whatsapp_business_management` permission (not just `whatsapp_business_messaging`)

### 5.7 Rate Limits & Counts

| Limit | Value |
|---|---|
| Template creation rate | **100 per WABA per hour** |
| Template count (unverified portfolio) | **250 per WABA** |
| Template count (verified portfolio with approved display name) | **6,000 per WABA** |
| Inactive template auto-archival | After **12 months** of inactivity |
| Auto-archive deletion window | **28 days** after archival |

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview/

---

## 6. Media Upload & Download

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/media/

### 6.1 Upload Media

```
POST https://graph.facebook.com/v25.0/{phone_number_id}/media
Authorization: Bearer {token}
Content-Type: multipart/form-data

messaging_product=whatsapp
file=@/path/to/file.jpg;type=image/jpeg
```

Response:
```json
{"id": "1037543291543636"}
```

Use the returned `id` directly in send API calls (`"image": {"id": "1037543291543636"}`).

### 6.2 Get Media URL (from media ID)

```
GET https://graph.facebook.com/v25.0/{media_id}?phone_number_id={phone_number_id}
Authorization: Bearer {token}
```

Response:
```json
{
  "messaging_product": "whatsapp",
  "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=...",
  "mime_type": "image/jpeg",
  "sha256": "SfInY0gGKTsJlUWbwxC1k+FAD0FZHvzwfpvO0zX0GUI=",
  "file_size": "109982",
  "id": "1037543291543636"
}
```

**URL expiry: 5 minutes.** Fetch binary immediately after getting the URL.

### 6.3 Download Media Binary

```
GET {media_url_from_step_above}
Authorization: Bearer {token}
```
Returns raw binary data. Must include the Authorization header — the URL itself is not publicly accessible.

### 6.4 Delete Media

```
DELETE https://graph.facebook.com/v25.0/{media_id}
Authorization: Bearer {token}
```
Response: `{"deleted": true}`

### 6.5 Supported Media Types & Size Limits

| Type | MIME Types | Max Size (Upload/Send) | Max Inbound (Cloud API) |
|---|---|---|---|
| Image | image/jpeg, image/png | 5 MB | 5 MB |
| Audio | audio/aac, audio/mp4, audio/mpeg, audio/amr, audio/ogg | 16 MB | 16 MB |
| Video | video/mp4, video/3gpp | 16 MB | 16 MB |
| Document | application/pdf, and Office formats | 100 MB | 100 MB |
| Sticker | image/webp | 500 KB | 100 KB (static), 500 KB (animated) |
| Any inbound media | — | — | **100 MB** |

### 6.6 Media ID Expiry

| Media ID Source | Expiry |
|---|---|
| Uploaded via API (Section 6.1) | **30 days** |
| From inbound webhook (`image.id`, `audio.id`, etc.) | **7 days** |

Download inbound media promptly — do not rely on 7-day window in production.

---

## 7. Throughput and Messaging Limits

### 7.1 Per-Phone-Number Throughput (MPS)

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/throughput/

| Phone Number Type | Default MPS | Max Achievable MPS |
|---|---|---|
| Standard Cloud API number | **80 mps** | **1,000 mps** (automatic upgrade) |
| WhatsApp Business App numbers (dual-use) | **20 mps** (fixed) | 20 mps (no upgrade path) |

Throughput = inbound + outbound + all message types combined.

**Error on throughput exceed:** `130429`

**Auto-upgrade to 1,000 mps eligibility:**
- Business portfolio must have **Unlimited** messaging limit tier
- Phone number must have messaged **100K+ unique users** outside a CSW in a rolling 24-hour period
- Phone number must have quality score of **YELLOW or higher**
- Upgrade takes up to 1 minute; during upgrade `131057` is returned

**Webhook server capacity guidance:** provision 3× outgoing MPS capacity for status webhooks + 1× for incoming messages.

**Get current throughput:**
```
GET /{phone_number_id}?fields=throughput
Authorization: Bearer {token}
```

### 7.2 Business Portfolio Messaging Limits (Daily Unique Users)

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits/

Since October 2025, messaging limits apply at **Business Portfolio level** (not per phone number).

| Tier | Daily Limit | Field Value |
|---|---|---|
| TIER_250 | 250 unique users/day (outside CSW) | `TIER_250` |
| TIER_1K | 1,000 unique users/day | `TIER_1K` |
| TIER_10K | 10,000 unique users/day | `TIER_10K` |
| TIER_100K | 100,000 unique users/day | `TIER_100K` |
| TIER_UNLIMITED | Unlimited | `TIER_UNLIMITED` |

**API field:** `whatsapp_business_manager_messaging_limit` (old `messaging_limit_tier` deprecated)

**Auto-scaling criteria:**
- Used >50% of current daily limit in the past 7 days
- Messages maintain a high quality rating (not flagged or restricted)
- When criteria met, tier upgrades automatically over 24 hours

**Tier advancement blocked during:**
- Phone number `Flagged` status (7-day block per flag event)
- Account in `Restricted` status

### 7.3 Business Verification Requirements

- Start at TIER_250 without verification
- Meta Business Verification (submit business docs to Meta) required to advance beyond TIER_250 to higher tiers
- Verified portfolio: template count raised to 6,000 (vs 250 unverified)
- New phone numbers added to a **verified portfolio** inherit the portfolio's existing tier — they do not start at TIER_250

---

## 8. Rider Use Case

### 8.1 Business Sending Location Pin to User — SUPPORTED

A business can push a static lat/lng pin to a user using `type: "location"` (see Section 3.7).
- `latitude` and `longitude` are required (as string values)
- `name` and `address` are optional display fields
- No interactive element — purely informational map pin

**Use case for riders:** Send the restaurant's location pin to the customer, or send the rider's pickup point. Works within CSW as a free-form message; outside CSW must use a template (but templates do not support `type: "location"` — the location pin message type is NOT available as a template component type).

**Gotcha:** If sending a location pin outside a CSW (e.g., first message to customer), you cannot use the `type: "location"` standalone message. Instead, include the address as text in a template body, or use a location component in a template if supported by your BSP. Standard Cloud API template components do not include a standalone location pin type; only text, image, document, video, and button components are documented.

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/location-messages/

### 8.2 Requesting User Location — SUPPORTED

Use `interactive.type: "location_request_message"` (see Section 3.4).

**Constraints:**
- Only sends a prompt button — the user must tap "Share Location" in the WhatsApp UI
- Cannot be forced or automated
- Requires an **open CSW** or a template wrapper (the `location_request_message` is an interactive message type, usable within CSW as free-form; outside CSW it must be sent via an approved marketing or utility template that wraps an interactive component — availability of this in templates is **UNVERIFIED** for all BSPs)
- The user's response arrives as a standard `type: "location"` webhook (Section 1.4)

**Source:** https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-messages/location-messages/

---

## Appendix: Quick Limits Reference

| Item | Limit | Source |
|---|---|---|
| Reply buttons per message | 3 | Send API docs |
| Button title | 20 chars | Send API docs |
| Button ID | 256 chars | Send API docs |
| List sections | 10 | Send API docs |
| List rows total | 10 | Send API docs |
| Row title | 24 chars | Send API docs |
| Row description | 72 chars | Send API docs |
| Row ID | 200 chars | Send API docs |
| List button text | 20 chars | Send API docs |
| Body text (interactive/template) | 1024 chars | Send API docs |
| Body text (list) | 4096 chars | Send API docs |
| Header text | 60 chars | Send API docs |
| Footer text | 60 chars | Send API docs |
| Template name | 512 chars, `^[a-z0-9_]+$` | Template Management docs |
| Template creation rate | 100/hour/WABA | Template Overview docs |
| Templates per unverified WABA | 250 | Template Overview docs |
| Templates per verified WABA | 6,000 | Template Overview docs |
| Name reuse after delete | 30 days | Template Management docs |
| Media URL expiry | 5 minutes | Media docs |
| Uploaded media ID expiry | 30 days | Media docs |
| Inbound media ID expiry | 7 days | Media docs |
| Image max size | 5 MB | Media docs |
| PDF max size | 100 MB | Media docs |
| Default throughput | 80 mps | Throughput docs |
| Max throughput (auto upgrade) | 1,000 mps | Throughput docs |
| Throughput error | 130429 | Throughput docs |
| Frequency cap error | 131049 | Webhooks/error codes |

---

## Adapter Design Gotchas Summary

1. **Webhook normalizer:** Check `value.messages` for inbound vs `value.statuses` for delivery receipts. Both can appear in the same webhook payload (batch). Process all entries.

2. **Interactive type dispatch:** `messages[n].type == "interactive"` — then check `interactive.type` for `"button_reply"` vs `"list_reply"` vs `"location_request_message"` (the last only appears on outbound sends, not inbound).

3. **Image URL in webhooks:** `image.url` may be absent (gradual rollout from Nov 12, 2025). Always fall back to `image.id` + GET media endpoint flow.

4. **Location send payload:** `latitude`/`longitude` must be **strings** in the send body even though they are floats in incoming webhook payloads.

5. **List messages:** No image header support. Attempting `"header": {"type": "image", ...}` on a list message will be rejected.

6. **Template send with named params:** Only use `"parameter_name"` field if the template was created with `"parameter_format": "named"`. Mixing formats causes `132018` errors.

7. **Status webhook `conversation` field absent in v24.0+:** Do not assume `status.conversation` exists. Build the webhook normalizer to handle its absence.

8. **Pricing field location:** `pricing` appears in `sent` OR `delivered` status, not necessarily both. Check both.

9. **X-Hub-Signature-256:** Must validate against raw body bytes before parsing. Framework middleware that re-encodes the body will break validation.

10. **send_template outside CSW:** Any `type: "template"` message can be sent at any time regardless of CSW state. Free-form messages (`text`, `image`, `interactive`) require an open CSW.
