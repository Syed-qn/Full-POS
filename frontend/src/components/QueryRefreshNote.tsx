/** Inline note when a cached query refetch fails but stale rows are still shown. */
export function QueryRefreshNote({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span style={{ color: "var(--danger, #dc2626)", fontSize: 13 }}>
      Couldn&apos;t refresh
    </span>
  );
}