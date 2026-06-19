import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";

/**
 * Background location task. MUST be defined at module top level (registered
 * before React renders) so Android can resume it when the app is backgrounded.
 * It runs in its own JS context, so it reads the device token + API base itself.
 */
export const LOCATION_TASK = "rider-location-task";
export const TOKEN_KEY = "deviceToken";

const API_BASE = (Constants.expoConfig?.extra?.apiBase as string) ?? "";

TaskManager.defineTask(LOCATION_TASK, async ({ data, error }) => {
  if (error) return;
  const { locations } = (data ?? {}) as { locations?: Location.LocationObject[] };
  if (!locations?.length) return;
  const token = await AsyncStorage.getItem(TOKEN_KEY);
  if (!token) return;
  const loc = locations[locations.length - 1];
  try {
    await fetch(`${API_BASE}/api/v1/rider-app/location`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        latitude: loc.coords.latitude,
        longitude: loc.coords.longitude,
        accuracy: loc.coords.accuracy,
        speed: loc.coords.speed,
        heading: loc.coords.heading,
      }),
    });
  } catch {
    // Best-effort: a failed post is dropped; the next fix retries shortly.
  }
});

export async function startBackgroundTracking() {
  const fg = await Location.requestForegroundPermissionsAsync();
  if (fg.status !== "granted") throw new Error("Location permission denied");
  // Background permission ("Allow all the time") — required to track when the
  // screen is off / app backgrounded.
  await Location.requestBackgroundPermissionsAsync();

  const already = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK);
  if (already) return;

  await Location.startLocationUpdatesAsync(LOCATION_TASK, {
    accuracy: Location.Accuracy.High,
    timeInterval: 5000,
    distanceInterval: 10,
    pausesUpdatesAutomatically: false,
    showsBackgroundLocationIndicator: true,
    foregroundService: {
      notificationTitle: "Live tracking active",
      notificationBody: "Sharing your location so customers can track deliveries.",
    },
  });
}

export async function stopBackgroundTracking() {
  const running = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK);
  if (running) await Location.stopLocationUpdatesAsync(LOCATION_TASK);
}
