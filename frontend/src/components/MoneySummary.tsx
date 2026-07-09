import s from "./MoneySummary.module.css";

export function MoneySummary({
  label = "Amount due",
  amount,
  currency = "AED",
  size = "lg",
}: {
  label?: string;
  amount: string | number;
  currency?: string;
  size?: "md" | "lg";
}) {
  const display =
    typeof amount === "number"
      ? amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : amount;

  return (
    <div className={`${s.wrap} ${size === "lg" ? s.lg : s.md}`}>
      <span className={s.label}>{label}</span>
      <span className={s.amount}>
        <span className={s.currency}>{currency}</span> {display}
      </span>
    </div>
  );
}
