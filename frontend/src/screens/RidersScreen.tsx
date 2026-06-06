import { useEffect, useState } from "react";
import { RiderCard } from "../components/RiderCard";
import { fetchRiders, setRiderStatus } from "../lib/ridersApi";
import type { RiderOut, RiderStatus } from "../lib/types";
import s from "./RidersScreen.module.css";

export function RidersScreen() {
  const [riders, setRiders] = useState<RiderOut[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetchRiders()
      .then(setRiders)
      .finally(() => setLoaded(true));
  }, []);

  async function onStatusChange(id: number, status: RiderStatus) {
    const updated = await setRiderStatus(id, status);
    setRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  if (loaded && riders.length === 0) {
    return <div className={s.empty}>No riders yet — register your first rider.</div>;
  }

  return (
    <div className={s.grid}>
      {riders.map((r) => (
        <RiderCard key={r.id} rider={r} onStatusChange={onStatusChange} />
      ))}
    </div>
  );
}
