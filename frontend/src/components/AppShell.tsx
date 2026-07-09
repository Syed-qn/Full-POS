import type { ReactNode } from "react";
import { DesktopStatusBar } from "./DesktopStatusBar";
import { NavSidebar } from "./NavSidebar";
import { SectionBanner } from "./SectionBanner";
import { SyncConflictBanner } from "./SyncConflictBanner";
import { TopBar } from "./TopBar";
import s from "./AppShell.module.css";

export function AppShell({
  children,
  connectionDown = false,
  unread = 0,
}: {
  children: ReactNode;
  connectionDown?: boolean;
  unread?: number;
}) {
  return (
    <div className={s.shell}>
      <NavSidebar unread={unread} />
      <div className={s.content}>
        <TopBar />
        <main className={s.main}>
          <SyncConflictBanner />
          {connectionDown && (
            <SectionBanner tone="warning">
              Live updates paused — reconnecting. Local queue still works offline.
            </SectionBanner>
          )}
          {children}
        </main>
        <DesktopStatusBar />
      </div>
    </div>
  );
}
