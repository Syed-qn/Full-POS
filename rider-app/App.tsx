import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  startBackgroundTracking,
  stopBackgroundTracking,
  TOKEN_KEY,
} from "./tasks";

const API_BASE = (Constants.expoConfig?.extra?.apiBase as string) ?? "";

type Me = {
  riderName: string;
  activeOrderNumber: string | null;
  customerName: string | null;
  tracking: boolean;
};

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
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState("Starting…");

  const loadMe = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/rider-app/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) setMe(await resp.json());
    } catch {
      /* keep last */
    }
  }, [token]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await startBackgroundTracking();
        if (alive) setStatus("Live — tracking active");
      } catch (e) {
        if (alive) {
          setStatus("Location permission needed");
          Alert.alert(
            "Allow location",
            "Please allow location 'All the time' so deliveries can be tracked even when the screen is off.",
          );
        }
      }
    })();
    loadMe();
    const timer = setInterval(loadMe, 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [loadMe]);

  return (
    <View style={styles.screen}>
      <View style={styles.center}>
        <Text style={styles.title}>{me?.riderName ?? "Rider"}</Text>
        <View style={styles.statusPill}>
          <Text style={styles.statusPillText}>{status}</Text>
        </View>
        <Text style={styles.subtitle}>
          {me?.tracking
            ? `Delivering ${me.activeOrderNumber ?? ""}${me.customerName ? ` · ${me.customerName}` : ""}`
            : "No active delivery — keep the app running, it'll track your next one."}
        </Text>
        <Text style={styles.note}>
          Keep this app open or in the background during your shift. Tracking
          continues automatically for every delivery — no need to reopen.
        </Text>
      </View>
      <Pressable style={styles.linkButton} onPress={onUnpair}>
        <Text style={styles.linkButtonText}>Unpair this device</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#f8fafc", padding: 24, justifyContent: "space-between" },
  center: { flex: 1, justifyContent: "center", alignItems: "center", gap: 12 },
  title: { fontSize: 26, fontWeight: "700", color: "#0f172a" },
  subtitle: { fontSize: 15, color: "#475569", textAlign: "center" },
  note: { fontSize: 13, color: "#64748b", textAlign: "center", marginTop: 8, paddingHorizontal: 12 },
  input: {
    width: "100%", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 12,
    padding: 16, fontSize: 22, textAlign: "center", letterSpacing: 4, backgroundColor: "#fff",
  },
  button: { width: "100%", backgroundColor: "#16a34a", borderRadius: 12, padding: 16, alignItems: "center" },
  buttonDisabled: { backgroundColor: "#94a3b8" },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
  error: { color: "#b91c1c" },
  statusPill: { backgroundColor: "#dcfce7", paddingHorizontal: 14, paddingVertical: 6, borderRadius: 999 },
  statusPillText: { color: "#166534", fontWeight: "600" },
  linkButton: { alignItems: "center", padding: 12 },
  linkButtonText: { color: "#64748b" },
});
