import { useState } from "react";
import { Button } from "./Button";
import { SideDrawer } from "./SideDrawer";
import { resolveTicket } from "../lib/ticketsApi";
import type { ResolveTicketIn, Ticket } from "../lib/types";
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
  const [replacementOrderId, setReplacementOrderId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const noteOk = note.trim().length > 0;
  const amountOk = Number(amount) > 0;

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

  return (
    <SideDrawer open title={`Complaint #${ticket.id}`} onClose={onResolved}>
      <div className={s.section}>
        <div className={s.summary}>
          <Field label="Customer" value={`#${ticket.customer_id}`} />
          <Field label="Order" value={ticket.order_id ? `#${ticket.order_id}` : "—"} />
          {ticket.category && <Field label="Category" value={ticket.category} />}
          <Field label="Status" value={ticket.status} />
        </div>
      </div>

      {ticket.source_message && (
        <div className={s.section}>
          <span className={s.label}>Customer message</span>
          <p className={s.message}>{ticket.source_message}</p>
        </div>
      )}

      {ticket.evidence && (
        <div className={s.section}>
          <span className={s.label}>Evidence</span>
          <p className={s.message}>{ticket.evidence}</p>
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
        />
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
        />
        <Button
          disabled={submitting || !noteOk || !amountOk}
          onClick={() =>
            submit({ action: "wallet_refund", note, amount })
          }
        >
          Refund to Wallet
        </Button>
      </div>

      <div className={s.action}>
        <label className={s.label} htmlFor="ticket-replacement">
          Replacement order id
        </label>
        <input
          id="ticket-replacement"
          className={s.input}
          type="number"
          min="0"
          value={replacementOrderId}
          onChange={(e) => setReplacementOrderId(e.target.value)}
        />
        <Button
          variant="ghost"
          disabled={submitting || !noteOk}
          onClick={() =>
            submit({
              action: "replacement",
              note,
              ...(replacementOrderId
                ? { replacement_order_id: Number(replacementOrderId) }
                : {}),
            })
          }
        >
          Send Replacement
        </Button>
      </div>

      <div className={s.action}>
        <Button
          variant="ghost"
          disabled={submitting || !noteOk}
          onClick={() => submit({ action: "resolved_no_action", note })}
        >
          Mark Resolved
        </Button>
      </div>

      {error && <p className={s.error}>{error}</p>}
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
