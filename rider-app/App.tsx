import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
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
  mapsLink,
  markDelivered,
  pickup,
  type Run,
  type Stop,
} from "./api";
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
        <ActivityIndicator size="large" />
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
      <Text style={styles.title}>Rider Tracker</Text>
      <Text style={styles.subtitle}>Enter the pairing code from your WhatsApp.</Text>
      <TextInput
        style={styles.input}
        value={code}
        onChangeText={setCode}
        placeholder="e.g. AB3K9P"
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={12}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        style={[styles.button, (busy || code.length < 4) && styles.buttonDisabled]}
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

  const loadRun = useCallback(async () => {
    try {
      setRun(await getOrders(token));
    } catch {
      /* keep last */
    }
  }, [token]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await startBackgroundTracking();
        if (alive) setStatus("Live — sharing location");
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

  return (
    <View style={styles.screen}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Deliveries</Text>
        <View style={styles.statusPill}>
          <Text style={styles.statusPillText}>{status}</Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.list}>
        {!hasRun ? (
          <Text style={styles.subtitle}>
            No active delivery — keep the app running, you'll be notified when one
            is assigned.
          </Text>
        ) : !pickedUp ? (
          <View style={styles.card}>
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
              style={[styles.button, busy && styles.buttonDisabled]}
              disabled={busy}
              onPress={doPickup}
            >
              <Text style={styles.buttonText}>{busy ? "…" : "Picked up — start run"}</Text>
            </Pressable>
          </View>
        ) : pending.length === 0 ? (
          <Text style={styles.subtitle}>All delivered. Head back to the restaurant.</Text>
        ) : (
          pending.map((s, i) => (
            <View key={s.orderId} style={[styles.card, i === 0 && styles.cardActive]}>
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

              {s.customerPhone ? (
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
                {s.latitude != null && s.longitude != null ? (
                  <Pressable
                    style={[styles.button, styles.buttonAlt]}
                    onPress={() => Linking.openURL(mapsLink(s.latitude!, s.longitude!))}
                  >
                    <Text style={styles.buttonAltText}>Navigate</Text>
                  </Pressable>
                ) : null}
                {i === 0 ? (
                  <Pressable
                    style={[styles.button, busy && styles.buttonDisabled]}
                    disabled={busy}
                    onPress={() => doDelivered(s)}
                  >
                    <Text style={styles.buttonText}>{busy ? "…" : "Collected & delivered"}</Text>
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

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#f8fafc", padding: 24, justifyContent: "space-between" },
  center: { flex: 1, justifyContent: "center", alignItems: "center", gap: 12 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  title: { fontSize: 26, fontWeight: "700", color: "#0f172a" },
  subtitle: { fontSize: 15, color: "#475569", textAlign: "center", marginTop: 24 },
  note: { fontSize: 13, color: "#64748b", textAlign: "center", marginTop: 8, paddingHorizontal: 12 },
  input: {
    width: "100%", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 12,
    padding: 16, fontSize: 22, textAlign: "center", letterSpacing: 4, backgroundColor: "#fff",
  },
  button: { flex: 1, backgroundColor: "#16a34a", borderRadius: 12, padding: 16, alignItems: "center", marginTop: 12 },
  buttonAlt: { backgroundColor: "#e2e8f0" },
  buttonAltText: { color: "#0f172a", fontSize: 16, fontWeight: "600" },
  buttonDisabled: { backgroundColor: "#94a3b8" },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
  error: { color: "#b91c1c" },
  statusPill: { backgroundColor: "#dcfce7", paddingHorizontal: 14, paddingVertical: 6, borderRadius: 999 },
  statusPillText: { color: "#166534", fontWeight: "600", fontSize: 12 },
  linkButton: { alignItems: "center", padding: 12 },
  linkButtonText: { color: "#64748b" },
  list: { gap: 12, paddingBottom: 12 },
  card: { backgroundColor: "#fff", borderRadius: 16, padding: 16, borderWidth: 1, borderColor: "#e2e8f0" },
  cardActive: { borderColor: "#16a34a", backgroundColor: "#f6fef9" },
  stopHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8, gap: 8 },
  cardTitle: { fontSize: 16, fontWeight: "700", color: "#0f172a" },
  seqPill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  seqPillFirst: { backgroundColor: "#16a34a" },
  seqPillLater: { backgroundColor: "#eef2f6" },
  seqPillFirstText: { color: "#fff", fontSize: 10.5, fontWeight: "800", letterSpacing: 0.5 },
  seqPillLaterText: { color: "#64748b", fontSize: 10.5, fontWeight: "700", letterSpacing: 0.5 },
  custName: { fontSize: 15, fontWeight: "600", color: "#0f172a", marginBottom: 2 },
  cardLine: { fontSize: 14, color: "#475569", marginTop: 2 },
  callRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: "#eff6ff", borderRadius: 10, paddingVertical: 9, paddingHorizontal: 12, marginTop: 10,
  },
  callText: { color: "#1d4ed8", fontSize: 14, fontWeight: "600" },
  callTag: { color: "#fff", backgroundColor: "#2563eb", fontSize: 10.5, fontWeight: "800", letterSpacing: 0.5, paddingHorizontal: 9, paddingVertical: 3, borderRadius: 999, overflow: "hidden" },
  codChip: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: "#fffbeb", borderWidth: 1, borderColor: "#fde68a",
    borderRadius: 10, paddingVertical: 9, paddingHorizontal: 12, marginTop: 10,
  },
  codLabel: { fontSize: 13, color: "#92400e", fontWeight: "600" },
  codAmount: { fontSize: 16, color: "#0f172a", fontWeight: "800" },
  cardHint: { fontSize: 12, color: "#94a3b8", marginTop: 8, fontStyle: "italic" },
  cardActions: { flexDirection: "row", gap: 10, marginTop: 12 },
});
