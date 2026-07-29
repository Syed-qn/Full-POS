/** Tell a manager when another branch is waiting on them.
 *
 * The Transfers tab already carries a count, but that only helps somebody
 * already looking at Inventory. A request nobody answers is the other branch
 * standing still, and a delivery nobody confirms is stock sitting in NEITHER
 * branch's count — both need to reach you wherever you are in the app.
 *
 * Alerts once per transfer, ever. The seen ids are persisted, so a reload, a
 * live event or five screen changes do not replay the same request at you —
 * that is the fastest way to teach somebody to ignore alerts entirely.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { AlertItem } from "../components/AlertCenter";
import { toast } from "../components/Toaster";
import { listBranchTransfers } from "./branchTransfersApi";
import { subscribeLive } from "./liveEvents";
import { getSessionRole } from "./navAccess";
import type { BranchTransferOut } from "./types";

const SEEN_KEY = "pos.transfer_alerts_seen";
/** Enough that a busy week cannot cycle an id back into "unseen", small enough
 *  that the key never grows without bound. */
const MAX_SEEN = 200;

function readSeen(): number[] {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((n) => typeof n === "number") : [];
  } catch {
    return [];
  }
}

function writeSeen(ids: number[]): void {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(ids.slice(-MAX_SEEN)));
  } catch {
    /* private mode — alerts still work for this session, just not across reloads */
  }
}

/** Everything the logged-in branch itself has to act on. Direction is the
 *  direction the STOCK travels, so a PENDING row going "out" is another branch
 *  asking you for something. */
export function needsMyAction(transfers: BranchTransferOut[]): BranchTransferOut[] {
  return transfers.filter(
    (t) =>
      (t.status === "pending" && t.direction === "out") ||
      (t.status === "in_transit" && t.direction === "in"),
  );
}

export function alertLineFor(t: BranchTransferOut): string {
  const items = t.lines
    .map((line) => `${line.ingredient_name} ${line.qty_requested ?? line.quantity} ${line.unit}`)
    .join(", ");
  return t.status === "pending"
    ? `${t.to_branch_name} asked for ${items}`
    : `${items} on the way from ${t.from_branch_name}`;
}

export function useTransferAlerts(): AlertItem[] {
  // Owner and branch manager only. A cashier cannot reach the endpoint at all
  // — it would 403 — and running it on their terminal is pure noise.
  //
  // null is the OWNER: getSessionRole returns null for a manager/owner
  // restaurant token because that token carries no role claim. Gating on
  // "owner" alone would have excluded the one person who most needs this.
  const role = getSessionRole();
  const enabled = role === null || role === "owner" || role === "manager";

  const [items, setItems] = useState<AlertItem[]>([]);
  const seen = useRef<Set<number>>(new Set());

  const check = useCallback(async function check(): Promise<void> {
    try {
      const transfers = await listBranchTransfers();
      const waiting = needsMyAction(transfers);

      setItems(
        waiting.map((t) => ({
          id: `transfer-${t.id}`,
          level: t.status === "pending" ? "warning" : "info",
          title: alertLineFor(t),
          detail:
            t.status === "pending"
              ? "Waiting for your answer"
              : "Confirm what arrived to add it to your stock",
          href: "/inventory",
        })),
      );

      const fresh = waiting.filter((t) => !seen.current.has(t.id));
      if (fresh.length === 0) return;
      for (const t of fresh) seen.current.add(t.id);
      writeSeen([...seen.current]);

      // One toast for a batch. Five separate toasts for five requests is the
      // duplicate problem wearing a different hat.
      toast(
        fresh.length === 1
          ? `🔁 ${alertLineFor(fresh[0])}`
          : `🔁 ${fresh.length} branch transfers need you`,
      );
    } catch {
      // Single-site restaurant, a session that cannot read transfers, or a
      // network blip. Nothing to say — the next event tries again.
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setItems([]);
      return;
    }
    seen.current = new Set(readSeen());
    void check();
    // The server already announces "inventory changed" for both branches on
    // every transfer write, so there is nothing to poll.
    return subscribeLive((event) => {
      if (event.topic === "inventory") void check();
    });
  }, [enabled, check]);

  return items;
}
