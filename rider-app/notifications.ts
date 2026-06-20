import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { registerPushToken } from "./api";

// Show assignment pushes as a heads-up banner even with the app foregrounded.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * Register for push notifications and send the Expo token to the backend so the
 * server can wake this rider when a delivery is assigned. Best-effort: returns
 * silently on simulators / denied permission / network error — pushes are a
 * convenience, the app still works via polling.
 */
export async function registerForPush(deviceToken: string): Promise<void> {
  try {
    if (!Device.isDevice) return; // push tokens aren't issued on emulators

    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("deliveries", {
        name: "Deliveries",
        importance: Notifications.AndroidImportance.HIGH,
        vibrationPattern: [0, 250, 250, 250],
      });
    }

    const existing = await Notifications.getPermissionsAsync();
    let status = existing.status;
    if (status !== "granted") {
      status = (await Notifications.requestPermissionsAsync()).status;
    }
    if (status !== "granted") return;

    const projectId =
      Constants.expoConfig?.extra?.eas?.projectId ??
      Constants.easConfig?.projectId;
    const expoToken = (
      await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined)
    ).data;
    if (expoToken) await registerPushToken(deviceToken, expoToken);
  } catch {
    // Best-effort — never block the app on push registration.
  }
}

/** Subscribe to notification taps. Returns an unsubscribe fn. */
export function onNotificationTap(handler: () => void): () => void {
  const sub = Notifications.addNotificationResponseReceivedListener(() => handler());
  return () => sub.remove();
}
