import { useState } from "react";
import { Button } from "./Button";
import { RiderMapModal } from "./RiderMapModal";
import type { RiderOut, RiderStatus } from "../lib/types";
import s from "./RiderCard.module.css";

/** "2 min ago" style relative time from an ISO timestamp. */
function seenAgo(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "recently";
  const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

// A ping fresher than this means the rider is actively sharing live location.
const LIVE_MS = 3 * 60 * 1000;

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
  const [showMap, setShowMap] = useState(false);

  // Loose `!= null` so a backend that hasn't shipped these fields yet (value is
  // `undefined`, not `null`) reads as "no location" instead of rendering NaN.
  const hasLocation = rider.last_lat != null && rider.last_lng != null;
  const lastSeenMs = rider.last_location_at ? new Date(rider.last_location_at).getTime() : NaN;
  const isLive = !Number.isNaN(lastSeenMs) && Date.now() - lastSeenMs < LIVE_MS;

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
        <span
          className={s.locDot}
          style={isLive ? undefined : { background: "var(--text-muted)", boxShadow: "none" }}
        />
        <span className={s.locText}>
          {hasLocation
            ? isLive
              ? `Live · seen ${seenAgo(rider.last_location_at!)}`
              : `Last seen ${seenAgo(rider.last_location_at!)}`
            : "No location shared yet"}
        </span>
        {hasLocation && (
          <button type="button" className={s.viewMap} onClick={() => setShowMap(true)}>
            View on map
          </button>
        )}
      </div>

      <div className={s.deliveries}>
        <div className={s.deliveryStat}>
          <span className={s.deliveryNum}>{rider.delivered_24h}</span>
          <span className={s.deliveryLabel}>
            Today<span className={s.deliveryHint}>shift · 8am to 8am</span>
          </span>
        </div>
        <span className={s.deliveryDivider} />
        <div className={s.deliveryStat}>
          <span className={s.deliveryNum}>{rider.delivered_lifetime}</span>
          <span className={s.deliveryLabel}>
            Lifetime<span className={s.deliveryHint}>all time</span>
          </span>
        </div>
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

      {showMap && <RiderMapModal rider={rider} onClose={() => setShowMap(false)} />}
    </div>
  );
}
