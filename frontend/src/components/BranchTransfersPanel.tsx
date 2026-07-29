/** Stock moving between branches of the same restaurant.
 *
 * Three legs, which is the standard trade flow: the branch that runs out ASKS,
 * the branch holding it SENDS, the asking branch CONFIRMS what turned up. A
 * branch can also send unprompted, skipping the first leg.
 *
 * Left column is everything waiting on you, ordered by who is blocked: a
 * request nobody has answered, then a delivery nobody has confirmed — stock in
 * that second state sits in neither branch's count. Right column is where you
 * start something new.
 *
 * Only rendered when this restaurant has sibling branches. A single-site
 * restaurant has nowhere to send to, and a tab that can only say "no branches"
 * teaches people to stop reading the tab bar.
 */
import { useState } from "react";
import { Button } from "./Button";
import {
  approveBranchRequest,
  cancelBranchTransfer,
  declineBranchRequest,
  dispatchBranchTransfer,
  receiveBranchTransfer,
  requestBranchStock,
  withdrawBranchRequest,
} from "../lib/branchTransfersApi";
import { toast } from "./Toaster";
import type { BranchTransferOut, IngredientOut, SiblingBranchOut } from "../lib/types";
import s from "../screens/InventoryScreen.module.css";
import p from "./BranchTransfersPanel.module.css";

/** Enough to see a working week of movements without the history column
 *  growing taller than the two beside it. */
const HISTORY_PAGE_SIZE = 5;

const STATUS_LABEL: Record<string, string> = {
  pending: "waiting for an answer",
  in_transit: "on the way",
  completed: "done",
  cancelled: "cancelled",
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

/** One line, spelling out only the numbers that actually differ. Asked 10,
 *  sent 6, got 5 are three separate facts, and a gap between any two of them
 *  is the thing worth reading. */
function lineText(transfer: BranchTransferOut): string {
  return transfer.lines
    .map((line) => {
      const parts: string[] = [];
      // == null, not === null: rows written before requests existed come back
      // without the field at all, and "asked undefined" is worse than silence.
      const asked = line.qty_requested ?? null;
      const sent = line.quantity;
      const got = line.qty_received ?? null;
      if (transfer.status === "pending") {
        return `${line.ingredient_name} ${asked ?? sent} ${line.unit}`;
      }
      if (asked !== null && Number(asked) !== Number(sent)) {
        parts.push(`asked ${asked}`);
      }
      parts.push(`sent ${sent}`);
      if (got !== null && Number(got) !== Number(sent)) {
        parts.push(`got ${got}`);
      }
      return `${line.ingredient_name} ${parts.join(", ")} ${line.unit}`;
    })
    .join(" · ");
}

type Adjust = { id: number; kind: "receive" | "approve" };

type Props = {
  transfers: BranchTransferOut[];
  branches: SiblingBranchOut[];
  ingredients: IngredientOut[];
  loaded: boolean;
  /** Refetch the screen. Both branches' stock figures may have changed. */
  onDone: () => void | Promise<void>;
};

export function BranchTransfersPanel({
  transfers,
  branches,
  ingredients,
  loaded,
  onDone,
}: Props) {
  const [mode, setMode] = useState<"request" | "send">("request");
  const [otherBranch, setOtherBranch] = useState<number | "">("");
  const [ingredientName, setIngredientName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  // Which row is having its quantities typed in. Both "send less than asked"
  // and "less arrived than was sent" use the same form; agreeing in full and
  // confirming in full are each one click, because most of the time nothing
  // is wrong and a form for the normal case is a form people learn to skip.
  const [adjust, setAdjust] = useState<Adjust | null>(null);
  const [adjustQty, setAdjustQty] = useState<Record<string, string>>({});
  const [page, setPage] = useState(0);

  // Which branch YOU are. Derived from the rows rather than plumbed in: the
  // server scoped them by the token, and on any row "out" means the from side
  // is us, so this can never disagree with the data it labels. The two screens
  // are otherwise near-identical, and telling them apart mattered the moment
  // somebody had one open per branch.
  const myBranchName =
    transfers.find((t) => t.direction === "out")?.from_branch_name ??
    transfers.find((t) => t.direction === "in")?.to_branch_name ??
    null;

  // Direction is the direction the STOCK travels, so a request sits the same
  // way round as a delivery: out of the holder, into the asker. On a pending
  // row that means "out" is someone asking YOU.
  const askedOfMe = transfers.filter((t) => t.status === "pending" && t.direction === "out");
  const iAsked = transfers.filter((t) => t.status === "pending" && t.direction === "in");
  const incoming = transfers.filter((t) => t.status === "in_transit" && t.direction === "in");
  const outgoing = transfers.filter((t) => t.status === "in_transit" && t.direction === "out");
  const history = transfers.filter((t) => t.status === "completed" || t.status === "cancelled");

  // Clamped rather than reset: answering a request removes a row from the
  // waiting list and ADDS one here, so the page you are on can shift under you.
  // Holding an out-of-range page would show an empty card with no way back.
  const pageCount = Math.max(1, Math.ceil(history.length / HISTORY_PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const firstShown = safePage * HISTORY_PAGE_SIZE + 1;
  const pageRows = history.slice(firstShown - 1, firstShown - 1 + HISTORY_PAGE_SIZE);
  const lastShown = firstShown + pageRows.length - 1;

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

  function closeAdjust(): void {
    setAdjust(null);
    setAdjustQty({});
  }

  async function submitForm(): Promise<void> {
    if (otherBranch === "" || !ingredientName || !quantity) return;
    const branch = branches.find((b) => b.id === otherBranch);
    const lines = [{ ingredient_name: ingredientName, quantity }];
    if (mode === "request") {
      await run(
        () =>
          requestBranchStock({
            from_restaurant_id: Number(otherBranch),
            lines,
            note: note || null,
          }),
        `Asked ${branch?.name ?? "the other branch"} for ${quantity} of ${ingredientName}.`,
      );
    } else {
      await run(
        () =>
          dispatchBranchTransfer({
            to_restaurant_id: Number(otherBranch),
            lines,
            note: note || null,
          }),
        `Sent ${quantity} of ${ingredientName} to ${branch?.name ?? "the other branch"}.`,
      );
    }
    setIngredientName("");
    setQuantity("");
    setNote("");
  }

  async function submitAdjust(transfer: BranchTransferOut): Promise<void> {
    const typed = transfer.lines
      .filter((line) => adjustQty[line.ingredient_name] !== undefined)
      .map((line) => ({
        ingredient_name: line.ingredient_name,
        quantity: adjustQty[line.ingredient_name],
      }));
    if (adjust?.kind === "approve") {
      await run(
        () => approveBranchRequest(transfer.id, typed),
        `Sent to ${transfer.to_branch_name}. Off your count now.`,
      );
    } else {
      await run(
        () =>
          receiveBranchTransfer(
            transfer.id,
            typed.map((line) => ({
              ingredient_name: line.ingredient_name,
              qty_received: line.quantity,
            })),
          ),
        "Recorded. The shortfall is kept against this transfer.",
      );
    }
    closeAdjust();
  }

  /** The quantity form shared by "send less" and "less arrived". */
  function adjustForm(transfer: BranchTransferOut) {
    const sending = adjust?.kind === "approve";
    return (
      <div className={p.shortForm}>
        {transfer.lines.map((line) => {
          const ceiling = sending ? (line.qty_requested ?? line.quantity) : line.quantity;
          return (
            <label key={line.ingredient_name} className={p.shortRow}>
              <span>
                {line.ingredient_name} — {sending ? "asked for" : "sent"} {ceiling} {line.unit}
              </span>
              <input
                type="number"
                min="0"
                max={String(ceiling)}
                step="0.001"
                inputMode="decimal"
                placeholder={String(ceiling)}
                aria-label={`${line.ingredient_name} ${sending ? "to send" : "received"}`}
                value={adjustQty[line.ingredient_name] ?? ""}
                onChange={(e) =>
                  setAdjustQty((prev) => ({ ...prev, [line.ingredient_name]: e.target.value }))
                }
              />
            </label>
          );
        })}
        <div className={p.shortActions}>
          <Button size="md" type="button" disabled={busy} onClick={() => void submitAdjust(transfer)}>
            {sending ? "Send this much" : "Save what arrived"}
          </Button>
          <Button size="md" type="button" variant="ghost" onClick={closeAdjust}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <section className={s.panels}>
      <div className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h2>Waiting on you{myBranchName ? ` · ${myBranchName}` : ""}</h2>
            <span>Requests to answer, then deliveries to confirm.</span>
          </div>
        </div>
        <div className={s.list}>
          {askedOfMe.map((t) => (
            <div key={t.id} className={s.listItem}>
              <strong>
                {t.to_branch_name} asked for {lineText(t)}
              </strong>
              <span>
                Asked {shortDate(t.created_at)}
                {t.note ? ` · ${t.note}` : ""}
              </span>
              {adjust?.id === t.id && adjust.kind === "approve" ? (
                adjustForm(t)
              ) : (
                <div className={s.rowActions}>
                  <button
                    type="button"
                    className={`${s.rowBtn} ${p.primary}`}
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => approveBranchRequest(t.id),
                        `Sent to ${t.to_branch_name}. Off your count now.`,
                      )
                    }
                  >
                    Send it all
                  </button>
                  <button
                    type="button"
                    className={s.rowBtn}
                    disabled={busy}
                    onClick={() => setAdjust({ id: t.id, kind: "approve" })}
                  >
                    Send less
                  </button>
                  <button
                    type="button"
                    className={s.rowBtn}
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => declineBranchRequest(t.id, "none to spare"),
                        `Declined ${t.to_branch_name}.`,
                      )
                    }
                  >
                    Cannot spare it
                  </button>
                </div>
              )}
            </div>
          ))}

          {incoming.map((t) => (
            <div key={t.id} className={s.listItem}>
              <strong>
                On the way from {t.from_branch_name}: {lineText(t)}
              </strong>
              <span>
                Sent {shortDate(t.created_at)}
                {t.note ? ` · ${t.note}` : ""}
              </span>
              {adjust?.id === t.id && adjust.kind === "receive" ? (
                adjustForm(t)
              ) : (
                <div className={s.rowActions}>
                  <button
                    type="button"
                    className={`${s.rowBtn} ${p.primary}`}
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
                    onClick={() => setAdjust({ id: t.id, kind: "receive" })}
                  >
                    Something is missing
                  </button>
                </div>
              )}
            </div>
          ))}

          {loaded && askedOfMe.length === 0 && incoming.length === 0 && (
            <div className={s.empty}>Nothing waiting on you.</div>
          )}
        </div>

        {(iAsked.length > 0 || outgoing.length > 0) && (
          <>
            <div className={s.cardHead}>
              <div className={s.cardHeadText}>
                <h2>Waiting on them</h2>
              </div>
            </div>
            <div className={s.list}>
              {iAsked.map((t) => (
                <div key={t.id} className={s.listItem}>
                  <strong>
                    You asked {t.from_branch_name} for {lineText(t)}
                  </strong>
                  <span>Asked {shortDate(t.created_at)} · no answer yet</span>
                  <div className={s.rowActions}>
                    <button
                      type="button"
                      className={`${s.rowBtn} ${p.secondary}`}
                      disabled={busy}
                      onClick={() =>
                        void run(() => withdrawBranchRequest(t.id), "Request withdrawn.")
                      }
                    >
                      Never mind
                    </button>
                  </div>
                </div>
              ))}
              {outgoing.map((t) => (
                <div key={t.id} className={s.listItem}>
                  <strong>
                    To {t.to_branch_name}: {lineText(t)}
                  </strong>
                  {/* Already off this branch count — once the van has gone the
                      food is not in this kitchen. */}
                  <span>Sent {shortDate(t.created_at)} · off your stock, not confirmed yet</span>
                  <div className={s.rowActions}>
                    <button
                      type="button"
                      className={`${s.rowBtn} ${p.secondary}`}
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
            <h2>{mode === "request" ? "Ask for stock" : "Send stock"}</h2>
            <span>
              {mode === "request"
                ? "Nothing moves until they agree."
                : "Comes off your count now, not when it arrives."}
            </span>
          </div>
        </div>
        <div className={p.modeTabs} role="tablist" aria-label="Transfer type">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "request"}
            className={`${p.modeTab} ${mode === "request" ? p.modeTabActive : ""}`}
            onClick={() => setMode("request")}
          >
            Ask for stock
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "send"}
            className={`${p.modeTab} ${mode === "send" ? p.modeTabActive : ""}`}
            onClick={() => setMode("send")}
          >
            Send stock
          </button>
        </div>
        <div className={p.sendForm}>
          <label className={p.field}>
            <span>{mode === "request" ? "Ask which branch" : "To branch"}</span>
            <select
              value={otherBranch}
              onChange={(e) => setOtherBranch(e.target.value === "" ? "" : Number(e.target.value))}
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
            {/* Asking is free text: you often need something this branch has
                never stocked, which is exactly why you are asking. Sending is
                a list, because you can only send what you actually hold. */}
            {mode === "request" ? (
              <input
                type="text"
                list="branch-transfer-items"
                maxLength={128}
                placeholder="e.g. Chicken"
                value={ingredientName}
                onChange={(e) => setIngredientName(e.target.value)}
              />
            ) : (
              <select value={ingredientName} onChange={(e) => setIngredientName(e.target.value)}>
                <option value="">Choose an item</option>
                {ingredients.map((i) => (
                  <option key={i.id} value={i.name}>
                    {i.name} ({i.current_stock} {i.unit} here)
                  </option>
                ))}
              </select>
            )}
            <datalist id="branch-transfer-items">
              {ingredients.map((i) => (
                <option key={i.id} value={i.name} />
              ))}
            </datalist>
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
              placeholder={
                mode === "request" ? "e.g. need it before the dinner rush" : "e.g. driver Ahmed, 6pm van"
              }
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <Button
            size="md"
            type="button"
            disabled={busy || otherBranch === "" || !ingredientName || !quantity}
            onClick={() => void submitForm()}
          >
            {mode === "request" ? "Send request" : "Send"}
          </Button>
        </div>

      </div>

      {/* Its own column, not tacked under the form. Finished transfers are
          what you check a discrepancy against, so they are read on their own —
          buried below a form you have to scroll past, nobody looks. */}
      <div className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h2>Past transfers</h2>
            <span>Finished and cancelled, newest first.</span>
          </div>
        </div>
        <div className={s.list}>
          {pageRows.map((t) => (
            <div key={t.id} className={s.listItem}>
              <strong>
                {t.direction === "out" ? `To ${t.to_branch_name}` : `From ${t.from_branch_name}`}:{" "}
                {lineText(t)}
              </strong>
              <span>
                {STATUS_LABEL[t.status] ?? t.status} · {shortDate(t.created_at)}
                {t.note ? ` · ${t.note}` : ""}
              </span>
            </div>
          ))}
          {loaded && history.length === 0 && <div className={s.empty}>No transfers yet.</div>}
        </div>
        {pageCount > 1 && (
          <div className={p.pager}>
            <button
              type="button"
              className={`${s.rowBtn} ${p.secondary}`}
              disabled={safePage === 0}
              onClick={() => setPage(safePage - 1)}
            >
              Back
            </button>
            {/* The range, not just "page 2 of 4" — when a transfer is missing
                you want to know how far down the list you have already read. */}
            <span className={p.pageCount}>
              {firstShown}–{lastShown} of {history.length}
            </span>
            <button
              type="button"
              className={`${s.rowBtn} ${p.secondary}`}
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage(safePage + 1)}
            >
              Next
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
