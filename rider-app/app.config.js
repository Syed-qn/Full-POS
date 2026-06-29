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

  const plugins = [...(config.plugins || [])];
  const hasMapsPlugin = plugins.some(
    (p) => p === "react-native-maps" || (Array.isArray(p) && p[0] === "react-native-maps"),
  );
  if (!hasMapsPlugin) {
    plugins.push([
      "react-native-maps",
      {
        androidGoogleMapsApiKey: mapsKey,
      },
    ]);
  }

  return {
    ...config,
    plugins,
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