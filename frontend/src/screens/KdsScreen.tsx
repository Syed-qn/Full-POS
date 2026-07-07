import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { bumpItem, fetchStationTickets, type KdsTicketItem } from "../lib/kdsApi";

export function KdsScreen() {
  const { stationId } = useParams<{ stationId: string }>();
  const [items, setItems] = useState<KdsTicketItem[]>([]);

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
      {items.map((item) => (
        <div key={item.id}>
          <span>
            {item.qty}x {item.dish_name}
            {item.variant_name ? ` (${item.variant_name})` : ""}
          </span>
          <button type="button" onClick={() => handleBump(item.id)}>
            Bump
          </button>
        </div>
      ))}
    </div>
  );
}
