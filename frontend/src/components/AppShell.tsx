import type { ReactNode } from "react";
import { getRoleChrome, getSessionRole, isTrainingMode } from "../lib/navAccess";
import { useOfflineStatus } from "../lib/useOfflineStatus";
import { DesktopStatusBar } from "./DesktopStatusBar";
import { NavSidebar } from "./NavSidebar";
import { SectionBanner } from "./SectionBanner";
import { SyncConflictBanner } from "./SyncConflictBanner";
import { TopBar } from "./TopBar";
import type { AlertItem } from "./AlertCenter";
import s from "./AppShell.module.css";

export function AppShell({
  children,
  connectionDown,
  unread = 0,
  alerts = [],
}: {
  children: ReactNode;
  /** Optional force-offline (tests / parent override). When omitted, uses live navigator + desktop status. */
  connectionDown?: boolean;
  unread?: number;
  alerts?: AlertItem[];
}) {
  const status = useOfflineStatus();
  const offline = connectionDown ?? status.offline;
  const training = isTrainingMode();
  const role = getSessionRole();
  const chrome = getRoleChrome(role);

  return (
    <div
      className={`${s.shell} ${training ? s.training : ""} ${!chrome.showSidebar ? s.noSidebar : ""}`}
      data-training={training ? "true" : "false"}
      data-role-mode={chrome.mode}
    >
      {chrome.showSidebar && <NavSidebar unread={unread} />}
      <div className={s.content}>
        <TopBar offline={offline} pendingCount={status.pendingCount} alerts={alerts} />
        <main className={s.main}>
          <SyncConflictBanner />
          {training && (
            <SectionBanner tone="warning">
              Training mode is on — orders and sales from this session are excluded from real KPIs.
            </SectionBanner>
          )}
          {offline && (
            <SectionBanner tone="warning">
              Live updates paused — reconnecting. Local queue still works offline. See Reliability
              for details.
            </SectionBanner>
          )}
          {children}
        </main>
        <DesktopStatusBar />
      </div>
    </div>
  );
}
