import type { ReactNode } from "react";
import s from "./BottomActionBar.module.css";

export function BottomActionBar({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`${s.bar} ${className}`} role="toolbar" aria-label="Primary actions">
      {children}
    </div>
  );
}
