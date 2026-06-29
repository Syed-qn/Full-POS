import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import s from "./SideDrawer.module.css";

export function SideDrawer({
  open,
  title,
  onClose,
  children,
  wide,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return createPortal(
    <div className={s.root}>
      <div className={s.scrim} data-testid="drawer-scrim" onClick={onClose} />
      <aside
        className={`${s.panel} ${wide ? s.wide : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className={s.head}>
          <span className={s.title}>{title}</span>
          <button type="button" className={s.x} onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className={s.body}>{children}</div>
      </aside>
    </div>,
    document.body,
  );
}
