import { useCallback, useState, type ReactNode } from "react";
import { ApprovalPinModal } from "../components/ApprovalPinModal";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { submitManagerPin } from "./staffApi";

/** Danger-action types recorded on POST /api/v1/staff/approvals. */
export type ManagerPinActionType =
  | "void"
  | "refund"
  | "discount"
  | "stock_adjustment"
  | "channel_pause"
  | string;

export type ManagerPinGateRequest = {
  actionType: ManagerPinActionType;
  actionLabel: string;
  /** Affected record id / number shown in the modal. */
  recordLabel: string;
  /** Required for void, refund, stock adjustment. */
  reasonRequired?: boolean;
  orderId?: number;
  amountAed?: string;
  confirmTitle: string;
  confirmMessage: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Business action after PIN is accepted and approval is recorded. */
  execute: (ctx: { pin: string; reason: string }) => Promise<void>;
};

/**
 * Record manager approval via staff approvals API.
 * Matches OrderDetailScreen void path (submitManagerPin).
 */
export async function recordManagerApproval(opts: {
  pin: string;
  reason: string;
  actionType: string;
  orderId?: number;
  amountAed?: string;
}) {
  return submitManagerPin({
    pin: opts.pin,
    action_type: opts.actionType,
    order_id: opts.orderId,
    amount_aed: opts.amountAed,
    reason: opts.reason || undefined,
  });
}

/**
 * ConfirmDialog → ApprovalPinModal gate for protected manager actions.
 * Always shows action label + record id; optional reason for high-risk ops.
 */
export function useManagerPinGate() {
  const [pending, setPending] = useState<ManagerPinGateRequest | null>(null);
  const [phase, setPhase] = useState<"idle" | "confirm" | "pin">("idle");
  const [busy, setBusy] = useState(false);

  const requestPin = useCallback((req: ManagerPinGateRequest) => {
    setPending(req);
    setPhase("confirm");
  }, []);

  const cancel = useCallback(() => {
    if (busy) return;
    setPhase("idle");
    setPending(null);
  }, [busy]);

  const continueToPin = useCallback(() => {
    setPhase("pin");
  }, []);

  const onApprove = useCallback(
    async (payload: { pin: string; reason: string }) => {
      if (!pending) return;
      setBusy(true);
      try {
        await recordManagerApproval({
          pin: payload.pin,
          reason: payload.reason,
          actionType: pending.actionType,
          orderId: pending.orderId,
          amountAed: pending.amountAed,
        });
        await pending.execute(payload);
        setPhase("idle");
        setPending(null);
      } finally {
        setBusy(false);
      }
    },
    [pending],
  );

  const pinGate: ReactNode =
    pending && phase !== "idle" ? (
      <>
        {phase === "confirm" && (
          <ConfirmDialog
            title={pending.confirmTitle}
            message={pending.confirmMessage}
            confirmLabel={pending.confirmLabel ?? "Continue to PIN"}
            cancelLabel={pending.cancelLabel ?? "Keep"}
            danger
            busy={busy}
            onConfirm={continueToPin}
            onCancel={cancel}
          />
        )}
        <ApprovalPinModal
          open={phase === "pin"}
          actionLabel={pending.actionLabel}
          recordLabel={pending.recordLabel}
          reasonRequired={Boolean(pending.reasonRequired)}
          onCancel={cancel}
          onApprove={onApprove}
        />
      </>
    ) : null;

  return {
    requestPin,
    pinGate,
    pinBusy: busy,
    pinActive: phase !== "idle",
  };
}
