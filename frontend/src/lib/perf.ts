/** Dev-only timing helper for dashboard TTFP checks (see dashboard latency spec). */
export function perfMark(label: string, startMs: number): void {
  if (!import.meta.env.DEV) return;
  const elapsed = performance.now() - startMs;
  console.debug("[perf]", label, `${elapsed.toFixed(1)}ms`);
}

export function perfNow(): number {
  return performance.now();
}