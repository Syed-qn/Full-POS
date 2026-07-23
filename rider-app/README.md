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
   (default `https://full-pos-production.up.railway.app`).

   `apiBase` is **baked into the APK at build time**. It must point at the same
   backend as the manager dashboard, because a pairing code only exists in that
   backend's database — pointing the app elsewhere makes every code come back
   "invalid or expired pairing code" even though the code is perfectly valid.
   Changing it requires a rebuild; there is no runtime override.
4. `eas login`, then `eas init` (fills `expo.extra.eas.projectId`).

## In-app map (not WhatsApp redirect)

The rider app shows a **built-in map** on the active stop (`MapPanel` — drop-off pin,
your live blue dot, distance badge, dashed line). You should **not** need to leave the
app for basic navigation.

**Why some riders still saw Google Maps:** (1) an old APK built before the in-app map,
(2) the Android **Maps SDK key** was missing at build time (blank/gray map), or (3) they
were still on the legacy **WhatsApp** rider flow (stop messages embed a Google Maps link).

### Maps SDK key (required for map tiles)

1. In [Google Cloud Console](https://console.cloud.google.com/), enable **Maps SDK for
   Android** on the same API key you use for the backend (or create a dedicated key).
2. For **EAS cloud builds**, set a project secret (do not commit the key):

   ```bash
   cd rider-app
   eas secret:create --scope project --name APP_MAPS_SDK_ANDROID --value "YOUR_KEY"
   ```

3. For **local builds**, copy `.env.example` → `.env` and set `APP_MAPS_SDK_ANDROID`.

`app.config.js` also accepts `APP_GOOGLE_MAPS_API_KEY` as a fallback env name.

After setting the key, **rebuild the APK** — OTA updates cannot inject native map keys.

Optional: **Turn-by-turn in Google Maps ↗** under the in-app map opens Google Maps for
voice navigation only; the primary view stays in-app.

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
