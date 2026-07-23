import { useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { inviteRiderToApp } from "../lib/ridersApi";
import type { RiderOut } from "../lib/types";
import s from "./DishEditModal.module.css";

interface Props {
  rider: RiderOut;
  /** The restaurant's WhatsApp number the rider must message first (or null). */
  restaurantPhone: string | null;
  onClose: () => void;
}

/**
 * Confirmation dialog for "Send app link". WhatsApp only lets the business
 * message a rider AFTER the rider messages first (the 24h service window), so we
 * instruct the manager to have the rider send "hi" to the restaurant's number
 * before we text the pairing code + app link — then confirm to actually send.
 */
export function AppInviteModal({ rider, restaurantPhone, onClose }: Props) {
  const [busy, setBusy] = useState(false);

  async function onConfirm() {
    setBusy(true);
    try {
      const res = await inviteRiderToApp(rider.id);
      toast(
        `Pairing code ${res.code} sent on WhatsApp (valid ${res.expires_in_minutes} min).`,
        "success",
      );
      onClose();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not send the app link.", "error");
      setBusy(false);
    }
  }

  return (
    <div className={s.overlay} onClick={onClose}>
      <div className={s.modal} onClick={(e) => e.stopPropagation()}>
        <div className={s.header}>
          <h2 className={s.title}>Send app link to {rider.name}</h2>
          <button className={s.close} onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className={s.body}>
          <p style={{ margin: 0, lineHeight: 1.5 }}>
            WhatsApp only delivers our message after the rider contacts you first.
            So before sending the link:
          </p>
          <ol style={{ margin: "12px 0 0", paddingLeft: 20, lineHeight: 1.6 }}>
            <li>
              Ask <strong>{rider.name}</strong> to send <strong>“hi”</strong> from{" "}
              <strong>{rider.phone}</strong> to your WhatsApp number:
              <div
                style={{
                  marginTop: 6,
                  fontFamily: "var(--font-mono)",
                  fontWeight: 700,
                  fontSize: 16,
                  color: "var(--accent-primary)",
                }}
              >
                {restaurantPhone ?? "your WhatsApp business number"}
              </div>
            </li>
            <li style={{ marginTop: 8 }}>
              Once they’ve sent it, confirm below and we’ll text them the pairing
              code and app download link.
            </li>
          </ol>
        </div>

        <div className={s.footer}>
          <div className={s.footerRight}>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={onConfirm} disabled={busy}>
              {busy ? "Sending…" : "Confirm & send link"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
