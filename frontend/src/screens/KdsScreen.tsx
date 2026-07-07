import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { bumpItem, fetchStationTickets, ticketUrgency, type KdsTicketItem } from "../lib/kdsApi";

const URGENCY_COLOR: Record<string, string> = {
  ok: "transparent",
  warning: "#f59e0b",
  late: "#ef4444",
};

export function KdsScreen() {
  const { stationId } = useParams<{ stationId: string }>();
  const [items, setItems] = useState<KdsTicketItem[]>([]);
  const [, forceTick] = useState(0);

  // Urgency color depends on elapsed time, not just fetched data — re-render
  // periodically even when no new tickets have arrived.
  useEffect(() => {
    const tick = setInterval(() => forceTick((n) => n + 1), 30000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    if (!stationId) return;
    let cancelled = false;
    async function reload() {
      const rows = await fetchStationTickets(Number(stationId));
      if (!cancelled) setItems(rows);
    }
    reload();
    const interval = setInterval(reload, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [stationId]);

  async function handleBump(itemId: number) {
    await bumpItem(itemId);
    setItems((prev) => prev.filter((i) => i.id !== itemId));
  }

  return (
    <div>
      {items.map((item) => {
        const urgency = ticketUrgency(item.created_at);
        return (
          <div
            key={item.id}
            data-urgency={urgency}
            style={{ borderLeft: `4px solid ${URGENCY_COLOR[urgency]}`, paddingLeft: 8 }}
          >
            <span>
              {item.qty}x {item.dish_name}
              {item.variant_name ? ` (${item.variant_name})` : ""}
            </span>
            <button type="button" onClick={() => handleBump(item.id)}>
              Bump
            </button>
          </div>
        );
      })}
    </div>
  );
}
