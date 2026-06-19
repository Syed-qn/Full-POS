# Rider Tracker (Android app)

Native background-GPS app for riders. The rider pairs **once** with a code sent
over WhatsApp, then the app streams location in the background (even when the
screen is off) so customers can track their delivery. Replaces the keep-a-web-
page-open approach.

- **Stack:** Expo (React Native) + `expo-location` background task.
- **Auth:** one-time pairing code → long-lived device token (stored on device).
- **Backend:** posts to this repo's `/api/v1/rider-app/*` endpoints.

## How it fits the backend

| App action | Backend |
|---|---|
| Enter pairing code | `POST /api/v1/rider-app/pair {code}` → `{device_token}` |
| Background GPS (every ~5s) | `POST /api/v1/rider-app/location` (Bearer device_token) |
| Show current delivery | `GET /api/v1/rider-app/me` (Bearer device_token) |

The first GPS fix after a pickup reveals the rider's stop (customer details +
Delivered button) and notifies the customer with their tracking link — same gate
as before, now driven by the app.

## One-time setup (you)

1. Install tooling: `npm i -g eas-cli` and create a free [Expo account](https://expo.dev).
2. In `rider-app/`: `npm install`, then `npx expo install` (aligns native dep versions).
3. Edit `app.json` → `expo.extra.apiBase` to your backend URL
   (default `https://restaurant-whatsapp-service.onrender.com`).
4. `eas login`, then `eas init` (fills `expo.extra.eas.projectId`).

## Build the APK

```bash
cd rider-app
eas build -p android --profile preview     # cloud build → APK download link
```

When it finishes, EAS prints a public **APK download URL**. (Local alternative:
`npx expo run:android` on a machine with Android SDK, or `eas build --local`.)

## Distribute + onboard a rider

1. Host the APK (the EAS download link works) and set it on the backend:
   `APP_RIDER_APP_APK_URL=<apk url>`.
2. In the dashboard (or via API) trigger:
   `POST /api/v1/riders/{rider_id}/app-invite` — this WhatsApps the rider a
   6-char code (valid 60 min) + the install link.
3. Rider: install the APK → open the app → enter the code → tap **Pair device**.
4. Android asks for location — the rider must choose **Allow all the time** (the
   app explains why). Done — it now tracks every delivery automatically.

## Notes

- **Android only** (sideloaded APK). iOS would need an Apple Developer account +
  TestFlight and a separate build profile.
- **"Allow all the time"** is required for background tracking; "While using the
  app" only tracks with the screen on.
- Battery: a persistent "Live tracking active" notification is shown while
  tracking (Android foreground-service requirement) — this is expected.
- The device token never expires; "Unpair this device" in the app clears it.
- DB columns (`riders.device_token`, `pairing_code`, `pairing_code_expires_at`)
  are added by Alembic migration `d5e6f7a8b9c0`, which auto-applies on deploy
  (the Dockerfile runs `alembic upgrade head`).
