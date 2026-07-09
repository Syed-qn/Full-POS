import type { ButtonHTMLAttributes } from "react";
import s from "./Button.module.css";

type Variant = "primary" | "ghost" | "danger";
/** md = compact admin; lg = default; touch = POS primary ≥64px */
type Size = "md" | "lg" | "touch";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({
  variant = "primary",
  size = "lg",
  className = "",
  disabled,
  ...rest
}: Props) {
  return (
    <button
      className={`${s.btn} ${s[variant]} ${s[size]} ${className}`}
      {...rest}
      disabled={disabled}
      /* Native disabled + explicit aria-disabled so AT always announces state. */
      aria-disabled={disabled ? true : undefined}
    />
  );
}

/** Alias for touch-first primary actions (UI/UX spec ≥64px). */
export function TouchButton(props: Props) {
  return <Button size="touch" {...props} />;
}
