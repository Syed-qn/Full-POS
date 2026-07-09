import { useEffect, useState } from "react";
import { getPosBridge, isDesktopShell } from "../lib/desktopEnv";
import s from "./DesktopStatusBar.module.css";

export function DesktopStatusBar() {
  const desktop = isDesktopShell();
  const [online, setOnline] = useState(true);
  const [pending, setPending] = useState(0);
  const [conflicts, setConflicts] = useState(0);
  const [clock, setClock] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!desktop) return;
    const bridge = getPosBridge();
    let cancelled = false;

    async function tick() {
      try {
        if (bridge?.networkStatus) {
          const st = await bridge.networkStatus();
          if (!cancelled) setOnline(st.online);
        }
        if (bridge?.listPendingOps) {
          const ops = await bridge.listPendingOps();
          if (!cancelled) setPending(ops.length);
        }
        if (bridge?.listConflicts) {
          const c = await bridge.listConflicts();
          if (!cancelled) setConflicts(c.length);
        }
      } catch {
        if (!cancelled) setOnline(false);
      }
    }

    void tick();
    const id = setInterval(() => void tick(), 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [desktop]);

  return (
    <footer className={s.bar} role="status" aria-live="polite">
      <div className={s.left}>
        <span className={s.brand}>FULL POS</span>
        <span className={s.sep}>·</span>
        <span className={s.mode}>{desktop ? "Local terminal" : "Cloud console"}</span>
        {desktop && (
          <>
            <span className={s.sep}>·</span>
            <span className={`${s.dot} ${online ? s.ok : s.bad}`} />
            <span className={online ? s.okText : s.badText}>
              {online ? "Online" : "Offline — local queue active"}
            </span>
            {pending > 0 && (
              <span className={s.chip} title="Queued for sync">
                {pending} pending
              </span>
            )}
            {conflicts > 0 && (
              <span className={s.chipWarn} title="Sync conflicts">
                {conflicts} conflict{conflicts === 1 ? "" : "s"}
              </span>
            )}
          </>
        )}
      </div>
      <div className={s.right}>
        <span className={s.hint}>F5 refresh · Esc close drawer</span>
        <span className={s.clock}>
          {clock.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </span>
      </div>
    </footer>
  );
}
