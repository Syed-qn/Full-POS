import { useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { SectionBanner } from "../components/SectionBanner";
import { toast } from "../components/Toaster";
import {
  bulkUpdateBranches,
  completeStockTransfer,
  createBranch,
  createCentralKitchenRequest,
  createOrgCustomer,
  createOrgMember,
  createOrgMenuItem,
  createOrgPromotion,
  createStockTransfer,
  creditOrgLoyalty,
  decideMenuPublish,
  getBranchComparison,
  getOrgIdFromToken,
  getOrgMe,
  getOrgToken,
  getOrganizationInventorySummary,
  getRegionReport,
  getRollupSales,
  getRoyaltyReport,
  listBranches,
  listCentralKitchenRequests,
  listOrgCustomers,
  listOrgMembers,
  listOrgMenuItems,
  loginOrganization,
  patchOrgMe,
  pushOrgPromotion,
  requestMenuPublish,
  signupOrganization,
  updateCentralKitchenStatus,
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
  const [branchRegion, setBranchRegion] = useState("");
  const [locale, setLocale] = useState<"en" | "ar">("en");
  const [royaltyPct, setRoyaltyPct] = useState("0");
  const [royalty, setRoyalty] = useState<{
    total_royalty_aed: string;
    total_revenue_aed: string;
    branches: Array<{ restaurant_name: string; royalty_aed: string; revenue_aed: string }>;
  } | null>(null);
  const [regions, setRegions] = useState<Array<{ region: string; revenue_aed: string; branch_count: number }>>([]);
  const [menuName, setMenuName] = useState("");
  const [menuPrice, setMenuPrice] = useState("15.00");
  const [menuItems, setMenuItems] = useState<Array<{ id: number; name: string; base_price_aed: string }>>([]);
  const [promoCode, setPromoCode] = useState("");
  const [promoAmt, setPromoAmt] = useState("10.00");
  const [customers, setCustomers] = useState<Array<{ phone: string; loyalty_points: number; name?: string | null }>>([]);
  const [custPhone, setCustPhone] = useState("+9715");
  const [members, setMembers] = useState<Array<{ name: string; role: string; email: string }>>([]);
  const [ckRequests, setCkRequests] = useState<Array<{ id: number; status: string; from_restaurant_id: number }>>([]);
  const [ckFrom, setCkFrom] = useState("");
  const [ckItem, setCkItem] = useState("");

  const orgId = getOrgIdFromToken();
  const t = (en: string, ar: string) => (locale === "ar" ? ar : en);

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
      const [
        branchRows,
        rollupReport,
        inventoryReport,
        comparisonRows,
        me,
        roy,
        reg,
        menu,
        custs,
        mems,
        cks,
      ] = await Promise.all([
        listBranches(),
        getRollupSales(targetDate),
        getOrganizationInventorySummary(),
        currentOrgId
          ? getBranchComparison(currentOrgId, startDate, endDate)
          : Promise.resolve([] as BranchComparisonOut[]),
        getOrgMe().catch(() => null),
        getRoyaltyReport(startDate, endDate).catch(() => null),
        getRegionReport(startDate, endDate).catch(() => []),
        listOrgMenuItems().catch(() => []),
        listOrgCustomers().catch(() => []),
        listOrgMembers().catch(() => []),
        listCentralKitchenRequests().catch(() => []),
      ]);
      setBranches(branchRows);
      setRollup(rollupReport);
      setSummary(inventoryReport);
      setComparison(comparisonRows);
      setFromBranch((prev) => prev || String(branchRows[0]?.id ?? ""));
      setToBranch((prev) => prev || String(branchRows[1]?.id ?? branchRows[0]?.id ?? ""));
      setCkFrom((prev) => prev || String(branchRows[0]?.id ?? ""));
      if (me) {
        setRoyaltyPct(me.royalty_pct);
        if (me.default_locale === "ar" || me.default_locale === "en") setLocale(me.default_locale);
      }
      setRoyalty(
        roy && typeof roy === "object" && !Array.isArray(roy) && "branches" in roy
          ? (roy as typeof royalty)
          : null,
      );
      setRegions(Array.isArray(reg) ? reg : []);
      setMenuItems(Array.isArray(menu) ? menu : []);
      setCustomers(Array.isArray(custs) ? custs : []);
      setMembers(Array.isArray(mems) ? mems : []);
      setCkRequests(Array.isArray(cks) ? cks : []);
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
      const created = await createBranch({
        name: branchName,
        lat: parsedLat,
        lng: parsedLng,
        region: branchRegion || undefined,
        locale,
      });
      setBranches((prev) => [...prev, created]);
      setBranchName("");
      setLat("");
      setLng("");
      setBranchRegion("");
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
        title={t("Branches", "الفروع")}
        subtitle={t(
          "Franchise HQ — menu publish, royalty, regions, shared loyalty, central kitchen",
          "المقر — قائمة مركزية، رسوم الامتياز، المناطق، الولاء، المطبخ المركزي",
        )}
        right={
          <div className={s.actions}>
            <select
              aria-label="Dashboard language"
              value={locale}
              onChange={(e) => setLocale(e.target.value as "en" | "ar")}
            >
              <option value="en">EN</option>
              <option value="ar">AR</option>
            </select>
            <input
              className={s.date}
              aria-label="Rollup date"
              type="date"
              value={targetDate}
              onChange={(e) => setTargetDate(e.target.value)}
            />
            <Button type="button" variant="ghost" onClick={() => void load()}>
              {t("Refresh", "تحديث")}
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
              <label>
                <span>Region</span>
                <input aria-label="Branch region" value={branchRegion} onChange={(e) => setBranchRegion(e.target.value)} placeholder="dubai" />
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

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>{t("Central menu & publish", "القائمة المركزية")}</h2>
            <span>HQ master items → branch menus with approval</span>
          </div>
          <div className={s.formGridSingle}>
            <label>
              <span>Dish name</span>
              <input value={menuName} onChange={(e) => setMenuName(e.target.value)} />
            </label>
            <label>
              <span>Base price AED</span>
              <input value={menuPrice} onChange={(e) => setMenuPrice(e.target.value)} />
            </label>
          </div>
          <div className={s.actions}>
            <Button
              type="button"
              disabled={submitting}
              onClick={async () => {
                if (!menuName.trim()) return;
                setSubmitting(true);
                try {
                  await createOrgMenuItem({ name: menuName, base_price_aed: menuPrice });
                  setMenuName("");
                  setMenuItems(await listOrgMenuItems());
                  toast("Menu item added");
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Failed", "error");
                } finally {
                  setSubmitting(false);
                }
              }}
            >
              Add master item
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={async () => {
                try {
                  const job = await requestMenuPublish({
                    target_restaurant_ids: branches.map((b) => b.id),
                  });
                  const done = await decideMenuPublish(job.id, true);
                  toast(`Menu publish: ${done.status}`);
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Publish failed", "error");
                }
              }}
            >
              Request &amp; approve publish
            </Button>
          </div>
          <ul>
            {menuItems.map((m) => (
              <li key={m.id}>
                {m.name} — AED {m.base_price_aed}
              </li>
            ))}
          </ul>
        </div>

        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>{t("Franchise royalty", "رسوم الامتياز")}</h2>
            <span>Royalty % of delivered sales by branch</span>
          </div>
          <div className={s.formGridSingle}>
            <label>
              <span>Royalty %</span>
              <input value={royaltyPct} onChange={(e) => setRoyaltyPct(e.target.value)} />
            </label>
          </div>
          <Button
            type="button"
            variant="ghost"
            onClick={async () => {
              try {
                await patchOrgMe({ royalty_pct: royaltyPct, default_locale: locale });
                setRoyalty(await getRoyaltyReport(startDate, endDate));
                toast("Royalty settings saved");
              } catch (e) {
                toast(e instanceof Error ? e.message : "Failed", "error");
              }
            }}
          >
            Save &amp; load royalty report
          </Button>
          {royalty && (
            <ul>
              <li>
                Total royalty: {money(royalty.total_royalty_aed)} on {money(royalty.total_revenue_aed)}
              </li>
              {royalty.branches.map((b) => (
                <li key={b.restaurant_name}>
                  {b.restaurant_name}: {money(b.royalty_aed)}
                </li>
              ))}
            </ul>
          )}
          <h3 style={{ marginTop: 12 }}>{t("Regions", "المناطق")}</h3>
          <ul>
            {regions.map((r) => (
              <li key={r.region}>
                {r.region}: {r.branch_count} branches · {money(r.revenue_aed)}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>{t("Shared customers & loyalty", "العملاء والولاء")}</h2>
            <span>Org-wide phone identity across branches</span>
          </div>
          <div className={s.formGridSingle}>
            <label>
              <span>Phone</span>
              <input value={custPhone} onChange={(e) => setCustPhone(e.target.value)} />
            </label>
          </div>
          <div className={s.actions}>
            <Button
              type="button"
              onClick={async () => {
                try {
                  await createOrgCustomer({ phone: custPhone, preferred_locale: locale });
                  await creditOrgLoyalty({ phone: custPhone, points: 10, spend_aed: "25" });
                  setCustomers(await listOrgCustomers());
                  toast("Customer + loyalty credited");
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Failed", "error");
                }
              }}
            >
              Upsert + credit 10 pts
            </Button>
          </div>
          <ul>
            {customers.map((c) => (
              <li key={c.phone}>
                {c.name ?? c.phone}: {c.loyalty_points} pts
              </li>
            ))}
          </ul>
        </div>

        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>{t("HQ promotions", "العروض")}</h2>
            <span>Push multi-use coupons to branches</span>
          </div>
          <div className={s.formGridSingle}>
            <label>
              <span>Code</span>
              <input value={promoCode} onChange={(e) => setPromoCode(e.target.value)} />
            </label>
            <label>
              <span>Discount AED</span>
              <input value={promoAmt} onChange={(e) => setPromoAmt(e.target.value)} />
            </label>
          </div>
          <Button
            type="button"
            onClick={async () => {
              if (!promoCode.trim()) return;
              try {
                const p = await createOrgPromotion({
                  code: promoCode,
                  title: promoCode,
                  discount_aed: promoAmt,
                  target_restaurant_ids: branches.map((b) => b.id),
                });
                await pushOrgPromotion(p.id);
                toast(`Promotion ${p.code} pushed`);
                setPromoCode("");
              } catch (e) {
                toast(e instanceof Error ? e.message : "Failed", "error");
              }
            }}
          >
            Create &amp; push promo
          </Button>

          <h3 style={{ marginTop: 16 }}>{t("HQ members / roles", "الأدوار")}</h3>
          <Button
            type="button"
            variant="ghost"
            onClick={async () => {
              if (!branches[0]) return;
              try {
                await createOrgMember({
                  email: `mgr${Date.now()}@branch.local`,
                  name: "Branch Manager",
                  role: "branch_manager",
                  branch_ids: [branches[0].id],
                });
                setMembers(await listOrgMembers());
                toast("Member added");
              } catch (e) {
                toast(e instanceof Error ? e.message : "Failed", "error");
              }
            }}
          >
            Add sample branch manager
          </Button>
          <ul>
            {members.map((m) => (
              <li key={m.email}>
                {m.name} · {m.role} · {m.email}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>{t("Central kitchen", "المطبخ المركزي")}</h2>
            <span>Branch production requests</span>
          </div>
          <div className={s.formGridSingle}>
            <label>
              <span>Requesting branch</span>
              <select
                aria-label="Kitchen requesting branch"
                value={ckFrom}
                onChange={(e) => setCkFrom(e.target.value)}
              >
                {branches.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                    {b.is_central_kitchen ? " (CK)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Item</span>
              <input value={ckItem} onChange={(e) => setCkItem(e.target.value)} placeholder="Dough 10kg" />
            </label>
          </div>
          <Button
            type="button"
            onClick={async () => {
              if (!ckFrom || !ckItem.trim()) return;
              try {
                await createCentralKitchenRequest({
                  from_restaurant_id: Number(ckFrom),
                  items: [{ name: ckItem, qty: 1 }],
                });
                setCkRequests(await listCentralKitchenRequests());
                setCkItem("");
                toast("Kitchen request created");
              } catch (e) {
                toast(e instanceof Error ? e.message : "Failed — designate a central kitchen", "error");
              }
            }}
          >
            Submit request
          </Button>
          <ul>
            {ckRequests.map((r) => (
              <li key={r.id}>
                #{r.id} from {r.from_restaurant_id} · {r.status}{" "}
                {r.status === "pending" && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={async () => {
                      await updateCentralKitchenStatus(r.id, "in_production");
                      setCkRequests(await listCentralKitchenRequests());
                    }}
                  >
                    Start production
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </div>

        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>{t("Bulk updates", "تحديث جماعي")}</h2>
            <span>Apply locale/currency across selected locations</span>
          </div>
          <Button
            type="button"
            variant="ghost"
            onClick={async () => {
              try {
                await bulkUpdateBranches({
                  restaurant_ids: branches.map((b) => b.id),
                  action: "set_locale",
                  payload: { locale },
                });
                await load();
                toast(`Locale set to ${locale} on all branches`);
              } catch (e) {
                toast(e instanceof Error ? e.message : "Failed", "error");
              }
            }}
          >
            Set all branches locale = {locale}
          </Button>
        </div>
      </section>
    </div>
  );
}
