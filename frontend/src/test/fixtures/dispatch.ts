import type { DispatchKpisOut } from "../../lib/types";

/** Vitest fixture — production uses GET /api/v1/dispatch/kpis. */
export const MOCK_DISPATCH_KPIS: DispatchKpisOut = {
  batch_rate_pct: 42,
  avg_stops: 2.1,
  engine_fallback_pct: 8,
  window: "today",
};