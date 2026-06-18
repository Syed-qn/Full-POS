import { useEffect, useState } from "react";
import s from "./Toaster.module.css";

type ToastType = "success" | "error";
interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
}

// Tiny pub/sub so any module can call toast() without prop-drilling a context.
let counter = 0;
const listeners = new Set<(t: ToastItem) => void>();

export function toast(message: string, type: ToastType = "success") {
  counter += 1;
  const item: ToastItem = { id: counter, message, type };
  listeners.forEach((l) => l(item));
}

/** Mount once near the app root. Renders stacked toasts bottom-right. */
export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const onToast = (t: ToastItem) => {
      setItems((prev) => [...prev, t]);
      setTimeout(() => {
        setItems((prev) => prev.filter((x) => x.id !== t.id));
      }, 3200);
    };
    listeners.add(onToast);
    return () => {
      listeners.delete(onToast);
    };
  }, []);

  if (items.length === 0) return null;

  return (
    <div className={s.wrap} role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`${s.toast} ${s[t.type]}`}>
          <span className={s.icon} aria-hidden>{t.type === "success" ? "✓" : "!"}</span>
          <span className={s.msg}>{t.message}</span>
        </div>
      ))}
    </div>
  );
}
