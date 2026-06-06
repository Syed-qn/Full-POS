import s from "./Spinner.module.css";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className={s.spinner} role="status" aria-label={label} />;
}
