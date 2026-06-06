import type { ReactNode } from "react";
import { NavSidebar } from "./NavSidebar";
import { SectionBanner } from "./SectionBanner";
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
      <main className={s.main}>
        {connectionDown && (
          <SectionBanner tone="warning">
            Live updates paused — reconnecting.
          </SectionBanner>
        )}
        {children}
      </main>
    </div>
  );
}
