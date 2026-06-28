// Dynamic Expo config: keeps everything in app.json, but lets EAS Build / local env
// supply secrets instead of committing them:
//   - GOOGLE_SERVICES_JSON     → google-services.json path (SECRET file env var on EAS).
//   - APP_MAPS_SDK_ANDROID     → Android Google Maps SDK key. Local builds read it from
//                                rider-app/.env; EAS builds from the EAS env var of the
//                                same name. Unset → app.json fallback (placeholder = blank map).
module.exports = ({ config }) => ({
  ...config,
  android: {
    ...config.android,
    googleServicesFile:
      process.env.GOOGLE_SERVICES_JSON || config.android.googleServicesFile,
    config: {
      ...config.android?.config,
      googleMaps: {
        ...config.android?.config?.googleMaps,
        apiKey:
          process.env.APP_MAPS_SDK_ANDROID ||
          config.android?.config?.googleMaps?.apiKey ||
          "",
      },
    },
  },
});
