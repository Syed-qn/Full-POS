import { useEffect, useRef, useState } from "react";
import s from "./LocationPicker.module.css";

interface Props {
  lat: number;
  lng: number;
  /** Fired with rounded coords whenever the pin moves (search, drag, click, geolocate). */
  onChange: (lat: number, lng: number) => void;
  /** Extra class on the card root (e.g. to drop the max-width inside a dialog). */
  className?: string;
  /**
   * Commit each pin move immediately via onChange instead of staging it behind
   * the "Save location" confirm bar. Use inside a dialog that already has its own
   * Save button, so the pin isn't lost to a second, easily-missed confirm step.
   */
  instant?: boolean;
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

// A usable pin: finite and not the 0,0 "null island" the till passes when no
// location is set yet. Treating 0,0 as real centred the map on the ocean (blank
// tiles) instead of the Dubai fallback.
const isRealCoord = (la: number, ln: number) =>
  Number.isFinite(la) && Number.isFinite(ln) && !(la === 0 && ln === 0);

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

export async function reverseGeocode(lat: number, lng: number): Promise<string | null> {
  const r = await fetch(
    `${NOMINATIM}/reverse?format=jsonv2&lat=${lat}&lon=${lng}`,
    { headers: { Accept: "application/json" } },
  );
  if (!r.ok) return null;
  const d = (await r.json()) as { display_name?: string };
  return d.display_name ?? null;
}

export function LocationPicker({ lat, lng, onChange, className = "", instant = false }: Props) {
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
  // A moved/searched pin is staged here until the user confirms (Save) or
  // discards it (Cancel) — so a stray drag never silently changes the location.
  const [pending, setPending] = useState<{ lat: number; lng: number } | null>(null);

  // Stage a new pin position. In `instant` mode we commit straight away (the
  // host dialog owns the Save button); otherwise it waits for the confirm bar.
  function propose(la: number, ln: number) {
    const r = { lat: round6(la), lng: round6(ln) };
    markerRef.current?.setLatLng([r.lat, r.lng]);
    mapObj.current?.panTo([r.lat, r.lng]);
    if (instant) {
      onChangeRef.current(r.lat, r.lng);
      setPending(null);
    } else {
      setPending(r);
    }
  }
  const proposeRef = useRef(propose);
  proposeRef.current = propose;

  // Initialise the map once.
  useEffect(() => {
    let cancelled = false;
    import("leaflet").then((L) => {
      if (cancelled || !mapRef.current || mapObj.current) return;
      const start: [number, number] = isRealCoord(lat, lng)
        ? [lat, lng]
        : FALLBACK;
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
        proposeRef.current(p.lat, p.lng);
      });
      map.on("click", (e: import("leaflet").LeafletMouseEvent) => {
        proposeRef.current(e.latlng.lat, e.latlng.lng);
      });

      // A map mounted inside a dialog often initialises at 0×0 (the dialog is
      // still animating/laying out), so tiles for the real viewport never load
      // and it shows blank. Re-measure a few times as the layout settles.
      [120, 350, 700].forEach((t) => setTimeout(() => map.invalidateSize(), t));
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
    // Ignore the 0,0 "no pin" sentinel — snapping the marker to null island on
    // reset would strand it in the ocean.
    if (!isRealCoord(lat, lng)) return;
    const cur = markerRef.current.getLatLng();
    if (Math.abs(cur.lat - lat) > 1e-6 || Math.abs(cur.lng - lng) > 1e-6) {
      markerRef.current.setLatLng([lat, lng]);
      mapObj.current.setView([lat, lng]);
    }
  }, [lat, lng]);

  // The pin currently shown = the staged (pending) position if any, else the
  // committed prop coords.
  const activeLat = pending ? pending.lat : lat;
  const activeLng = pending ? pending.lng : lng;

  // Reverse-geocode the current pin so the manager sees the real address.
  useEffect(() => {
    if (!Number.isFinite(activeLat) || !Number.isFinite(activeLng) || (activeLat === 0 && activeLng === 0)) return;
    let cancelled = false;
    const t = setTimeout(() => {
      reverseGeocode(activeLat, activeLng)
        .then((a) => { if (!cancelled) setAddress(a); })
        .catch(() => { if (!cancelled) setAddress(null); });
    }, 500);
    return () => { cancelled = true; clearTimeout(t); };
  }, [activeLat, activeLng]);

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
    propose(place.lat, place.lng);
  }

  function saveLocation() {
    if (!pending) return;
    onChangeRef.current(pending.lat, pending.lng);
    setPending(null);
  }

  function cancelLocation() {
    if (!pending) return;
    // Snap the pin back to the last committed location.
    markerRef.current?.setLatLng([lat, lng]);
    mapObj.current?.panTo([lat, lng]);
    setPending(null);
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
        propose(pos.coords.latitude, pos.coords.longitude);
      },
      () => {
        setLocating(false);
        setGeoError("Couldn't get your location — allow access or set the pin manually.");
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  return (
    <div className={`${s.card} ${className}`.trim()}>
      <div className={s.searchWrap}>
        <span className={s.searchIcon} aria-hidden>🔍</span>
        <input
          className={s.search}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length && setShowResults(true)}
          placeholder="Search an address or place…"
        />
        {searching && <span className={s.spinner} />}
        {showResults && results.length > 0 && (
          <ul className={s.results}>
            {results.map((r, i) => (
              <li key={i} className={s.resultItem} onMouseDown={() => pick(r)}>
                <span className={s.resultPin} aria-hidden>📍</span>
                <span className={s.resultLabel}>{r.label}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={s.mapWrap}>
        <div ref={mapRef} className={s.map} />
        <button
          type="button"
          className={s.locBtn}
          onClick={useMyLocation}
          disabled={locating}
        >
          {locating ? "Locating…" : "📍 My location"}
        </button>
      </div>

      <div className={s.footer}>
        {address ? (
          <div className={s.address}>
            <span className={s.addrIcon} aria-hidden>📍</span>
            <div className={s.addrTextWrap}>
              <span className={s.addrLabel}>{pending ? "New location" : "Selected location"}</span>
              <span className={s.addrText}>{address}</span>
            </div>
          </div>
        ) : (
          <span className={s.tip}>Search, drag the pin, or click the map to set your location.</span>
        )}

        {pending && (
          <div className={s.confirmBar}>
            <span className={s.pendingNote}>Pin moved — save to apply.</span>
            <div className={s.confirmBtns}>
              <button type="button" className={s.cancelBtn} onClick={cancelLocation}>
                Cancel
              </button>
              <button type="button" className={s.saveBtn} onClick={saveLocation}>
                Save location
              </button>
            </div>
          </div>
        )}
        {geoError && <span className={s.error}>{geoError}</span>}
      </div>
    </div>
  );
}
