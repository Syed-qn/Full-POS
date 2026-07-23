import { useEffect, useReducer } from "react";

/**
 * Manager dashboard theme.
 *
 * Deliberately separate from `posTheme`: the POS boards are wall-mounted in a
 * kitchen or on a counter and are usually set once per DEVICE, while the
 * dashboard follows the person reading it. Sharing one key would make a manager
 * darkening their laptop also darken the kitchen screen.
 *
 * The value is written to <html data-theme>, so the palettes in tokens.css
 * reach every screen AND every portal (dialogs, drawers, toasts) without any
 * component having to opt in.
 */
export type AppTheme = "light" | "dark" | "blue";

const KEY = "dashboard_theme";
const ORDER: AppTheme[] = ["light", "dark", "blue"];

export const APP_THEME_LABEL: Record<AppTheme, string> = {
  light: "Light",
  dark: "Dark",
  blue: "Blue",
};

/** Icon shown for the theme you would switch TO — the control's next state. */
export const APP_THEME_ICON: Record<AppTheme, string> = {
  light: "☀",
  dark: "🌙",
  blue: "🌊",
};

function read(): AppTheme {
  const s = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
  return s === "dark" || s === "blue" || s === "light" ? s : "light";
}

let current: AppTheme = read();
const listeners = new Set<() => void>();

/** Light is the default palette, so it carries no attribute at all. */
function apply(t: AppTheme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (t === "light") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", t);
}

// Paint before first render so a dark user never sees a white flash.
apply(current);

export function getAppTheme(): AppTheme {
  return current;
}

export function setAppTheme(t: AppTheme) {
  current = t;
  apply(t);
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* ignore quota / disabled storage */
  }
  for (const l of listeners) l();
}

/** Advance light → dark → blue → light. */
export function cycleAppTheme() {
  setAppTheme(ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]);
}

export function nextAppTheme(): AppTheme {
  return ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
}

/** Subscribe — every consumer re-renders when the theme changes anywhere. */
export function useAppTheme(): AppTheme {
  const [, force] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    listeners.add(force);
    return () => {
      listeners.delete(force);
    };
  }, []);
  return current;
}
