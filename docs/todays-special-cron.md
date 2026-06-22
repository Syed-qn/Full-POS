# Today's Special — cron heartbeat setup

The "Today's Special" automation sends each opted-in customer the daily special a
few minutes before their own predicted ordering time. Because the Render free
tier has **no Celery/Redis and sleeps when idle**, an **external cron job** must
ping the app every ~10–15 minutes to drive the per-customer timed sends.

## 1. Set the shared secret (server)

The heartbeat endpoint is guarded by a secret so it's never open to the public.
Generate a long random value and set it as an environment variable on the server
(Render → Environment):

```
APP_MARKETING_TICK_SECRET=<long-random-string>
```

Generate one, e.g.:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

If this variable is empty/unset, the endpoint returns **503** (disabled) — so the
feature is off until you set it.

> Also required on Render free tier (already documented for marketing):
> `APP_OUTBOX_SYNC_DELIVERY=true` so the sends actually go out in-request.

## 2. Point a cron job at the endpoint

Have any scheduler call this every 10–15 minutes (it only sends to customers whose
time is *due* that minute, and is idempotent — one send per customer per day):

```bash
curl -fsS -X POST https://restaurant-whatsapp-service.onrender.com/api/v1/marketing/tick \
  -H "X-Tick-Secret: <long-random-string>"
```

Response (example): `{"queued": 3, "suppressed": 1, "restaurants": 1}`.

### Free options for the scheduler
- **cron-job.org** — create a job, method POST, URL above, add a custom header
  `X-Tick-Secret: <secret>`, interval every 10 min.
- **UptimeRobot** — "HTTP(s)" monitor, POST, custom header, 10-min interval (also
  keeps the free Render service awake).
- **GitHub Actions** — scheduled workflow:

```yaml
# .github/workflows/todays-special-tick.yml
name: todays-special-tick
on:
  schedule:
    - cron: "*/10 * * * *"   # every 10 minutes (UTC)
jobs:
  tick:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -fsS -X POST "$URL" -H "X-Tick-Secret: $SECRET"
        env:
          URL: https://restaurant-whatsapp-service.onrender.com/api/v1/marketing/tick
          SECRET: ${{ secrets.MARKETING_TICK_SECRET }}
```

## 3. Turn it on (manager dashboard)

Marketing page → **Today's Special (auto-timed)** → enable the toggle, pick an
**approved** template, optionally adjust the lead time (default 15 min) and the
default time for customers without a clear ordering pattern → **Save automation**.

## How the timing works
- Each customer's usual order time is the circular mean of their past order times
  (Asia/Dubai). With ≥3 clustered orders it's "personalized"; otherwise the
  restaurant default time is used.
- Send time = predicted time − lead minutes, clamped to the UAE **09:00–18:00**
  window. Opt-out and the 2-per-24h cap still apply.
- The cron cadence is the granularity: a 10-min cron means "11:45" lands in the
  11:40 or 11:50 tick.
