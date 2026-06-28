import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import * as Location from "expo-location";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  getOrders,
  markDelivered,
  pickup,
  setDuty,
  type Run,
  type Stop,
} from "./api";
import MapPanel from "./MapPanel";
import { onNotificationTap, registerForPush } from "./notifications";
import {
  sendCurrentLocation,
  startBackgroundTracking,
  stopBackgroundTracking,
  TOKEN_KEY,
} from "./tasks";

const API_BASE = (Constants.expoConfig?.extra?.apiBase as string) ?? "";

export default function App() {
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    AsyncStorage.getItem(TOKEN_KEY).then((t) => {
      setToken(t);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return (
      <View style={[styles.screen, styles.center]}>
        <ActivityIndicator size="large" color={C.green} />
      </View>
    );
  }
  return token ? (
    <TrackingScreen
      token={token}
      onUnpair={async () => {
        await stopBackgroundTracking();
        await AsyncStorage.removeItem(TOKEN_KEY);
        setToken(null);
      }}
    />
  ) : (
    <PairingScreen onPaired={setToken} />
  );
}

function PairingScreen({ onPaired }: { onPaired: (t: string) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pair = async () => {
    setBusy(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}/api/v1/rider-app/pair`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code.trim().toUpperCase() }),
      });
      if (!resp.ok) throw new Error("Invalid or expired code");
      const data = await resp.json();
      await AsyncStorage.setItem(TOKEN_KEY, data.device_token);
      onPaired(data.device_token);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pairing failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={[styles.screen, styles.center]}>
      <View style={styles.logoBadge}>
        <Text style={styles.logoEmoji}>🛵</Text>
      </View>
      <Text style={styles.title}>Rider Tracker</Text>
      <Text style={styles.subtitle}>Enter the pairing code from your WhatsApp.</Text>
      <TextInput
        style={styles.input}
        value={code}
        onChangeText={setCode}
        placeholder="AB3K9P"
        placeholderTextColor={C.dim}
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={12}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        style={({ pressed }) => [
          styles.button,
          styles.buttonWide,
          pressed && styles.buttonPressed,
          (busy || code.length < 4) && styles.buttonDisabled,
        ]}
        disabled={busy || code.length < 4}
        onPress={pair}
      >
        <Text style={styles.buttonText}>{busy ? "Pairing…" : "Pair device"}</Text>
      </Pressable>
    </View>
  );
}

function TrackingScreen({
  token,
  onUnpair,
}: {
  token: string;
  onUnpair: () => void;
}) {
  const [status, setStatus] = useState("Starting…");
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [onDuty, setOnDuty] = useState(true);
  const [dutyBusy, setDutyBusy] = useState(false);
  const [riderPos, setRiderPos] = useState<{ lat: number; lng: number } | null>(null);

  // Watch the rider's own position (foreground) so the in-app map can draw the line
  // to the drop-off and keep both in view. Permission is already granted for tracking.
  useEffect(() => {
    let sub: Location.LocationSubscription | null = null;
    (async () => {
      try {
        const { status: perm } = await Location.getForegroundPermissionsAsync();
        if (perm !== "granted") return;
        sub = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.High, distanceInterval: 25, timeInterval: 5000 },
          (loc) => setRiderPos({ lat: loc.coords.latitude, lng: loc.coords.longitude }),
        );
      } catch {
        /* map just shows the drop-off without the live line */
      }
    })();
    return () => sub?.remove();
  }, []);

  const loadRun = useCallback(async () => {
    try {
      const r = await getOrders(token);
      setRun(r);
      // Keep the switch in sync with the server (e.g. another device / a manager),
      // but never clobber an in-flight toggle the rider is mid-press on.
      if (!dutyBusy) setOnDuty(r.onDuty);
    } catch {
      /* keep last */
    }
  }, [token, dutyBusy]);

  const toggleDuty = async () => {
    const next = !onDuty;
    setDutyBusy(true);
    setOnDuty(next); // optimistic
    try {
      const res = await setDuty(token, next);
      setOnDuty(res.onDuty);
    } catch (e) {
      setOnDuty(!next); // revert on failure
      Alert.alert("Couldn't update", e instanceof Error ? e.message : "Try again");
    } finally {
      setDutyBusy(false);
    }
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await startBackgroundTracking();
        if (alive) setStatus("Live, sharing location");
      } catch {
        if (alive) {
          setStatus("Location permission needed");
          Alert.alert(
            "Allow location",
            "Please allow location 'All the time' so deliveries can be tracked even when the screen is off.",
          );
        }
      }
      registerForPush(token);
    })();
    loadRun();
    const timer = setInterval(loadRun, 15000);
    const unsub = onNotificationTap(loadRun); // tap "New delivery" → refresh
    return () => {
      alive = false;
      clearInterval(timer);
      unsub();
    };
  }, [loadRun, token]);

  const doPickup = async () => {
    setBusy(true);
    try {
      setRun(await pickup(token));
      // NOTE: do NOT fire an explicit GPS ping here. The background task's first
      // ping (within a few seconds) reveals the customer's "on the way" + track
      // link exactly once. An extra ping here races with the background one — both
      // get treated as the "first ping" and the customer notification is delivered
      // twice.
    } catch (e) {
      Alert.alert("Pickup failed", e instanceof Error ? e.message : "Try again");
    } finally {
      setBusy(false);
    }
  };

  const doDelivered = async (stop: Stop) => {
    setBusy(true);
    try {
      // Push a fresh GPS fix first so the server's live-tracking check passes even
      // if Android throttled background updates while the app was idle.
      await sendCurrentLocation();
      const res = await markDelivered(token, stop.orderId);
      // Optimistically drop this stop so it disappears instantly, then reconcile
      // with the server (handles batch-complete / a newly assigned next run).
      setRun((r) =>
        r
          ? { ...r, stops: r.stops.map((s) => (s.orderId === stop.orderId ? { ...s, delivered: true } : s)) }
          : r,
      );
      await loadRun();
      if (res.batchComplete) {
        Alert.alert("All delivered", "Head back to the restaurant.");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Try again";
      Alert.alert("Couldn't mark delivered", msg);
    } finally {
      setBusy(false);
    }
  };

  const pending = (run?.stops ?? []).filter((s) => !s.delivered);
  const hasRun = !!run?.batchId;
  const pickedUp = run?.status === "picked_up";
  const live = status.startsWith("Live");

  return (
    <View style={styles.screen}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Deliveries</Text>
        <View style={[styles.statusPill, live ? styles.statusPillLive : styles.statusPillWarn]}>
          <View style={[styles.statusDot, live ? styles.statusDotLive : styles.statusDotWarn]} />
          <Text style={[styles.statusPillText, live ? styles.statusTextLive : styles.statusTextWarn]}>
            {live ? "LIVE" : status}
          </Text>
        </View>
      </View>

      <Pressable
        style={[styles.dutyBar, onDuty ? styles.dutyBarOn : styles.dutyBarOff]}
        onPress={toggleDuty}
        disabled={dutyBusy}
      >
        <View style={styles.dutyLabelWrap}>
          <View style={[styles.dutyDot, onDuty ? styles.dutyDotOn : styles.dutyDotOff]} />
          <Text style={[styles.dutyLabel, onDuty ? styles.dutyLabelOn : styles.dutyLabelOff]}>
            {onDuty ? "ON DUTY" : "OFF DUTY"}
          </Text>
        </View>
        <View style={[styles.dutyTrack, onDuty ? styles.dutyTrackOn : styles.dutyTrackOff]}>
          <View style={[styles.dutyKnob, onDuty ? styles.dutyKnobOn : styles.dutyKnobOff]} />
        </View>
      </Pressable>
      {!onDuty ? (
        <Text style={styles.dutyHint}>
          You won't get new deliveries. Finish any active stops below.
        </Text>
      ) : null}

      <ScrollView contentContainerStyle={styles.list}>
        {!hasRun ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyEmoji}>{onDuty ? "🕒" : "🌙"}</Text>
            <Text style={styles.subtitle}>
              {onDuty
                ? "No deliveries right now. You'll be notified when one is assigned."
                : "You're off duty. Turn on duty above to start receiving deliveries."}
            </Text>
          </View>
        ) : !pickedUp ? (
          <View style={[styles.card, styles.cardActive]}>
            <Text style={styles.cardTitle}>
              {pending.length} {pending.length === 1 ? "order" : "orders"} ready to pick up
            </Text>
            {pending.map((s) => (
              <Text key={s.orderId} style={styles.cardLine}>
                • {s.orderNumber}
                {s.customerName ? ` · ${s.customerName}` : ""}
              </Text>
            ))}
            <Pressable
              style={({ pressed }) => [
                styles.button,
                styles.buttonWide,
                pressed && styles.buttonPressed,
                busy && styles.buttonDisabled,
              ]}
              disabled={busy}
              onPress={doPickup}
            >
              <Text style={styles.buttonText}>{busy ? "…" : "Picked up"}</Text>
            </Pressable>
          </View>
        ) : pending.length === 0 ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyEmoji}>✅</Text>
            <Text style={styles.subtitle}>All delivered. Head back to the restaurant.</Text>
          </View>
        ) : (
          pending.map((s, i) => (
            <View key={s.orderId} style={[styles.card, i === 0 ? styles.cardActive : styles.cardDim]}>
              <View style={styles.stopHead}>
                <Text style={styles.cardTitle}>{s.orderNumber}</Text>
                <View style={[styles.seqPill, i === 0 ? styles.seqPillFirst : styles.seqPillLater]}>
                  <Text style={i === 0 ? styles.seqPillFirstText : styles.seqPillLaterText}>
                    {i === 0 ? "DELIVER FIRST" : `LATER · ${i + 1}/${pending.length}`}
                  </Text>
                </View>
              </View>

              {s.customerName ? <Text style={styles.custName}>{s.customerName}</Text> : null}
              {s.address ? <Text style={styles.cardLine}>📍 {s.address}</Text> : null}

              {i === 0 && s.latitude != null && s.longitude != null ? (
                <MapPanel
                  destLat={s.latitude}
                  destLng={s.longitude}
                  riderLat={riderPos?.lat}
                  riderLng={riderPos?.lng}
                  label={s.customerName ?? s.orderNumber}
                />
              ) : null}

              {s.doNotCall ? (
                <View style={styles.noCallRow}>
                  <Text style={styles.noCallText}>🚫 Don't call, message only</Text>
                  {s.customerPhone ? (
                    <Text style={styles.noCallPhone}>{s.customerPhone}</Text>
                  ) : null}
                </View>
              ) : s.customerPhone ? (
                <Pressable
                  style={styles.callRow}
                  onPress={() => Linking.openURL(`tel:${s.customerPhone}`)}
                >
                  <Text style={styles.callText}>📞 {s.customerPhone}</Text>
                  <Text style={styles.callTag}>CALL</Text>
                </Pressable>
              ) : null}

              <View style={styles.codChip}>
                <Text style={styles.codLabel}>💵 Collect cash</Text>
                <Text style={styles.codAmount}>AED {s.codAmount.toFixed(2)}</Text>
              </View>

              {i === 0 ? null : (
                <Text style={styles.cardHint}>Deliver the stop above first.</Text>
              )}

              <View style={styles.cardActions}>
                {i === 0 ? (
                  <Pressable
                    style={({ pressed }) => [
                      styles.button,
                      styles.buttonFlex,
                      pressed && styles.buttonPressed,
                      busy && styles.buttonDisabled,
                    ]}
                    disabled={busy}
                    onPress={() => doDelivered(s)}
                  >
                    <Text style={styles.buttonText}>{busy ? "…" : "Delivered"}</Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
          ))
        )}
      </ScrollView>

      <Pressable style={styles.linkButton} onPress={onUnpair}>
        <Text style={styles.linkButtonText}>Unpair this device</Text>
      </Pressable>
    </View>
  );
}

// Dark "cockpit" palette — high-contrast for outdoor / sunlight use.
const C = {
  bg: "#0a0e14",
  card: "#161d29",
  cardDim: "#10151e",
  border: "#1f2937",
  green: "#22c55e",
  greenDark: "#16a34a",
  greenTintBg: "#0f2018",
  greenTintBorder: "#1f6f43",
  text: "#f1f5f9",
  sub: "#94a3b8",
  dim: "#5b6675",
};

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg, paddingHorizontal: 20, paddingTop: 56, paddingBottom: 16, justifyContent: "space-between" },
  center: { flex: 1, justifyContent: "center", alignItems: "center", gap: 14 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 14 },
  title: { fontSize: 30, fontWeight: "800", color: C.text, letterSpacing: -0.5 },
  subtitle: { fontSize: 15, color: C.sub, textAlign: "center", lineHeight: 22 },

  logoBadge: {
    width: 84, height: 84, borderRadius: 24, backgroundColor: C.greenTintBg,
    borderWidth: 1, borderColor: C.greenTintBorder, alignItems: "center", justifyContent: "center", marginBottom: 6,
  },
  logoEmoji: { fontSize: 40 },

  input: {
    width: "100%", borderWidth: 1.5, borderColor: C.border, borderRadius: 14,
    paddingVertical: 18, paddingHorizontal: 16, fontSize: 26, fontWeight: "700",
    textAlign: "center", letterSpacing: 8, color: C.text, backgroundColor: C.card, marginTop: 8,
  },

  // No flex here — a flex:1 button stretches to full height in a column layout
  // (esp. on react-native-web). Standalone buttons hug their content (buttonWide
  // gives width); the two side-by-side action buttons opt into flex via buttonFlex.
  button: { backgroundColor: C.green, borderRadius: 14, paddingVertical: 18, alignItems: "center", marginTop: 14 },
  buttonWide: { width: "100%" },
  buttonFlex: { flex: 1 },
  buttonPressed: { backgroundColor: C.greenDark },
  buttonAlt: { flex: 1, backgroundColor: "#1f2937" },
  buttonAltPressed: { backgroundColor: "#2a3647" },
  buttonAltText: { color: C.text, fontSize: 17, fontWeight: "700" },
  buttonDisabled: { backgroundColor: "#33404f" },
  buttonText: { color: "#04130a", fontSize: 17, fontWeight: "800" },
  error: { color: "#f87171", fontWeight: "600" },

  statusPill: { flexDirection: "row", alignItems: "center", gap: 7, paddingHorizontal: 13, paddingVertical: 7, borderRadius: 999, borderWidth: 1 },
  statusPillLive: { backgroundColor: C.greenTintBg, borderColor: C.greenTintBorder },
  statusPillWarn: { backgroundColor: "#241a0c", borderColor: "#6b4f1d" },
  statusDot: { width: 8, height: 8, borderRadius: 999 },
  statusDotLive: { backgroundColor: C.green },
  statusDotWarn: { backgroundColor: "#f59e0b" },
  statusPillText: { fontWeight: "800", fontSize: 12, letterSpacing: 0.8 },
  statusTextLive: { color: "#4ade80" },
  statusTextWarn: { color: "#fbbf24" },

  dutyBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderRadius: 14, borderWidth: 1, paddingVertical: 12, paddingHorizontal: 16, marginBottom: 4,
  },
  dutyBarOn: { backgroundColor: C.greenTintBg, borderColor: C.greenTintBorder },
  dutyBarOff: { backgroundColor: "#241a0c", borderColor: "#6b4f1d" },
  dutyLabelWrap: { flexDirection: "row", alignItems: "center", gap: 9 },
  dutyDot: { width: 9, height: 9, borderRadius: 999 },
  dutyDotOn: { backgroundColor: C.green },
  dutyDotOff: { backgroundColor: "#f59e0b" },
  dutyLabel: { fontSize: 14, fontWeight: "900", letterSpacing: 1 },
  dutyLabelOn: { color: "#4ade80" },
  dutyLabelOff: { color: "#fbbf24" },
  dutyTrack: { width: 50, height: 28, borderRadius: 999, padding: 3, justifyContent: "center" },
  dutyTrackOn: { backgroundColor: C.greenDark, alignItems: "flex-end" },
  dutyTrackOff: { backgroundColor: "#3a2f17", alignItems: "flex-start" },
  dutyKnob: { width: 22, height: 22, borderRadius: 999 },
  dutyKnobOn: { backgroundColor: "#eafff2" },
  dutyKnobOff: { backgroundColor: "#fbbf24" },
  dutyHint: { fontSize: 13, color: "#fbbf24", marginBottom: 10, marginTop: 2, fontWeight: "600" },

  linkButton: { alignItems: "center", paddingVertical: 14 },
  linkButtonText: { color: C.dim, fontSize: 14, fontWeight: "600" },

  list: { gap: 14, paddingBottom: 12 },
  emptyCard: { alignItems: "center", gap: 10, paddingVertical: 48, paddingHorizontal: 16 },
  emptyEmoji: { fontSize: 44 },

  card: { backgroundColor: C.card, borderRadius: 20, padding: 18, borderWidth: 1, borderColor: C.border },
  cardActive: { borderColor: C.greenTintBorder, backgroundColor: "#101b16" },
  cardDim: { opacity: 0.7 },
  stopHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10, gap: 8 },
  cardTitle: { fontSize: 19, fontWeight: "800", color: C.text },
  cardLine: { fontSize: 15, color: C.sub, marginTop: 4, lineHeight: 21 },

  seqPill: { borderRadius: 999, paddingHorizontal: 11, paddingVertical: 5 },
  seqPillFirst: { backgroundColor: C.green },
  seqPillLater: { backgroundColor: "#1f2937" },
  seqPillFirstText: { color: "#04130a", fontSize: 11, fontWeight: "900", letterSpacing: 0.6 },
  seqPillLaterText: { color: C.sub, fontSize: 11, fontWeight: "800", letterSpacing: 0.6 },

  custName: { fontSize: 17, fontWeight: "700", color: C.text, marginBottom: 2 },

  callRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: "#11243f", borderWidth: 1, borderColor: "#1e3a5f",
    borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14, marginTop: 12,
  },
  callText: { color: "#7dd3fc", fontSize: 15, fontWeight: "700" },
  callTag: { color: "#04130a", backgroundColor: "#38bdf8", fontSize: 11, fontWeight: "900", letterSpacing: 0.6, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, overflow: "hidden" },

  noCallRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: "#2a1414", borderColor: "#5b2121", borderWidth: 1,
    borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14, marginTop: 12,
  },
  noCallText: { color: "#fca5a5", fontSize: 14, fontWeight: "800" },
  noCallPhone: { color: "#7f8896", fontSize: 13, fontWeight: "600" },

  codChip: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: "#241d09", borderWidth: 1, borderColor: "#5b4a13",
    borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14, marginTop: 12,
  },
  codLabel: { fontSize: 14, color: "#fcd34d", fontWeight: "700" },
  codAmount: { fontSize: 19, color: C.text, fontWeight: "900" },

  cardHint: { fontSize: 13, color: C.dim, marginTop: 10, fontStyle: "italic" },
  cardActions: { flexDirection: "row", gap: 12, marginTop: 14 },
});
