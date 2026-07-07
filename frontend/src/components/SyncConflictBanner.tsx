import { useEffect, useState } from "react";

interface ConflictOp {
  id: string;
  entity: string;
  path: string;
}

export function SyncConflictBanner() {
  const [conflicts, setConflicts] = useState<ConflictOp[]>([]);

  useEffect(() => {
    const bridge = (
      window as unknown as { posBridge?: { listConflicts: () => Promise<ConflictOp[]> } }
    ).posBridge;
    if (!bridge) return;
    bridge.listConflicts().then(setConflicts);
  }, []);

  if (conflicts.length === 0) {
    return <div data-testid="sync-conflict-banner" />;
  }

  return (
    <div data-testid="sync-conflict-banner" role="alert">
      {conflicts.length} change{conflicts.length === 1 ? "" : "s"} couldn't sync — needs
      review
    </div>
  );
}
