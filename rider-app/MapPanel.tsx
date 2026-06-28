import { useEffect, useRef } from "react";
import { StyleSheet, View } from "react-native";
import MapView, { Marker, Polyline, PROVIDER_GOOGLE } from "react-native-maps";

type Props = {
  destLat: number;
  destLng: number;
  riderLat?: number | null;
  riderLng?: number | null;
  label?: string | null;
  height?: number;
};

// Native in-app map (react-native-maps) — no redirect to Google Maps. Shows the
// drop-off pin, the rider's live position (native blue dot), and a line to the stop.
export default function MapPanel({
  destLat,
  destLng,
  riderLat,
  riderLng,
  label,
  height = 230,
}: Props) {
  const ref = useRef<MapView>(null);
  const hasRider = riderLat != null && riderLng != null;

  // Keep both the rider and the drop-off in view as the rider moves.
  useEffect(() => {
    if (!hasRider) return;
    ref.current?.fitToCoordinates(
      [
        { latitude: destLat, longitude: destLng },
        { latitude: riderLat as number, longitude: riderLng as number },
      ],
      { edgePadding: { top: 55, right: 55, bottom: 55, left: 55 }, animated: true },
    );
  }, [destLat, destLng, riderLat, riderLng, hasRider]);

  return (
    <View style={[styles.wrap, { height }]}>
      <MapView
        ref={ref}
        provider={PROVIDER_GOOGLE}
        style={styles.map}
        initialRegion={{
          latitude: destLat,
          longitude: destLng,
          latitudeDelta: 0.02,
          longitudeDelta: 0.02,
        }}
        showsUserLocation
        showsMyLocationButton
        toolbarEnabled={false}
      >
        <Marker
          coordinate={{ latitude: destLat, longitude: destLng }}
          title={label ?? "Drop-off"}
          description="Delivery location"
          pinColor="red"
        />
        {hasRider ? (
          <Polyline
            coordinates={[
              { latitude: riderLat as number, longitude: riderLng as number },
              { latitude: destLat, longitude: destLng },
            ]}
            strokeColor="#1a7a3c"
            strokeWidth={4}
            lineDashPattern={[8, 8]}
          />
        ) : null}
      </MapView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: 12,
    overflow: "hidden",
    marginTop: 10,
    backgroundColor: "#e9eef2",
  },
  map: { flex: 1 },
});
