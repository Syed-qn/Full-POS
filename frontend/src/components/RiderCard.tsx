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

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function RiderCard({
  rider,
  onStatusChange,
  onDelete,
  onEdit,
  stale = false,
}: {
  rider: RiderOut;
  onStatusChange: (id: number, status: RiderStatus) => void;
  onDelete: (id: number) => void;
  onEdit?: (rider: RiderOut) => void;
  stale?: boolean;
}) {
  const offShift = rider.status === "off_shift";
  const deactivated = rider.status === "deactivated";
  const color = STATUS_COLOR[rider.status];

  return (
    <div data-testid="rider-card" className={`${s.card} ${stale ? s.stale : ""} ${deactivated ? s.dim : ""}`}>
      <div className={s.head}>
        <div
          className={`${s.profile} ${onEdit ? s.profileClickable : ""}`}
          onClick={onEdit ? () => onEdit(rider) : undefined}
          title={onEdit ? "Edit rider" : undefined}
        >
          <span className={s.avatar} style={{ background: color }}>{initials(rider.name)}</span>
          <div className={s.headText}>
            <span className={s.name}>
              {rider.name}
              {onEdit && <span className={s.editTag}>Edit</span>}
            </span>
            <span className={s.phone}>{rider.phone}</span>
          </div>
        </div>
        <span className={s.status} style={{ color, borderColor: color, background: `color-mix(in srgb, ${color} 10%, transparent)` }}>
          <span className={s.dot} style={{ background: color }} />
          {STATUS_LABEL[rider.status]}
        </span>
      </div>

      {stale && <span className={s.staleBadge}>Location stale</span>}

      <div className={s.locRow}>
        <span className={s.locDot} />
        Location: live tracking phase
      </div>

      <div className={s.actions}>
        {deactivated ? (
          <Button variant="ghost" onClick={() => onStatusChange(rider.id, "available")}>
            Reactivate
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={() => onStatusChange(rider.id, offShift ? "available" : "off_shift")}>
              {offShift ? "Start shift" : "End shift"}
            </Button>
            <Button variant="ghost" onClick={() => onStatusChange(rider.id, "deactivated")}>
              Deactivate
            </Button>
          </>
        )}
        <Button variant="danger" onClick={() => onDelete(rider.id)} className={s.removeBtn}>
          Remove
        </Button>
      </div>
    </div>
  );
}
