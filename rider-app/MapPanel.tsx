import Constants from "expo-constants";
import { useEffect, useRef } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import MapView, { Marker, Polyline, PROVIDER_GOOGLE } from "react-native-maps";

type Props = {
  destLat: number;
  destLng: number;
  riderLat?: number | null;
  riderLng?: number | null;
  label?: string | null;
  height?: number;
};

// Straight-line (great-circle) distance in km — just for the "x.x km away" badge.
function haversineKm(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const R = 6371;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLng = ((bLng - aLng) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((aLat * Math.PI) / 180) *
      Math.cos((bLat * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(s), Math.sqrt(1 - s));
}

function fmtKm(km: number): string {
  if (km < 1) return `${Math.round(km * 1000)} m`;
  return `${km.toFixed(1)} km`;
}

const mapsConfigured =
  (Constants.expoConfig?.extra?.mapsConfigured as boolean | undefined) ?? false;

// Native in-app map (react-native-maps) — riders see drop-off + live position here.
// Turn-by-turn stays optional in App.tsx; this panel is the primary navigation view.
export default function MapPanel({
  destLat,
  destLng,
  riderLat,
  riderLng,
  label,
  height = 280,
}: Props) {
  const ref = useRef<MapView>(null);
  const hasRider = riderLat != null && riderLng != null;
  const distKm = hasRider
    ? haversineKm(riderLat as number, riderLng as number, destLat, destLng)
    : null;

  const fit = () => {
    if (!hasRider) {
      ref.current?.animateToRegion(
        { latitude: destLat, longitude: destLng, latitudeDelta: 0.01, longitudeDelta: 0.01 },
        400,
      );
      return;
    }
    ref.current?.fitToCoordinates(
      [
        { latitude: destLat, longitude: destLng },
        { latitude: riderLat as number, longitude: riderLng as number },
      ],
      { edgePadding: { top: 60, right: 50, bottom: 60, left: 50 }, animated: true },
    );
  };

  // Keep both the rider and the drop-off in view as the rider moves.
  useEffect(fit, [destLat, destLng, riderLat, riderLng, hasRider]);

  return (
    <View style={[styles.wrap, { height }]}>
      <MapView
        ref={ref}
        provider={mapsConfigured ? PROVIDER_GOOGLE : undefined}
        style={styles.map}
        initialRegion={{
          latitude: destLat,
          longitude: destLng,
          latitudeDelta: 0.01,
          longitudeDelta: 0.01,
        }}
        showsUserLocation
        showsMyLocationButton={false}
        showsCompass
        toolbarEnabled={false}
        mapPadding={{ top: 44, right: 0, bottom: 0, left: 0 }}
      >
        <Marker
          coordinate={{ latitude: destLat, longitude: destLng }}
          title={label ?? "Drop-off"}
          description="Delivery location"
          pinColor="#ef4444"
        />
        {hasRider ? (
          <Polyline
            coordinates={[
              { latitude: riderLat as number, longitude: riderLng as number },
              { latitude: destLat, longitude: destLng },
            ]}
            strokeColor="#22c55e"
            strokeWidth={4}
            lineDashPattern={[10, 8]}
          />
        ) : null}
      </MapView>

      {!mapsConfigured ? (
        <View style={styles.warnBar} pointerEvents="none">
          <Text style={styles.warnText}>
            Map tiles need APP_MAPS_SDK_ANDROID on the APK build — rebuild with a Maps SDK key.
          </Text>
        </View>
      ) : null}

      {/* Top overlay: where we're going + how far. */}
      <View style={styles.topBar} pointerEvents="none">
        <View style={styles.destPill}>
          <Text style={styles.pin}>📍</Text>
          <Text style={styles.destText} numberOfLines={1}>
            {label ?? "Drop-off"}
          </Text>
        </View>
        {distKm != null ? (
          <View style={styles.distPill}>
            <Text style={styles.distText}>{fmtKm(distKm)}</Text>
          </View>
        ) : null}
      </View>

      {/* Recenter / fit-to-route button. */}
      <Pressable style={styles.recenter} onPress={fit} hitSlop={8} accessibilityLabel="Recenter map">
        <Text style={styles.recenterIcon}>◎</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: 16,
    overflow: "hidden",
    marginTop: 12,
    backgroundColor: "#0f1620",
    borderWidth: 1,
    borderColor: "#1f6f43",
  },
  map: { flex: 1 },

  warnBar: {
    position: "absolute",
    left: 10,
    right: 10,
    bottom: 10,
    backgroundColor: "rgba(120,53,15,0.92)",
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 10,
  },
  warnText: { color: "#fde68a", fontSize: 11, fontWeight: "700", textAlign: "center" },

  topBar: {
    position: "absolute",
    top: 10,
    left: 10,
    right: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  destPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flexShrink: 1,
    backgroundColor: "rgba(10,14,20,0.82)",
    borderRadius: 999,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  pin: { fontSize: 13 },
  destText: { color: "#f1f5f9", fontSize: 13, fontWeight: "800", flexShrink: 1 },
  distPill: {
    backgroundColor: "#16a34a",
    borderRadius: 999,
    paddingVertical: 6,
    paddingHorizontal: 11,
  },
  distText: { color: "#04130a", fontSize: 12, fontWeight: "900", letterSpacing: 0.3 },

  recenter: {
    position: "absolute",
    right: 12,
    bottom: 12,
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: "rgba(10,14,20,0.85)",
    borderWidth: 1,
    borderColor: "#1f6f43",
    alignItems: "center",
    justifyContent: "center",
  },
  recenterIcon: { color: "#22c55e", fontSize: 22, fontWeight: "700", marginTop: -1 },
});