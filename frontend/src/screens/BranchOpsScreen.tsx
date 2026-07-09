import { useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { SectionBanner } from "../components/SectionBanner";
import { toast } from "../components/Toaster";
import {
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

export function BranchOpsScreen() {
  const [hasOrgToken, setHasOrgToken] = useState(() => getOrgToken() !== null);
  const [branches, setBranches] = useState<OrganizationBranchOut[]>([]);
  const [rollup, setRollup] = useState<OrganizationRollupSalesOut | null>(null);
  const [summary, setSummary] = useState<OrganizationInventorySummaryOut | null>(null);
  const [comparison, setComparison] = useState<BranchComparisonOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [targetDate, setTargetDate] = useState(todayIso);
  const [startDate, setStartDate] = useState(monthStartIso);
  const [endDate, setEndDate] = useState(todayIso);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [signupName, setSignupName] = useState("");
  const [branchName, setBranchName] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [fromBranch, setFromBranch] = useState("");
  const [toBranch, setToBranch] = useState("");
  const [ingredientName, setIngredientName] = useState("");
  const [transferUnit, setTransferUnit] = useState("kg");
  const [transferQty, setTransferQty] = useState("");
  const [lastTransfer, setLastTransfer] = useState<StockTransferOut | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const orgId = getOrgIdFromToken();

  async function load() {
    if (!getOrgToken()) {
      setHasOrgToken(false);
      setLoaded(true);
      return;
    }
    setHasOrgToken(true);
    setLoadError(null);
    try {
      const currentOrgId = getOrgIdFromToken();
      const [branchRows, rollupReport, inventoryReport, comparisonRows] =
        await Promise.all([
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
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not load branch operations.");
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- date changes reload through the Refresh action
  }, []);

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
      setHasOrgToken(true);
      await load();
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
      toast("Branch name, latitude, and longitude are required.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const created = await createBranch({ name: branchName, lat: parsedLat, lng: parsedLng });
      setBranches((prev) => [...prev, created]);
      setBranchName("");
      setLat("");
      setLng("");
      toast(`Branch added: ${created.name}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not add branch.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitTransfer() {
    if (!orgId) {
      toast("Sign in to the organization first.", "error");
      return;
    }
    if (!fromBranch || !toBranch || fromBranch === toBranch || !ingredientName.trim() || !transferQty.trim()) {
      toast("Pick two branches and enter an ingredient quantity.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const created = await createStockTransfer(orgId, {
        from_restaurant_id: Number(fromBranch),
        to_restaurant_id: Number(toBranch),
        lines: [{ ingredient_name: ingredientName, unit: transferUnit, quantity: transferQty }],
      });
      setLastTransfer(created);
      toast(`Transfer created: #${created.id}`);
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

  if (!hasOrgToken) {
    return (
      <div className={s.screen}>
        <PageHeader title="Branches" subtitle="Sign in with an organization account to manage branches" />
        <section className={s.card}>
          <div className={s.cardHead}>
            <h2>Organization access</h2>
            <span>Use this separate account for branch-wide sales, inventory, and transfers.</span>
          </div>
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
              <input type="password" value={loginPassword} onChange={(e) => setLoginPassword(e.target.value)} />
            </label>
          </div>
          <div className={s.actions}>
            <Button type="button" variant="ghost" disabled={submitting} onClick={() => void submitAuth("signup")}>
              Create organization
            </Button>
            <Button type="button" disabled={submitting} onClick={() => void submitAuth("login")}>
              Sign in
            </Button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className={s.screen}>
      <PageHeader
        title="Branches"
        subtitle="Multi-branch sales, inventory pressure, and stock transfers"
        right={
          <div className={s.actions}>
            <input
              className={s.date}
              aria-label="Rollup date"
              type="date"
              value={targetDate}
              onChange={(e) => setTargetDate(e.target.value)}
            />
            <Button type="button" variant="ghost" onClick={() => void load()}>
              Refresh
            </Button>
          </div>
        }
      />

      {loadError && <SectionBanner tone="warning">{loadError}</SectionBanner>}

      <section className={s.metrics}>
        <div className={s.metric}>
          <span>Branches</span>
          <strong>{branches.length}</strong>
        </div>
        <div className={s.metric}>
          <span>Sales on selected date</span>
          <strong>{money(rollup?.total_gross_sales_aed)}</strong>
        </div>
        <div className={s.metric}>
          <span>Inventory value</span>
          <strong>{money(summary?.total_inventory_value_aed)}</strong>
        </div>
        <div className={s.metric}>
          <span>Low-stock items</span>
          <strong>{summary?.total_low_stock_count ?? 0}</strong>
        </div>
      </section>

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Branch comparison</h2>
            <span>Sales, order count, inventory value, and low-stock pressure.</span>
          </div>
          <div className={s.range}>
            <label>
              <span>From</span>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </label>
            <label>
              <span>To</span>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </label>
            <Button type="button" variant="ghost" onClick={() => void load()}>
              Apply range
            </Button>
          </div>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Branch</th>
                  <th>Daily sales</th>
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
                      <td>{cmp ? `${cmp.order_count} orders` : "0 orders"}</td>
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
                {loaded && branches.length === 0 && (
                  <tr>
                    <td colSpan={6} className={s.empty}>No branches yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className={s.sideStack}>
          <section className={s.card}>
            <div className={s.cardHead}>
              <h2>Add branch</h2>
              <span>Create a restaurant branch under this organization.</span>
            </div>
            <div className={s.formGridSingle}>
              <label>
                <span>Branch name</span>
                <input aria-label="Branch name" value={branchName} onChange={(e) => setBranchName(e.target.value)} />
              </label>
              <label>
                <span>Latitude</span>
                <input aria-label="Latitude" value={lat} onChange={(e) => setLat(e.target.value)} />
              </label>
              <label>
                <span>Longitude</span>
                <input aria-label="Longitude" value={lng} onChange={(e) => setLng(e.target.value)} />
              </label>
            </div>
            <Button type="button" disabled={submitting} onClick={() => void submitBranch()}>
              Add branch
            </Button>
          </section>

          <section className={s.card}>
            <div className={s.cardHead}>
              <h2>Stock transfer</h2>
              <span>Move stock between branches with an auditable transfer record.</span>
            </div>
            <div className={s.formGridSingle}>
              <label>
                <span>From branch</span>
                <select aria-label="From branch" value={fromBranch} onChange={(e) => setFromBranch(e.target.value)}>
                  <option value="">Select branch</option>
                  {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
                </select>
              </label>
              <label>
                <span>To branch</span>
                <select aria-label="To branch" value={toBranch} onChange={(e) => setToBranch(e.target.value)}>
                  <option value="">Select branch</option>
                  {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
                </select>
              </label>
              <label>
                <span>Ingredient</span>
                <input aria-label="Ingredient" value={ingredientName} onChange={(e) => setIngredientName(e.target.value)} />
              </label>
              <div className={s.inlineFields}>
                <label>
                  <span>Unit</span>
                  <input aria-label="Transfer unit" value={transferUnit} onChange={(e) => setTransferUnit(e.target.value)} />
                </label>
                <label>
                  <span>Quantity</span>
                  <input aria-label="Quantity" value={transferQty} onChange={(e) => setTransferQty(e.target.value)} />
                </label>
              </div>
            </div>
            <div className={s.actions}>
              <Button type="button" disabled={submitting} onClick={() => void submitTransfer()}>
                Create transfer
              </Button>
              {lastTransfer && lastTransfer.status !== "completed" && (
                <Button type="button" variant="ghost" onClick={() => void completeTransfer()}>
                  Complete #{lastTransfer.id}
                </Button>
              )}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
