import type { ReactNode } from "react";
import s from "./PageHeader.module.css";

// Consistent page title + subtitle header (matches the home "Live Operations"
// header) with proper vertical spacing. Optional right-side slot for actions.
export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <header className={s.header}>
      <div>
        <h1 className={s.title}>{title}</h1>
        {subtitle && <p className={s.sub}>{subtitle}</p>}
      </div>
      {right && <div className={s.right}>{right}</div>}
    </header>
  );
}
