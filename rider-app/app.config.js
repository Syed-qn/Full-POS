// Dynamic Expo config: keeps everything in app.json, but lets EAS Build supply
// google-services.json via a SECRET file env var (GOOGLE_SERVICES_JSON) instead
// of committing it. Locally (where ./google-services.json exists) the app.json
// value is used; on EAS the env var path overrides it.
module.exports = ({ config }) => ({
  ...config,
  android: {
    ...config.android,
    googleServicesFile:
      process.env.GOOGLE_SERVICES_JSON || config.android.googleServicesFile,
  },
});
