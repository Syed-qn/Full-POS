import { useEffect, useReducer } from "react";

/** POS surface theme, shared across the waiter floor + order terminal. */
export type PosTheme = "dark" | "light" | "blue";

const KEY = "waiter_theme";
const ORDER: PosTheme[] = ["dark", "light", "blue"];

function read(): PosTheme {
  const s = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
  return s === "light" || s === "blue" || s === "dark" ? s : "dark";
}

let current: PosTheme = read();
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function setPosTheme(t: PosTheme) {
  current = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* ignore quota / disabled storage */
  }
  emit();
}

/** Advance dark → light → blue → dark. */
export function cyclePosTheme() {
  const i = ORDER.indexOf(current);
  setPosTheme(ORDER[(i + 1) % ORDER.length]);
}

/**
 * Subscribe to the shared theme. Any component using this re-renders when the
 * theme changes anywhere (e.g. the top-bar switcher updates the screen root),
 * so a single store keeps the floor, order terminal, and header in lockstep.
 */
export function usePosTheme(): PosTheme {
  const [, force] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    listeners.add(force);
    return () => {
      listeners.delete(force);
    };
  }, []);
  return current;
}
