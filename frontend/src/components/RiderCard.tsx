import { Button } from "./Button";
import type { RiderOut, RiderStatus } from "../lib/types";
import s from "./RiderCard.module.css";

const STATUS_LABEL: Record<RiderStatus, string> = {
  available: "Available",
  on_delivery: "On Delivery",
  off_shift: "Off Shift",
  deactivated: "Deactivated",
};

const STATUS_COLOR: Record<RiderStatus, string> = {
  available: "var(--sla-safe)",
  on_delivery: "var(--accent-rider)",
  off_shift: "var(--text-muted)",
  deactivated: "var(--sla-critical)",
};

export function RiderCard({
  rider,
  onStatusChange,
  stale = false,
}: {
  rider: RiderOut;
  onStatusChange: (id: number, status: RiderStatus) => void;
  stale?: boolean;
}) {
  const offShift = rider.status === "off_shift";
  return (
    <div data-testid="rider-card" className={`${s.card} ${stale ? s.stale : ""}`}>
      <div className={s.head}>
        <span className={s.name}>{rider.name}</span>
        <span className={s.status} style={{ color: STATUS_COLOR[rider.status] }}>
          ● {STATUS_LABEL[rider.status]}
        </span>
      </div>
      {stale && <span className={s.staleBadge}>Location stale</span>}
      <span className={s.loc}>Location: live tracking phase</span>
      <span className={s.stats}>On-time: — · Avg —</span>
      <div className={s.actions}>
        <Button variant="ghost" onClick={() => onStatusChange(rider.id, offShift ? "available" : "off_shift")}>
          {offShift ? "Start shift" : "End shift"}
        </Button>
        <Button variant="danger" onClick={() => onStatusChange(rider.id, "deactivated")}>
          Deactivate
        </Button>
      </div>
    </div>
  );
}
