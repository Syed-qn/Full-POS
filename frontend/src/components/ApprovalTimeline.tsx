import { Button } from "./Button";
import s from "./ApprovalTimeline.module.css";

export type ApprovalTimelineProps = {
  status: string;
  rejectionReason?: string | null;
  onFixWithAI?: () => void;
  onEditManually?: () => void;
  onSubmit?: () => void;
  fixing?: boolean;
  submitting?: boolean;
};

const STEPS = ["Submitted", "Pending", "Approved"] as const;

function stepIndex(status: string): number {
  if (status === "approved") return 3;
  if (status === "rejected") return 2;
  if (status === "pending_meta") return 2;
  if (status === "draft") return 0;
  return 0;
}

export function ApprovalTimeline({
  status,
  rejectionReason,
  onFixWithAI,
  onEditManually,
  onSubmit,
  fixing = false,
  submitting = false,
}: ApprovalTimelineProps) {
  if (!status || status === "deleted") return null;

  const active = stepIndex(status);
  const failed = status === "rejected";
  const showDraftSubmit = status === "draft" && onSubmit;

  return (
    <div className={s.root} data-status={status}>
      <div className={s.track} aria-label="Template approval progress">
        {STEPS.map((label, i) => {
          const stepNum = i + 1;
          const complete = active > stepNum || (status === "approved" && stepNum <= 3);
          // "current" is the in-progress step (pulsing ring). An approved step is
          // finished, not in-progress, so it is only "complete" (clean green check)
          // — never both, which previously drew a blue ring around a green dot.
          const current = status === "pending_meta" && stepNum === 2;
          const failedStep = failed && label === "Pending";
          return (
            <div
              key={label}
              className={`${s.step} ${complete ? s.stepComplete : ""} ${
                current ? s.stepActive : ""
              } ${failedStep ? s.stepFailed : ""}`}
            >
              <div className={s.dot} aria-hidden>
                {failedStep ? "✕" : complete ? "✓" : stepNum === 2 && status === "pending_meta" ? "◐" : ""}
              </div>
              <span className={s.label}>{label}</span>
            </div>
          );
        })}
      </div>

      {failed && (
        <div className={s.rejectedBox}>
          <div className={s.rejectedTitle}>Meta rejected this template</div>
          {rejectionReason ? (
            <p className={s.rejectedReason}>{rejectionReason}</p>
          ) : null}
          <div className={s.rejectedActions}>
            {onFixWithAI && (
              <Button variant="ghost" onClick={onFixWithAI} disabled={fixing}>
                {fixing ? "Fixing…" : "✨ Fix with AI"}
              </Button>
            )}
            {onEditManually && (
              <Button variant="ghost" onClick={onEditManually}>
                Edit manually
              </Button>
            )}
          </div>
        </div>
      )}

      {showDraftSubmit && (
        <div className={s.draftActions}>
          <p className={s.draftHint}>Template revised — submit again for Meta approval.</p>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Submitting…" : "Submit for approval"}
          </Button>
        </div>
      )}
    </div>
  );
}