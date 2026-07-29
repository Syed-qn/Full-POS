import { useEffect, useRef, useState } from "react";
import { apiClient } from "../lib/apiClient";
import { setToken } from "../lib/auth";
import type { OrganizationBranchOut } from "../lib/types";
import s from "./BranchSwitcher.module.css";

/**
 * Pick which branch the whole dashboard is looking at.
 *
 * Every branch-level screen — staff, menu, orders, inventory, reports — reads
 * its restaurant from the bearer token, so switching branch swaps the token
 * rather than passing a restaurant id down through each screen. That keeps
 * exactly one place where "which branch" is decided, and the server re-checks
 * ownership when it issues the new token.
 *
 * Renders nothing for a single-branch account: a picker with one entry is just
 * a control that can go wrong.
 */
/**
 * Last known branches + selection, so the control survives the reload that
 * switching triggers. Session-scoped: cleared on sign-out with the rest of the
 * session, so a different account never inherits another's branch list.
 */
const CACHE_KEY = "pos.branches";
const CURRENT_KEY = "pos.branch_current";

function readCachedBranches(): OrganizationBranchOut[] | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // Guard the shape: a half-written or stale-format entry must not throw
    // during render and blank the whole top bar.
    if (!Array.isArray(parsed) || !parsed.every((b) => typeof b?.id === "number")) {
      return null;
    }
    return parsed as OrganizationBranchOut[];
  } catch {
    return null;
  }
}

export function BranchSwitcher() {
  // Seed from cache so the field is on screen immediately after the reload,
  // rather than popping in seconds later when the round trip lands.
  const [branches, setBranches] = useState<OrganizationBranchOut[] | null>(
    () => readCachedBranches(),
  );
  const [currentId, setCurrentId] = useState<number | null>(() => {
    const raw = sessionStorage.getItem(CURRENT_KEY);
    const n = raw ? Number(raw) : NaN;
    return Number.isInteger(n) && n > 0 ? n : null;
  });
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // apiClient, NOT organizationsApi.listBranches: that helper authenticates
    // with the separate ORG token, which only exists after the Branches screen
    // runs bootstrap. In the top bar there is usually no org token yet, so the
    // call 401'd and the switcher silently rendered nothing — branches visible
    // on their own page, no way to switch from anywhere else.
    //
    // The endpoint accepts a restaurant OWNER token directly whenever that
    // restaurant is linked to an organization, which is exactly this case.
    // A standalone restaurant has no organization, so this 403s — that is the
    // normal single-branch case, not an error worth surfacing.
    apiClient
      .get<OrganizationBranchOut[]>("/api/v1/organizations/branches")
      .then((list) => {
        setBranches(list);
        try {
          sessionStorage.setItem(CACHE_KEY, JSON.stringify(list));
        } catch {
          /* private mode / quota — the control still works, just without the cache */
        }
      })
      // Only fall back to "no branches" when nothing was cached; a failed
      // refresh must not tear down a control that was rendering fine.
      .catch(() => setBranches((prev) => prev ?? []));
    // Which store this session is actually looking at, so the control shows the
    // truth instead of an empty "Switch branch…" prompt. The token decides the
    // branch, so /me is the only honest source — the cached value above is just
    // an optimistic head start until this answers.
    apiClient
      .get<{ id: number }>("/api/v1/me")
      .then((me) => {
        setCurrentId(me.id);
        try {
          sessionStorage.setItem(CURRENT_KEY, String(me.id));
        } catch {
          /* ignore */
        }
      })
      .catch(() => {});
  }, []);

  async function switchTo(id: number) {
    setBusy(true);
    try {
      const res = await apiClient.post<{ access_token: string; name: string }>(
        `/api/v1/organizations/branches/${id}/session`,
      );
      setToken(res.access_token);
      // Record the target before reloading so the control comes back already
      // showing the branch you picked, instead of flashing the previous one
      // until /me answers.
      try {
        sessionStorage.setItem(CURRENT_KEY, String(id));
      } catch {
        /* ignore */
      }
      // Full reload rather than a state update: every screen has already cached
      // data for the previous branch, and a hard boundary is cheaper to reason
      // about than invalidating each of them.
      window.location.reload();
    } catch {
      setBusy(false);
    }
  }

  // Close on an outside click or Escape. A popup that only closes by picking
  // something turns a glance at the list into an unwanted branch switch.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // A closed branch is not somewhere you can switch to — the server refuses to
  // mint a token for it — so offering it here would only produce a dead option
  // that errors on click. `!== false` so an older server, which omits the field
  // entirely, keeps showing every branch instead of hiding all of them.
  const openBranches = branches?.filter((b) => b.is_active !== false) ?? null;

  if (!openBranches || openBranches.length < 2) return null;

  // Show the branch actually in use. Until /me answers, fall back to the main
  // branch rather than a blank prompt — a control that reads "Switch branch…"
  // never tells you where you already are.
  const fallback = openBranches.find((b) => b.is_main)?.id ?? openBranches[0].id;
  const selected = currentId ?? fallback;

  // Look the current branch up in the FULL list: if the one you are signed into
  // was just closed, the trigger should still name it rather than silently
  // showing a different store while your token belongs to this one.
  const current =
    branches?.find((b) => b.id === selected) ?? openBranches[0];

  return (
    <div className={s.root} ref={rootRef}>
      <button
        type="button"
        className={s.wrap}
        role="combobox"
        aria-label="Branch"
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={busy}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={s.label}>Branch</span>
        <span className={s.value}>{current.name}</span>
        {current.is_main && <span className={s.mainTag}>Main</span>}
        <span className={s.chev} aria-hidden="true" />
      </button>

      {open && (
        <ul className={s.menu} role="listbox" aria-label="Branch">
          {openBranches.map((b) => {
            const isCurrent = b.id === selected;
            return (
              <li key={b.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isCurrent}
                  className={`${s.item} ${isCurrent ? s.itemCurrent : ""}`}
                  onClick={() => {
                    setOpen(false);
                    if (!isCurrent) void switchTo(b.id);
                  }}
                >
                  {/* Always rendered, hidden when not current, so the labels
                      line up instead of shifting by a tick's width. */}
                  <span className={s.tick} aria-hidden="true">
                    {isCurrent ? "✓" : ""}
                  </span>
                  <span className={s.itemName}>{b.name}</span>
                  {b.is_main && <span className={s.mainTag}>Main</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
