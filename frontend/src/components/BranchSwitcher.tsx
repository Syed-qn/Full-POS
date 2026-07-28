import { useEffect, useState } from "react";
import { apiClient } from "../lib/apiClient";
import { setToken } from "../lib/auth";
import { listBranches } from "../lib/organizationsApi";
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
export function BranchSwitcher() {
  const [branches, setBranches] = useState<OrganizationBranchOut[] | null>(null);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // A standalone restaurant has no organization, so this 403s — that is the
    // normal single-branch case, not an error worth surfacing.
    listBranches()
      .then(setBranches)
      .catch(() => setBranches([]));
    // Which store this session is actually looking at, so the control shows the
    // truth instead of an empty "Switch branch…" prompt. The token decides the
    // branch, so /me is the only honest source.
    apiClient
      .get<{ id: number }>("/api/v1/me")
      .then((me) => setCurrentId(me.id))
      .catch(() => {});
  }, []);

  async function switchTo(id: number) {
    setBusy(true);
    try {
      const res = await apiClient.post<{ access_token: string; name: string }>(
        `/api/v1/organizations/branches/${id}/session`,
      );
      setToken(res.access_token);
      // Full reload rather than a state update: every screen has already cached
      // data for the previous branch, and a hard boundary is cheaper to reason
      // about than invalidating each of them.
      window.location.reload();
    } catch {
      setBusy(false);
    }
  }

  if (!branches || branches.length < 2) return null;

  // Show the branch actually in use. Until /me answers, fall back to the main
  // branch rather than a blank prompt — a control that reads "Switch branch…"
  // never tells you where you already are.
  const fallback = branches.find((b) => b.is_main)?.id ?? branches[0].id;
  const selected = currentId ?? fallback;

  return (
    <label className={s.wrap}>
      <span className={s.label}>Branch</span>
      <select
        className={s.select}
        aria-label="Branch"
        disabled={busy}
        value={String(selected)}
        onChange={(e) => {
          const id = Number(e.target.value);
          if (Number.isInteger(id) && id > 0 && id !== selected) void switchTo(id);
        }}
      >
        {branches.map((b) => (
          <option key={b.id} value={b.id}>
            {b.is_main ? `${b.name} (Main)` : b.name}
          </option>
        ))}
      </select>
    </label>
  );
}
