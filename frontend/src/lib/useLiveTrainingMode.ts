/** Keep the training-mode banner honest.
 *
 * The staff session stores training_mode as it was at LOGIN. The server reads
 * the live column when it stamps an order, so a manager flipping the switch
 * mid-shift made the two disagree: the next order was correctly marked as
 * training while the screen showed no banner, or the reverse. Nobody watching
 * that screen has any reason to doubt it.
 *
 * This re-reads the flag and writes it back into the session, so the banner
 * follows the same value the server is acting on.
 */
import { useEffect, useState } from "react";
import { getStaffSession, isTrainingMode, setStaffSession } from "./navAccess";
import { getStaffMe } from "./staffApi";

/** Slow on purpose. Training mode changes a handful of times a week, and this
 *  runs on every till and every floor screen at once. */
const POLL_MS = 60_000;

export function useLiveTrainingMode(): boolean {
  const [training, setTraining] = useState(isTrainingMode);

  useEffect(() => {
    const session = getStaffSession();
    // Owner and manager tokens carry no staff row, so /me has nothing to
    // return for them and there is no banner to keep honest.
    if (!session) return;

    let cancelled = false;
    async function check(): Promise<void> {
      try {
        const me = await getStaffMe();
        if (cancelled) return;
        const current = getStaffSession();
        if (!current || current.training_mode === me.training_mode) {
          setTraining(me.training_mode);
          return;
        }
        // Write it back so anything else reading the session — and the next
        // reload — agrees rather than flipping back to the login snapshot.
        setStaffSession({ ...current, training_mode: me.training_mode });
        setTraining(me.training_mode);
      } catch {
        // Offline, or a session the endpoint will not answer for. Keep showing
        // what we last knew rather than clearing a banner that may be true.
      }
    }

    void check();
    // Coming back to the tab is the moment a stale banner is most likely and
    // costs nothing to catch.
    function onVisible(): void {
      if (document.visibilityState === "visible") void check();
    }
    document.addEventListener("visibilitychange", onVisible);
    const id = window.setInterval(check, POLL_MS);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(id);
    };
  }, []);

  return training;
}
