import type { ButtonHTMLAttributes } from "react";
import s from "./Button.module.css";

type Variant = "primary" | "ghost" | "danger";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({ variant = "primary", className = "", ...rest }: Props) {
  return <button className={`${s.btn} ${s[variant]} ${className}`} {...rest} />;
}
