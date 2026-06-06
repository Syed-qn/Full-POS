import type { ReactNode } from "react";
import s from "./SectionBanner.module.css";

type Tone = "warning" | "error" | "info" | "success";

export function SectionBanner({
  tone,
  children,
  onDismiss,
}: {
  tone: Tone;
  children: ReactNode;
  onDismiss?: () => void;
}) {
  return (
    <div className={`${s.banner} ${s[tone]}`} role="status">
      <span>{children}</span>
      {onDismiss && (
        <button className={s.x} onClick={onDismiss} aria-label="Dismiss">
          ✕
        </button>
      )}
    </div>
  );
}
