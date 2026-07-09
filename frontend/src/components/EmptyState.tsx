import type { ReactNode } from "react";
import s from "./EmptyState.module.css";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className={s.wrap} role="status">
      <h3 className={s.title}>{title}</h3>
      {description && <p className={s.desc}>{description}</p>}
      {action && <div className={s.action}>{action}</div>}
    </div>
  );
}
