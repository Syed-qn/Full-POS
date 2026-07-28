import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "../components/Button";
import { LocationPickerModal } from "../components/LocationPickerModal";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import { isAuthenticated } from "../lib/auth";
import {
  bootstrapOrganizationFromRestaurant,
  completeStockTransfer,
  createBranch,
  createStockTransfer,
  getBranchComparison,
  getOrgIdFromToken,
  getOrgToken,
  getOrganizationInventorySummary,
  getRollupSales,
  listBranches,
  loginOrganization,
  signupOrganization,
} from "../lib/organizationsApi";
import type {
  BranchComparisonOut,
  OrganizationBranchOut,
  OrganizationInventorySummaryOut,
  OrganizationRollupSalesOut,
  StockTransferOut,
} from "../lib/types";
import s from "./BranchOpsScreen.module.css";

type Phase = "loading" | "ready" | "denied";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthStartIso(): string {
  const d = new Date();
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)).toISOString().slice(0, 10);
}

function money(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  return `AED ${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function coordsLabel(lat?: number, lng?: number): string {
  if (lat == null || lng == null || !Number.isFinite(lat) || !Number.isFinite(lng)) {
    return "No map pin";
  }
  return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

export function BranchOpsScreen() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [branches, setBranches] = useState<OrganizationBranchOut[]>([]);
  const [rollup, setRollup] = useState<OrganizationRollupSalesOut | null>(null);
  const [summary, setSummary] = useState<OrganizationInventorySummaryOut | null>(null);
  const [comparison, setComparison] = useState<BranchComparisonOut[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [targetDate, setTargetDate] = useState(todayIso);
  const [startDate, setStartDate] = useState(monthStartIso);
  const [endDate, setEndDate] = useState(todayIso);
  const [submitting, setSubmitting] = useState(false);

  // Dialogs (header buttons only)
  const [addOpen, setAddOpen] = useState(false);
  const [stockOpen, setStockOpen] = useState(false);
  const [branchName, setBranchName] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [branchRegion, setBranchRegion] = useState("");
  const [mapOpen, setMapOpen] = useState(false);

  // Stock transfer form (dialog)
  const [fromBranch, setFromBranch] = useState("");
  const [toBranch, setToBranch] = useState("");
  const [ingredientName, setIngredientName] = useState("");
  const [transferUnit, setTransferUnit] = useState("kg");
  const [transferQty, setTransferQty] = useState("");
  const [lastTransfer, setLastTransfer] = useState<StockTransferOut | null>(null);

  // Optional org login (denied state only)
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [signupName, setSignupName] = useState("");

  const orgId = getOrgIdFromToken();

  const rollupByBranch = useMemo(
    () => new Map((rollup?.branches ?? []).map((row) => [row.restaurant_id, row])),
    [rollup],
  );
  const inventoryByBranch = useMemo(
    () => new Map((summary?.branches ?? []).map((row) => [row.restaurant_id, row])),
    [summary],
  );
  const comparisonByBranch = useMemo(
    () => new Map(comparison.map((row) => [row.restaurant_id, row])),
    [comparison],
  );

  const loadData = useCallback(async () => {
    setLoadError(null);
    const currentOrgId = getOrgIdFromToken();
    const [branchRows, rollupReport, inventoryReport, comparisonRows] = await Promise.all([
      listBranches(),
      getRollupSales(targetDate),
      getOrganizationInventorySummary(),
      currentOrgId
        ? getBranchComparison(currentOrgId, startDate, endDate)
        : Promise.resolve([] as BranchComparisonOut[]),
    ]);
    setBranches(branchRows);
    setRollup(rollupReport);
    setSummary(inventoryReport);
    setComparison(comparisonRows);
    setFromBranch((prev) => prev || String(branchRows[0]?.id ?? ""));
    setToBranch((prev) => prev || String(branchRows[1]?.id ?? branchRows[0]?.id ?? ""));
  }, [endDate, startDate, targetDate]);

  const openHq = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) setPhase("loading");
    setLoadError(null);
    try {
      if (isAuthenticated()) {
        try {
          await bootstrapOrganizationFromRestaurant();
        } catch {
          // Keep going if a valid org JWT already exists.
          if (!getOrgToken()) throw new Error("Owner access required for multi-branch HQ.");
        }
      }
      if (!getOrgToken()) {
        setPhase("denied");
        return;
      }
      await loadData();
      setPhase("ready");
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not open multi-branch HQ.");
      setPhase(getOrgToken() ? "ready" : "denied");
    }
  }, [loadData]);

  // Boot once on mount.
  useEffect(() => {
    void openHq();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only
  }, []);

  // Silent auto-refresh while HQ is open (no manual Refresh button).
  useEffect(() => {
    if (phase !== "ready") return;
    const id = window.setInterval(() => {
      void openHq({ silent: true });
    }, 15_000);
    return () => window.clearInterval(id);
  }, [phase, openHq]);

  async function submitAuth(mode: "login" | "signup") {
    if (!loginEmail.trim() || !loginPassword.trim() || (mode === "signup" && !signupName.trim())) {
      toast("Organization credentials are required.", "error");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "signup") {
        await signupOrganization(signupName, loginEmail, loginPassword);
      } else {
        await loginOrganization(loginEmail, loginPassword);
      }
      await loadData();
      setPhase("ready");
      toast(mode === "signup" ? "Organization created." : "Organization signed in.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Organization sign-in failed.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitBranch() {
    const parsedLat = Number(lat);
    const parsedLng = Number(lng);
    if (!branchName.trim() || !Number.isFinite(parsedLat) || !Number.isFinite(parsedLng)) {
      toast("Branch name and a map location (or lat/lng) are required.", "error");
      return;
    }
    setSubmitting(true);
    try {
      // No email/password: the branch is reached through the owner's own login
      // via the Branch switcher, so it gets no credential of its own.
      const created = await createBranch({
        name: branchName.trim(),
        lat: parsedLat,
        lng: parsedLng,
        region: branchRegion.trim() || undefined,
      });
      setBranches((prev) => [...prev, created]);
      setBranchName("");
      setLat("");
      setLng("");
      setBranchRegion("");
      setAddOpen(false);
      toast(`Branch added: ${created.name}. Switch to it from the Branch menu.`);
      await loadData();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not add branch.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitTransfer() {
    if (!orgId) {
      toast("Organization session missing. Refresh the page.", "error");
      return;
    }
    if (!fromBranch || !toBranch || fromBranch === toBranch || !ingredientName.trim() || !transferQty.trim()) {
      toast("Pick two different branches and enter ingredient + quantity.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const created = await createStockTransfer(orgId, {
        from_restaurant_id: Number(fromBranch),
        to_restaurant_id: Number(toBranch),
        lines: [{ ingredient_name: ingredientName.trim(), unit: transferUnit, quantity: transferQty }],
      });
      setLastTransfer(created);
      toast(`Transfer #${created.id} created`);
      // Keep dialog open so user can complete the transfer if needed.
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create transfer.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function completeTransfer() {
    if (!lastTransfer) return;
    try {
      const completed = await completeStockTransfer(lastTransfer.id);
      setLastTransfer(completed);
      toast(`Transfer #${completed.id} completed.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not complete transfer.", "error");
    }
  }

  if (phase === "loading") {
    return (
      <div className={s.screen}>
        <PageHeader title="Branches" subtitle="Loading multi-branch HQ…" />
        <div className={s.skeleton} aria-busy="true" aria-label="Loading branches">
          <div className={s.skKpis}>
            <div className={s.skTile} />
            <div className={s.skTile} />
            <div className={s.skTile} />
            <div className={s.skTile} />
          </div>
          <div className={s.skCards}>
            <div className={s.skCard} />
            <div className={s.skCard} />
          </div>
          <div className={s.skTable} />
        </div>
      </div>
    );
  }

  if (phase === "denied") {
    return (
      <div className={s.screen}>
        <PageHeader
          title="Branches"
          subtitle="Franchise HQ is for the restaurant owner only."
        />
        <section className={s.card}>
          <div className={s.cardHead}>
            <h2>Owner access required</h2>
            <span>
              {loadError ||
                "Sign in with the restaurant owner account (not a branch manager PIN) to manage locations."}
            </span>
          </div>
          <p className={s.hint}>
            Branch managers keep running their single store from the normal dashboard. Multi-branch
            sales, stock moves, and new locations are owner-only.
          </p>
        </section>
        <details className={s.advanced}>
          <summary>Optional organization email login</summary>
          <section className={s.card}>
            <div className={s.formGrid}>
              <label>
                <span>Organization name</span>
                <input value={signupName} onChange={(e) => setSignupName(e.target.value)} />
              </label>
              <label>
                <span>Owner email</span>
                <input value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)} />
              </label>
              <label>
                <span>Password</span>
                <input
                  type="password"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                />
              </label>
            </div>
            <div className={s.actions}>
              <Button
                type="button"
                size="md"
                variant="ghost"
                disabled={submitting}
                onClick={() => void submitAuth("signup")}
              >
                Create organization
              </Button>
              <Button type="button" size="md" disabled={submitting} onClick={() => void submitAuth("login")}>
                Sign in
              </Button>
            </div>
          </section>
        </details>
      </div>
    );
  }

  return (
    <div className={s.screen}>
      <PageHeader
        title="Branches"
        subtitle="Compare locations, add a branch, move stock between stores"
        right={
          <div className={s.headerTools}>
            <label className={s.dateField}>
              <span>Sales day</span>
              <input
                aria-label="Rollup date"
                type="date"
                value={targetDate}
                onChange={(e) => setTargetDate(e.target.value)}
              />
            </label>
            <Button type="button" size="md" variant="ghost" onClick={() => setStockOpen(true)}>
              Stock transfer
            </Button>
            <Button type="button" size="md" onClick={() => setAddOpen(true)}>
              + Add branch
            </Button>
          </div>
        }
      />

      {loadError && <div className={s.banner}>{loadError}</div>}

      <section className={s.kpis} aria-label="HQ summary">
        <div className={s.kpi}>
          <span>Branches</span>
          <strong>{branches.length}</strong>
        </div>
        <div className={s.kpi}>
          <span>Sales (selected day)</span>
          <strong>{money(rollup?.total_gross_sales_aed)}</strong>
        </div>
        <div className={s.kpi}>
          <span>Inventory value</span>
          <strong>{money(summary?.total_inventory_value_aed)}</strong>
        </div>
        <div className={s.kpi}>
          <span>Low-stock items</span>
          <strong>{summary?.total_low_stock_count ?? 0}</strong>
        </div>
      </section>

      <section className={s.branchGrid} aria-label="Branch list">
        {branches.map((branch) => {
          const sales = rollupByBranch.get(branch.id);
          const inv = inventoryByBranch.get(branch.id);
          const cmp = comparisonByBranch.get(branch.id);
          return (
            <article key={branch.id} className={s.branchCard}>
              <div className={s.branchTop}>
                <div>
                  <h2 className={s.branchName}>{branch.name}</h2>
                  <p className={s.branchMeta}>
                    #{branch.id}
                    {branch.email ? ` · ${branch.email}` : ""}
                    {branch.region ? ` · ${branch.region}` : ""}
                    {branch.is_central_kitchen ? " · Central kitchen" : ""}
                  </p>
                </div>
                <span className={s.pin}>{coordsLabel(branch.lat, branch.lng)}</span>
              </div>
              <div className={s.branchStats}>
                <div>
                  <span>Day sales</span>
                  <strong>{money(sales?.gross_sales_aed)}</strong>
                </div>
                <div>
                  <span>Orders (range)</span>
                  <strong>{cmp?.order_count ?? 0}</strong>
                </div>
                <div>
                  <span>Revenue (range)</span>
                  <strong>{money(cmp?.revenue_aed)}</strong>
                </div>
                <div>
                  <span>Inventory</span>
                  <strong>{money(inv?.inventory_value_aed)}</strong>
                </div>
              </div>
              <div className={s.branchFoot}>
                <span className={(inv?.low_stock_count ?? 0) > 0 ? s.badgeWarn : s.badgeOk}>
                  {(inv?.low_stock_count ?? 0) > 0
                    ? `${inv?.low_stock_count} low stock`
                    : "Stock OK"}
                </span>
              </div>
            </article>
          );
        })}
        {branches.length === 0 && (
          <div className={s.emptyCard}>
            <p>No branches yet.</p>
            <Button type="button" size="md" onClick={() => setAddOpen(true)}>
              Add your first branch
            </Button>
          </div>
        )}
      </section>

      <section className={s.card}>
        <div className={s.cardHeadRow}>
          <div>
            <h2>Performance</h2>
            <span>Compare locations over a date range</span>
          </div>
          <div className={s.range}>
            <label>
              <span>From</span>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </label>
            <label>
              <span>To</span>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </label>
            <Button
              type="button"
              size="md"
              variant="ghost"
              onClick={() => void openHq({ silent: true })}
            >
              Apply
            </Button>
          </div>
        </div>
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>Branch</th>
                <th>Day sales</th>
                <th>Orders</th>
                <th>Range revenue</th>
                <th>Inventory</th>
                <th>Low stock</th>
              </tr>
            </thead>
            <tbody>
              {branches.map((branch) => {
                const sales = rollupByBranch.get(branch.id);
                const inv = inventoryByBranch.get(branch.id);
                const cmp = comparisonByBranch.get(branch.id);
                return (
                  <tr key={branch.id}>
                    <td>{branch.name}</td>
                    <td>{money(sales?.gross_sales_aed)}</td>
                    <td>{cmp ? `${cmp.order_count}` : "0"}</td>
                    <td>{money(cmp?.revenue_aed)}</td>
                    <td>{money(inv?.inventory_value_aed)}</td>
                    <td>
                      <span className={(inv?.low_stock_count ?? 0) > 0 ? s.badgeWarn : s.badgeOk}>
                        {inv?.low_stock_count ?? 0}
                      </span>
                    </td>
                  </tr>
                );
              })}
              {branches.length === 0 && (
                <tr>
                  <td colSpan={6} className={s.empty}>
                    No branches yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {stockOpen &&
        createPortal(
          <div
            className={s.dialogOverlay}
            onClick={submitting ? undefined : () => setStockOpen(false)}
          >
            <div
              className={s.dialog}
              role="dialog"
              aria-modal="true"
              aria-labelledby="stock-transfer-title"
              onClick={(e) => e.stopPropagation()}
            >
              <div className={s.dialogHead}>
                <div>
                  <h2 id="stock-transfer-title">Stock transfer</h2>
                  <p>Move inventory between two branches with an audit trail.</p>
                </div>
                <button
                  type="button"
                  className={s.dialogClose}
                  aria-label="Close"
                  disabled={submitting}
                  onClick={() => setStockOpen(false)}
                >
                  ×
                </button>
              </div>
              <div className={s.dialogBody}>
                <div className={s.formGridSingle}>
                  <label>
                    <span>From branch</span>
                    <select
                      aria-label="From branch"
                      value={fromBranch}
                      onChange={(e) => setFromBranch(e.target.value)}
                    >
                      <option value="">Select branch</option>
                      {branches.map((branch) => (
                        <option key={branch.id} value={branch.id}>
                          {branch.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>To branch</span>
                    <select
                      aria-label="To branch"
                      value={toBranch}
                      onChange={(e) => setToBranch(e.target.value)}
                    >
                      <option value="">Select branch</option>
                      {branches.map((branch) => (
                        <option key={branch.id} value={branch.id}>
                          {branch.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Ingredient</span>
                    <input
                      aria-label="Ingredient"
                      value={ingredientName}
                      onChange={(e) => setIngredientName(e.target.value)}
                      placeholder="Rice"
                    />
                  </label>
                  <div className={s.inlineFields}>
                    <label>
                      <span>Unit</span>
                      <input
                        aria-label="Transfer unit"
                        value={transferUnit}
                        onChange={(e) => setTransferUnit(e.target.value)}
                      />
                    </label>
                    <label>
                      <span>Quantity</span>
                      <input
                        aria-label="Quantity"
                        value={transferQty}
                        onChange={(e) => setTransferQty(e.target.value)}
                        placeholder="5"
                      />
                    </label>
                  </div>
                  {lastTransfer && (
                    <p className={s.hint}>
                      Last transfer #{lastTransfer.id} · status{" "}
                      <strong>{lastTransfer.status}</strong>
                    </p>
                  )}
                </div>
              </div>
              <div className={s.dialogFoot}>
                <Button
                  type="button"
                  size="md"
                  variant="ghost"
                  disabled={submitting}
                  onClick={() => setStockOpen(false)}
                >
                  Cancel
                </Button>
                {lastTransfer && lastTransfer.status !== "completed" && (
                  <Button
                    type="button"
                    size="md"
                    variant="ghost"
                    onClick={() => void completeTransfer()}
                  >
                    Complete #{lastTransfer.id}
                  </Button>
                )}
                <Button
                  type="button"
                  size="md"
                  disabled={submitting}
                  onClick={() => void submitTransfer()}
                >
                  Create transfer
                </Button>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {addOpen &&
        createPortal(
          <div
            className={s.dialogOverlay}
            onClick={submitting ? undefined : () => setAddOpen(false)}
          >
            <div
              className={s.dialog}
              role="dialog"
              aria-modal="true"
              aria-labelledby="add-branch-title"
              onClick={(e) => e.stopPropagation()}
            >
              <div className={s.dialogHead}>
                <div>
                  <h2 id="add-branch-title">Add branch</h2>
                  <p>Creates a full store under this organization (own menu, orders, staff).</p>
                </div>
                <button
                  type="button"
                  className={s.dialogClose}
                  aria-label="Close"
                  disabled={submitting}
                  onClick={() => setAddOpen(false)}
                >
                  ×
                </button>
              </div>
              <div className={s.dialogBody}>
                <div className={s.formGridSingle}>
                  <label>
                    <span>Branch name</span>
                    <input
                      aria-label="Branch name"
                      value={branchName}
                      onChange={(e) => setBranchName(e.target.value)}
                      placeholder="e.g. Marina, Downtown"
                      autoFocus
                    />
                  </label>
                  {/* No login fields: a branch has no credential of its own.
                      Your owner account manages every branch through the Branch
                      switcher, so a second password per store would be one more
                      thing to leak and rotate for no extra reach. */}
                  <p className={s.locHint}>
                    You manage this branch with your own owner login. Use the Branch switcher
                    at the top to move between stores. Staff sign in at the branch with their
                    number and PIN.
                  </p>
                  <div className={s.locBlock}>
                    <div className={s.locHead}>
                      <span className={s.locLabel}>Location</span>
                      <button type="button" className={s.mapBtn} onClick={() => setMapOpen(true)}>
                        {lat.trim() && lng.trim() ? "Change on map" : "Set on map"}
                      </button>
                    </div>
                    <div className={s.coordRow}>
                      <label>
                        <span>Latitude</span>
                        <input
                          aria-label="Latitude"
                          inputMode="decimal"
                          placeholder="25.20480"
                          value={lat}
                          onChange={(e) => setLat(e.target.value)}
                        />
                      </label>
                      <label>
                        <span>Longitude</span>
                        <input
                          aria-label="Longitude"
                          inputMode="decimal"
                          placeholder="55.27080"
                          value={lng}
                          onChange={(e) => setLng(e.target.value)}
                        />
                      </label>
                    </div>
                    <p className={s.locHint}>
                      Use the map (search / click / drag pin) or type coordinates.
                    </p>
                  </div>
                  <label>
                    <span>Region (optional)</span>
                    <input
                      aria-label="Branch region"
                      value={branchRegion}
                      onChange={(e) => setBranchRegion(e.target.value)}
                      placeholder="dubai"
                    />
                  </label>
                </div>
              </div>
              <div className={s.dialogFoot}>
                <Button
                  type="button"
                  size="md"
                  variant="ghost"
                  disabled={submitting}
                  onClick={() => setAddOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="md"
                  disabled={submitting}
                  onClick={() => void submitBranch()}
                >
                  Add branch
                </Button>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {mapOpen && (
        <LocationPickerModal
          title="Set branch location"
          lat={lat.trim() && Number.isFinite(Number(lat)) ? Number(lat) : 0}
          lng={lng.trim() && Number.isFinite(Number(lng)) ? Number(lng) : 0}
          onSave={(la, ln) => {
            setLat(String(la));
            setLng(String(ln));
            setMapOpen(false);
            toast("Location set from map.");
          }}
          onClose={() => setMapOpen(false)}
        />
      )}
    </div>
  );
}
