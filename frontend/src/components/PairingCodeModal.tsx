import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { issueRiderPairingCode, type PairingCodeOut } from "../lib/ridersApi";
import type { RiderOut } from "../lib/types";
import s from "./PairingCodeModal.module.css";

/**
 * Shows the rider's app pairing code on screen.
 *
 * "Send app link" texts the code over WhatsApp, which Meta only allows inside
 * the 24h service window — i.e. it fails for exactly the rider who has never
 * messaged the restaurant, which is every NEW rider. This dialog issues the same
 * code and displays it, so the manager can simply read it out or hand over the
 * screen.
 *
 * A code lives 60 minutes and there is only ever one live code per rider:
 * pressing "New code" replaces the old one, which stops working immediately.
 */
export function PairingCodeModal({ rider, onClose }: { rider: RiderOut; onClose: () => void }) {
  const [data, setData] = useState<PairingCodeOut | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // Each mint REPLACES the rider's live code, so only one code is ever valid.
  // Two guards keep the screen honest about which one that is:
  //   reqIdRef  — two in-flight mints can land out of order (separate HTTP
  //               connections), so a slow earlier response must not overwrite a
  //               newer code. Only the highest request id may set state.
  //   mintedRef — React StrictMode runs mount effects twice in dev, which minted
  //               two codes per open and invalidated the first one mid-race. The
  //               open only ever mints once now.
  const reqIdRef = useRef(0);
  const mintedRef = useRef(false);

  const issue = useCallback(async () => {
    const reqId = ++reqIdRef.current;
    setBusy(true);
    setError(null);
    try {
      const next = await issueRiderPairingCode(rider.id);
      if (reqId !== reqIdRef.current) return; // superseded by a newer code
      setData(next);
    } catch (e) {
      if (reqId !== reqIdRef.current) return;
      setError(e instanceof Error ? e.message : "Could not create a code.");
    } finally {
      if (reqId === reqIdRef.current) setBusy(false);
    }
  }, [rider.id]);

  // Issue one as soon as the dialog opens — the manager asked for a code.
  useEffect(() => {
    if (mintedRef.current) return;
    mintedRef.current = true;
    void issue();
  }, [issue]);

  // Drive the countdown so an expired code visibly stops being usable rather
  // than sitting on screen looking valid.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const expiresAt = data?.expires_at ? new Date(data.expires_at).getTime() : null;
  const msLeft = expiresAt === null ? null : expiresAt - now;
  const expired = msLeft !== null && msLeft <= 0;
  const countdown =
    msLeft === null || expired
      ? null
      : `${Math.floor(msLeft / 60000)}m ${String(Math.floor((msLeft % 60000) / 1000)).padStart(2, "0")}s`;

  // Rendered into <body>, NOT inside the rider card. The card sets
  // `transform: translateY(-1px)` on hover, and a transformed ancestor becomes
  // the containing block for position:fixed children — so the overlay would size
  // itself to the CARD instead of the viewport and appear trapped inside it.
  return createPortal(
    <div className={s.overlay} onClick={onClose}>
      <div className={s.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Pairing code">
        <div className={s.header}>
          <h2 className={s.title}>Pairing code for {rider.name}</h2>
          <button className={s.close} onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className={s.body}>
          {error ? (
            <p className={s.error}>{error}</p>
          ) : (
            <>
              <div className={`${s.code} ${expired ? s.codeExpired : ""}`} data-testid="pairing-code">
                {busy && !data ? "······" : (data?.code ?? "······")}
              </div>
              <div className={expired ? s.expiryDead : s.expiry}>
                {busy && !data
                  ? "Creating a code…"
                  : expired
                    ? "Expired. Press New code"
                    : countdown
                      ? `Valid for ${countdown}`
                      : `Valid ${data?.expires_in_minutes ?? 60} minutes`}
              </div>
              <ol className={s.steps}>
                <li>Rider installs the rider app.</li>
                <li>They enter this code once, on the pairing screen.</li>
                <li>The code is then used up. The app stays signed in.</li>
              </ol>
            </>
          )}
        </div>

        <div className={s.footer}>
          <Button
            variant="ghost"
            disabled={!data?.code}
            onClick={() =>
              navigator.clipboard?.writeText(data?.code ?? "").then(
                () => toast("Code copied"),
                () => toast("Copy failed. Read it from the screen"),
              )
            }
          >
            Copy
          </Button>
          <Button variant="ghost" onClick={() => void issue()} disabled={busy}>
            {busy ? "Working…" : "New code"}
          </Button>
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
