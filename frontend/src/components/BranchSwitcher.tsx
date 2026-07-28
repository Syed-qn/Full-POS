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
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // A standalone restaurant has no organization, so this 403s — that is the
    // normal single-branch case, not an error worth surfacing.
    listBranches()
      .then(setBranches)
      .catch(() => setBranches([]));
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

  return (
    <label className={s.wrap}>
      <span className={s.label}>Branch</span>
      <select
        className={s.select}
        aria-label="Branch"
        disabled={busy}
        defaultValue=""
        onChange={(e) => {
          const id = Number(e.target.value);
          if (Number.isInteger(id) && id > 0) void switchTo(id);
        }}
      >
        <option value="" disabled>
          {busy ? "Switching…" : "Switch branch…"}
        </option>
        {branches.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
          </option>
        ))}
      </select>
    </label>
  );
}
