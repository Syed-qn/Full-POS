// Dynamic Expo config: keeps everything in app.json, but lets EAS Build / local env
// supply secrets instead of committing them:
//   - GOOGLE_SERVICES_JSON     → google-services.json path (SECRET file env var on EAS).
//   - APP_MAPS_SDK_ANDROID     → Android Google Maps SDK key (enable "Maps SDK for Android"
//                                on the key in Google Cloud). EAS secret or rider-app/.env.
//   - APP_GOOGLE_MAPS_API_KEY  → optional fallback (same GCP key often works if Maps SDK
//                                for Android is enabled on that key).
module.exports = ({ config }) => {
  const mapsKey =
    process.env.APP_MAPS_SDK_ANDROID ||
    process.env.APP_GOOGLE_MAPS_API_KEY ||
    config.android?.config?.googleMaps?.apiKey ||
    "";

  // NOTE: do NOT add "react-native-maps" to plugins. It ships no config plugin
  // (no app.plugin.js), so Expo falls back to requiring the package main —
  // lib/index.js, which is untranspiled JSX meant for Metro — and every config
  // read dies with `SyntaxError: Unexpected token '<'`, taking `eas build` with
  // it. The Android Maps key belongs in android.config.googleMaps.apiKey below,
  // which is the supported route and is all react-native-maps needs.

  return {
    ...config,
    android: {
      ...config.android,
      googleServicesFile:
        process.env.GOOGLE_SERVICES_JSON || config.android.googleServicesFile,
      config: {
        ...config.android?.config,
        googleMaps: {
          ...config.android?.config?.googleMaps,
          apiKey: mapsKey,
        },
      },
    },
    extra: {
      ...config.extra,
      mapsConfigured: Boolean(mapsKey),
    },
  };
};