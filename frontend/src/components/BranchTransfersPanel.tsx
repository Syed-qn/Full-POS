/** Stock moving between branches of the same restaurant, in two phases.
 *
 * Left: what is coming in and the one button that matters — confirm what
 * arrived. Right: send stock out. That order is deliberate; an incoming
 * delivery nobody accepts is stock that exists in no branch at all, so the
 * job with a deadline goes where the eye lands first.
 *
 * The panel is only rendered when this restaurant has sibling branches. A
 * single-site restaurant has nowhere to send to, and a tab that can only ever
 * say "no branches" is a tab that trains people to ignore the tab bar.
 */
import { useState } from "react";
import { Button } from "./Button";
import {
  cancelBranchTransfer,
  dispatchBranchTransfer,
  receiveBranchTransfer,
} from "../lib/branchTransfersApi";
import { toast } from "./Toaster";
import type { BranchTransferOut, IngredientOut, SiblingBranchOut } from "../lib/types";
import s from "../screens/InventoryScreen.module.css";
import p from "./BranchTransfersPanel.module.css";

const STATUS_LABEL: Record<string, string> = {
  in_transit: "on the way",
  completed: "done",
  cancelled: "cancelled",
  pending: "not sent yet",
};

function shortDate(iso: string | null): string {
  if (!iso) return "";
  // Server datetimes come back without a zone marker but are UTC; unmarked,
  // the browser reads them as local time and shifts the date by four hours.
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
}

function lineText(transfer: BranchTransferOut): string {
  return transfer.lines
    .map((line) => {
      const sent = `${line.quantity} ${line.unit}`;
      // Only worth spelling out both numbers when they differ — that gap is
      // the missing stock, and it is the whole reason the receiving branch
      // counts instead of clicking through.
      if (line.qty_received !== null && Number(line.qty_received) !== Number(line.quantity)) {
        return `${line.ingredient_name} ${line.qty_received} of ${sent}`;
      }
      return `${line.ingredient_name} ${sent}`;
    })
    .join(", ");
}

type Props = {
  transfers: BranchTransferOut[];
  branches: SiblingBranchOut[];
  ingredients: IngredientOut[];
  loaded: boolean;
  /** Refetch the screen. Both branches' stock figures have just changed. */
  onDone: () => void | Promise<void>;
};

export function BranchTransfersPanel({
  transfers,
  branches,
  ingredients,
  loaded,
  onDone,
}: Props) {
  const [toBranch, setToBranch] = useState<number | "">("");
  const [ingredientName, setIngredientName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  // Which incoming transfer is having its quantities corrected. Confirming in
  // full is one click; the short-delivery form only appears when asked for,
  // because most deliveries arrive complete.
  const [shortId, setShortId] = useState<number | null>(null);
  const [shortQty, setShortQty] = useState<Record<string, string>>({});

  const incoming = transfers.filter((t) => t.direction === "in" && t.status === "in_transit");
  const outgoing = transfers.filter((t) => t.direction === "out" && t.status === "in_transit");
  const history = transfers.filter((t) => t.status !== "in_transit");

  async function run(action: () => Promise<unknown>, done: string): Promise<void> {
    setBusy(true);
    try {
      await action();
      toast(done);
      await onDone();
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function send(): Promise<void> {
    if (toBranch === "" || !ingredientName || !quantity) return;
    const branch = branches.find((b) => b.id === toBranch);
    await run(
      () =>
        dispatchBranchTransfer({
          to_restaurant_id: Number(toBranch),
          lines: [{ ingredient_name: ingredientName, quantity }],
          note: note || null,
        }),
      `Sent ${quantity} of ${ingredientName} to ${branch?.name ?? "the other branch"}.`,
    );
    setIngredientName("");
    setQuantity("");
    setNote("");
  }

  async function confirmShort(transfer: BranchTransferOut): Promise<void> {
    const lines = transfer.lines
      .filter((line) => shortQty[line.ingredient_name] !== undefined)
      .map((line) => ({
        ingredient_name: line.ingredient_name,
        qty_received: shortQty[line.ingredient_name],
      }));
    await run(
      () => receiveBranchTransfer(transfer.id, lines),
      "Recorded. The shortfall is kept against this transfer.",
    );
    setShortId(null);
    setShortQty({});
  }

  return (
    <section className={s.panels}>
      <div className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h2>Arriving</h2>
            <span>Confirm what actually turned up. Only then is it your stock.</span>
          </div>
        </div>
        <div className={s.list}>
          {incoming.map((t) => (
            <div key={t.id} className={s.listItem}>
              <strong>
                From {t.from_branch_name}: {lineText(t)}
              </strong>
              <span>
                Sent {shortDate(t.created_at)}
                {t.note ? ` · ${t.note}` : ""}
              </span>
              {shortId === t.id ? (
                <div className={p.shortForm}>
                  {t.lines.map((line) => (
                    <label key={line.ingredient_name} className={p.shortRow}>
                      <span>
                        {line.ingredient_name} — sent {line.quantity} {line.unit}
                      </span>
                      <input
                        type="number"
                        min="0"
                        step="0.001"
                        inputMode="decimal"
                        placeholder={String(line.quantity)}
                        aria-label={`${line.ingredient_name} received`}
                        value={shortQty[line.ingredient_name] ?? ""}
                        onChange={(e) =>
                          setShortQty((prev) => ({
                            ...prev,
                            [line.ingredient_name]: e.target.value,
                          }))
                        }
                      />
                    </label>
                  ))}
                  <div className={p.shortActions}>
                    <Button size="md" type="button" disabled={busy} onClick={() => void confirmShort(t)}>
                      Save what arrived
                    </Button>
                    <Button
                      size="md"
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        setShortId(null);
                        setShortQty({});
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div className={s.rowActions}>
                  <button
                    type="button"
                    className={s.rowBtn}
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => receiveBranchTransfer(t.id),
                        `Received from ${t.from_branch_name}. Added to your stock.`,
                      )
                    }
                  >
                    All arrived
                  </button>
                  <button
                    type="button"
                    className={s.rowBtn}
                    disabled={busy}
                    onClick={() => setShortId(t.id)}
                  >
                    Something is missing
                  </button>
                </div>
              )}
            </div>
          ))}
          {loaded && incoming.length === 0 && (
            <div className={s.empty}>Nothing on the way to you.</div>
          )}
        </div>

        {outgoing.length > 0 && (
          <>
            <div className={s.cardHead}>
              <div className={s.cardHeadText}>
                <h2>Sent, not yet confirmed</h2>
                <span>Already off your stock. Cancel puts it back.</span>
              </div>
            </div>
            <div className={s.list}>
              {outgoing.map((t) => (
                <div key={t.id} className={s.listItem}>
                  <strong>
                    To {t.to_branch_name}: {lineText(t)}
                  </strong>
                  <span>Sent {shortDate(t.created_at)} · waiting for them to confirm</span>
                  <div className={s.rowActions}>
                    <button
                      type="button"
                      className={s.rowBtn}
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => cancelBranchTransfer(t.id),
                          "Cancelled. The stock is back on your count.",
                        )
                      }
                    >
                      Cancel and take it back
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h2>Send stock</h2>
            <span>Comes off your count now, not when it arrives.</span>
          </div>
        </div>
        <div className={p.sendForm}>
          <label className={p.field}>
            <span>To branch</span>
            <select
              value={toBranch}
              onChange={(e) => setToBranch(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">Choose a branch</option>
              {branches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <label className={p.field}>
            <span>Item</span>
            <select value={ingredientName} onChange={(e) => setIngredientName(e.target.value)}>
              <option value="">Choose an item</option>
              {ingredients.map((i) => (
                <option key={i.id} value={i.name}>
                  {i.name} ({i.current_stock} {i.unit} here)
                </option>
              ))}
            </select>
          </label>
          <label className={p.field}>
            <span>Quantity</span>
            <input
              type="number"
              min="0"
              step="0.001"
              inputMode="decimal"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
          <label className={p.field}>
            <span>Note (optional)</span>
            <input
              type="text"
              maxLength={256}
              placeholder="e.g. driver Ahmed, 6pm van"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <Button
            size="md"
            type="button"
            disabled={busy || toBranch === "" || !ingredientName || !quantity}
            onClick={() => void send()}
          >
            Send
          </Button>
        </div>

        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h2>Past transfers</h2>
          </div>
        </div>
        <div className={s.list}>
          {history.slice(0, 10).map((t) => (
            <div key={t.id} className={s.listItem}>
              <strong>
                {t.direction === "out" ? `To ${t.to_branch_name}` : `From ${t.from_branch_name}`}:{" "}
                {lineText(t)}
              </strong>
              <span>
                {STATUS_LABEL[t.status] ?? t.status} · {shortDate(t.created_at)}
              </span>
            </div>
          ))}
          {loaded && history.length === 0 && <div className={s.empty}>No transfers yet.</div>}
        </div>
      </div>
    </section>
  );
}
