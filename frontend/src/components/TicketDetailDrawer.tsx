import { useEffect, useState } from "react";
import { Button } from "./Button";
import { SideDrawer } from "./SideDrawer";
import { resolveTicket } from "../lib/ticketsApi";
import { getWallet } from "../lib/walletApi";
import type { ResolveTicketIn, Ticket, WalletBalance } from "../lib/types";
import s from "./TicketDetailDrawer.module.css";

export function TicketDetailDrawer({
  ticket,
  onResolved,
}: {
  ticket: Ticket;
  onResolved: () => void;
}) {
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wallet, setWallet] = useState<WalletBalance | null>(null);

  const isResolved = ticket.status === "resolved";
  const noteOk = note.trim().length > 0;
  const amountOk = Number(amount) > 0;

  // Show the customer's current wallet credit so the manager has context when
  // deciding a refund. Best-effort — hidden if unavailable.
  useEffect(() => {
    let cancelled = false;
    getWallet(ticket.customer_id)
      .then((w) => !cancelled && setWallet(w))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [ticket.customer_id]);

  async function submit(body: ResolveTicketIn) {
    setSubmitting(true);
    setError(null);
    try {
      await resolveTicket(ticket.id, body);
      onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not resolve this ticket.");
    } finally {
      setSubmitting(false);
    }
  }

  const evidenceItems = Array.isArray(ticket.evidence) ? ticket.evidence : [];

  return (
    <SideDrawer open title={`Complaint #${ticket.id}`} onClose={onResolved}>
      <div className={s.section}>
        <div className={s.summary}>
          <Field label="Customer" value={`#${ticket.customer_id}`} />
          <Field label="Order" value={ticket.order_id ? `#${ticket.order_id}` : "—"} />
          {ticket.category && <Field label="Category" value={ticket.category} />}
          <Field label="Status" value={ticket.status.replace("_", " ")} />
          {wallet && (
            <Field
              label="Wallet credit"
              value={`AED ${wallet.available_aed}${wallet.status === "frozen" ? " (frozen)" : ""}`}
            />
          )}
        </div>
      </div>

      {ticket.source_message && (
        <div className={s.section}>
          <span className={s.label}>Customer message</span>
          <p className={s.message}>{ticket.source_message}</p>
        </div>
      )}

      {evidenceItems.length > 0 && (
        <div className={s.section}>
          <span className={s.label}>Evidence</span>
          <p className={s.message}>{evidenceItems.length} attachment(s)</p>
        </div>
      )}

      {isResolved ? (
        <div className={s.section}>
          <span className={s.label}>Resolution</span>
          <p className={s.message}>
            {(ticket.resolution_action ?? "resolved").replace(/_/g, " ")}
            {ticket.resolution_amount_aed
              ? ` · AED ${ticket.resolution_amount_aed}`
              : ""}
            {ticket.replacement_order_id
              ? ` · replacement order #${ticket.replacement_order_id}`
              : ""}
          </p>
          {ticket.resolution_note && (
            <p className={s.message}>“{ticket.resolution_note}”</p>
          )}
        </div>
      ) : (
        <>
          {error && (
            <div className={s.errorBanner} role="alert">
              {error}
            </div>
          )}

          <div className={s.section}>
            <label className={s.label} htmlFor="ticket-note">
              Resolution note (required)
            </label>
            <textarea
              id="ticket-note"
              className={s.textarea}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What was decided / communicated to the customer"
              disabled={submitting}
            />
            {!noteOk && (
              <p className={s.hint}>
                Type a resolution note first — the action buttons below stay disabled until you do.
              </p>
            )}
          </div>

          <div className={s.action}>
            <label className={s.label} htmlFor="ticket-amount">
              Refund amount (AED)
            </label>
            <input
              id="ticket-amount"
              className={s.input}
              type="number"
              min="0"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              disabled={submitting}
            />
            <Button
              type="button"
              disabled={submitting || !noteOk || !amountOk}
              onClick={() => submit({ action: "wallet_refund", note: note.trim(), amount })}
            >
              {submitting ? "Saving…" : "Refund to Wallet"}
            </Button>
            {noteOk && !amountOk && (
              <p className={s.hint}>Enter a refund amount above AED 0 to enable wallet credit.</p>
            )}
          </div>

          <div className={s.action}>
            <span className={s.hint}>
              {ticket.order_id
                ? "Creates a free replacement of the original order — sent to the kitchen, assigned a rider, and trackable like any order."
                : "This complaint isn't linked to an order, so a replacement can't be auto-created. Issue a refund or place a manual order instead."}
            </span>
            <Button
              type="button"
              variant="ghost"
              disabled={submitting || !noteOk || !ticket.order_id}
              onClick={() => submit({ action: "create_replacement", note: note.trim() })}
            >
              {submitting ? "Saving…" : "Create replacement order"}
            </Button>
          </div>

          <div className={s.action}>
            <Button
              type="button"
              variant="ghost"
              disabled={submitting || !noteOk}
              onClick={() => submit({ action: "resolved_no_action", note: note.trim() })}
            >
              {submitting ? "Saving…" : "Mark Resolved"}
            </Button>
          </div>
        </>
      )}
    </SideDrawer>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.field}>
      <span className={s.fieldLabel}>{label}</span>
      <span className={s.fieldValue}>{value}</span>
    </div>
  );
}
