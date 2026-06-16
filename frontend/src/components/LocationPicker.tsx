import { useEffect, useRef, useState } from "react";
import s from "./LocationPicker.module.css";

interface Props {
  lat: number;
  lng: number;
  /** Fired with rounded coords whenever the pin moves (search, drag, click, geolocate). */
  onChange: (lat: number, lng: number) => void;
}

interface Place {
  lat: number;
  lng: number;
  label: string;
}

// Dubai fallback when the restaurant has no usable coordinates yet.
const FALLBACK: [number, number] = [25.2048, 55.2708];
const NOMINATIM = "https://nominatim.openstreetmap.org";

const round6 = (n: number) => Math.round(n * 1e6) / 1e6;

const PIN_HTML =
  '<div style="width:18px;height:18px;border-radius:50% 50% 50% 0;' +
  "transform:rotate(-45deg);background:#33363b;border:2px solid #fff;" +
  'box-shadow:0 1px 4px rgba(0,0,0,0.45)"></div>';

async function searchPlaces(q: string): Promise<Place[]> {
  const r = await fetch(
    `${NOMINATIM}/search?format=jsonv2&limit=6&addressdetails=0&q=${encodeURIComponent(q)}`,
    { headers: { Accept: "application/json" } },
  );
  if (!r.ok) return [];
  const data = (await r.json()) as Array<{ lat: string; lon: string; display_name: string }>;
  return data.map((x) => ({ lat: parseFloat(x.lat), lng: parseFloat(x.lon), label: x.display_name }));
}

async function reverseGeocode(lat: number, lng: number): Promise<string | null> {
  const r = await fetch(
    `${NOMINATIM}/reverse?format=jsonv2&lat=${lat}&lon=${lng}`,
    { headers: { Accept: "application/json" } },
  );
  if (!r.ok) return null;
  const d = (await r.json()) as { display_name?: string };
  return d.display_name ?? null;
}

export function LocationPicker({ lat, lng, onChange }: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapObj = useRef<import("leaflet").Map | null>(null);
  const markerRef = useRef<import("leaflet").Marker | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [showResults, setShowResults] = useState(false);
  const [searching, setSearching] = useState(false);
  const [address, setAddress] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);

  // Initialise the map once.
  useEffect(() => {
    let cancelled = false;
    import("leaflet").then((L) => {
      if (cancelled || !mapRef.current || mapObj.current) return;
      const start: [number, number] = [
        Number.isFinite(lat) ? lat : FALLBACK[0],
        Number.isFinite(lng) ? lng : FALLBACK[1],
      ];
      const map = L.map(mapRef.current, { zoomControl: true }).setView(start, 15);
      mapObj.current = map;
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
      }).addTo(map);

      const icon = L.divIcon({ html: PIN_HTML, className: "", iconSize: [18, 18], iconAnchor: [4, 18] });
      const marker = L.marker(start, { draggable: true, icon }).addTo(map);
      markerRef.current = marker;

      marker.on("dragend", () => {
        const p = marker.getLatLng();
        onChangeRef.current(round6(p.lat), round6(p.lng));
      });
      map.on("click", (e: import("leaflet").LeafletMouseEvent) => {
        marker.setLatLng(e.latlng);
        onChangeRef.current(round6(e.latlng.lat), round6(e.latlng.lng));
      });

      setTimeout(() => map.invalidateSize(), 120);
    });
    return () => {
      cancelled = true;
      mapObj.current?.remove();
      mapObj.current = null;
      markerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the pin synced when lat/lng change from outside.
  useEffect(() => {
    if (!mapObj.current || !markerRef.current) return;
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    const cur = markerRef.current.getLatLng();
    if (Math.abs(cur.lat - lat) > 1e-6 || Math.abs(cur.lng - lng) > 1e-6) {
      markerRef.current.setLatLng([lat, lng]);
      mapObj.current.setView([lat, lng]);
    }
  }, [lat, lng]);

  // Reverse-geocode the current pin so the manager sees the real address.
  useEffect(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || (lat === 0 && lng === 0)) return;
    let cancelled = false;
    const t = setTimeout(() => {
      reverseGeocode(lat, lng)
        .then((a) => { if (!cancelled) setAddress(a); })
        .catch(() => { if (!cancelled) setAddress(null); });
    }, 500);
    return () => { cancelled = true; clearTimeout(t); };
  }, [lat, lng]);

  // Debounced address search.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) { setResults([]); return; }
    let cancelled = false;
    setSearching(true);
    const t = setTimeout(() => {
      searchPlaces(q)
        .then((r) => { if (!cancelled) { setResults(r); setShowResults(true); } })
        .catch(() => { if (!cancelled) setResults([]); })
        .finally(() => { if (!cancelled) setSearching(false); });
    }, 450);
    return () => { cancelled = true; clearTimeout(t); };
  }, [query]);

  function pick(place: Place) {
    setQuery(place.label);
    setShowResults(false);
    setAddress(place.label);
    onChangeRef.current(round6(place.lat), round6(place.lng));
  }

  function useMyLocation() {
    if (!navigator.geolocation) {
      setGeoError("Geolocation isn't available in this browser.");
      return;
    }
    setLocating(true);
    setGeoError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        onChangeRef.current(round6(pos.coords.latitude), round6(pos.coords.longitude));
      },
      () => {
        setLocating(false);
        setGeoError("Couldn't get your location — allow access or set the pin manually.");
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  return (
    <div className={s.wrap}>
      <div className={s.searchWrap}>
        <input
          className={s.search}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length && setShowResults(true)}
          placeholder="Search an address or place… (e.g. Al Karama, Dubai)"
        />
        {searching && <span className={s.spinner}>…</span>}
        {showResults && results.length > 0 && (
          <ul className={s.results}>
            {results.map((r, i) => (
              <li key={i} className={s.resultItem} onMouseDown={() => pick(r)}>
                {r.label}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div ref={mapRef} className={s.map} />

      <div className={s.controls}>
        <button type="button" className={s.locBtn} onClick={useMyLocation} disabled={locating}>
          {locating ? "Locating…" : "📍 Use my current location"}
        </button>
        <span className={s.tip}>Search, drag the pin, or click the map.</span>
      </div>

      {address && (
        <div className={s.address}>
          <span className={s.addrIcon}>📌</span>
          <span className={s.addrText}>{address}</span>
        </div>
      )}
      {geoError && <span className={s.error}>{geoError}</span>}
    </div>
  );
}
