import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  fetchExcelExport,
  fetchItemPerformanceCsv,
  getAov,
  getAvgDeliveryTime,
  getDeadMenuItems,
  getDiscountReport,
  getDriverPerformance,
  getFoodCost,
  getForecastedSales,
  getGrossProfit,
  getItemPerformance,
  getLaborHours,
  getPeakHours,
  getPrepTimeByItem,
  getPrepTimeByStaff,
  getRefundReport,
  getRetention,
  getSalesByCategory,
  getSalesByChannel,
  getSalesByPayment,
  getSalesByWaiter,
  getSalesRollup,
  getSlowMoving,
  getTaxReport,
  getTopSelling,
  getVoidReport,
  getWastageReport,
  getZReport,
  sendOwnerWhatsappReport,
} from "../lib/reportsApi";
import type {
  DriverPerformanceRow,
  ItemPerformanceRow,
  LaborHoursRow,
  PrepTimeRow,
  RetentionReport,
  SalesRollupRow,
  ZReport,
} from "../lib/types";
import s from "./ReportsScreen.module.css";

function defaultRange() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 7);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function money(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  return `AED ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function count(value: number | null | undefined): string {
  return (value ?? 0).toLocaleString();
}

export function ReportsScreen() {
  const { start, end } = defaultRange();
  const [startDate, setStartDate] = useState(start);
  const [endDate, setEndDate] = useState(end);
  const [granularity, setGranularity] = useState<"hourly" | "daily" | "weekly" | "monthly">("daily");
  const [rollup, setRollup] = useState<SalesRollupRow[]>([]);
  const [items, setItems] = useState<ItemPerformanceRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [zDate, setZDate] = useState(end);
  const [zReport, setZReport] = useState<ZReport | null>(null);
  const [retention, setRetention] = useState<RetentionReport | null>(null);
  const [retentionLoaded, setRetentionLoaded] = useState(false);
  const [laborDate, setLaborDate] = useState(end);
  const [laborHours, setLaborHours] = useState<LaborHoursRow[]>([]);
  const [laborLoaded, setLaborLoaded] = useState(false);
  const [prepByItem, setPrepByItem] = useState<PrepTimeRow[]>([]);
  const [prepByItemLoaded, setPrepByItemLoaded] = useState(false);
  const [prepByStaff, setPrepByStaff] = useState<PrepTimeRow[]>([]);
  const [prepByStaffLoaded, setPrepByStaffLoaded] = useState(false);
  const [exportingCsv, setExportingCsv] = useState(false);
  const [exportingXlsx, setExportingXlsx] = useState(false);
  const [drivers, setDrivers] = useState<DriverPerformanceRow[]>([]);
  const [driversLoaded, setDriversLoaded] = useState(false);

  // Category 10 extended
  const [channels, setChannels] = useState<Array<{ channel: string; order_count: number; revenue_aed: string }>>([]);
  const [categories, setCategories] = useState<Array<{ category: string; qty: number; revenue_aed: string }>>([]);
  const [waiters, setWaiters] = useState<Array<{ staff_name: string; order_count: number; revenue_aed: string }>>([]);
  const [payments, setPayments] = useState<Array<{ tender_type: string; txn_count: number; net_aed: string }>>([]);
  const [profit, setProfit] = useState<{ gross_profit_aed: string; gross_margin_pct: number; food_cost_aed: string } | null>(null);
  const [foodCost, setFoodCost] = useState<{ total_food_cost_aed: string; food_cost_pct: number } | null>(null);
  const [discounts, setDiscounts] = useState<{ total_discounts_aed: string; discounted_order_count: number } | null>(null);
  const [voids, setVoids] = useState<{ void_count: number; void_value_aed: string } | null>(null);
  const [refunds, setRefunds] = useState<{ refund_txn_count: number; refunded_total_aed: string } | null>(null);
  const [waste, setWaste] = useState<{ event_count: number; estimated_cost_aed: string } | null>(null);
  const [topItems, setTopItems] = useState<Array<{ dish_name: string; order_count: number }>>([]);
  const [slowItems, setSlowItems] = useState<Array<{ dish_name: string; order_count: number }>>([]);
  const [deadItems, setDeadItems] = useState<Array<{ dish_name: string }>>([]);
  const [aov, setAov] = useState<{ aov_aed: string; order_count: number } | null>(null);
  const [avgDel, setAvgDel] = useState<{ avg_delivery_minutes: number | null; p50_minutes: number | null; late_pct: number } | null>(null);
  const [peak, setPeak] = useState<{ peak_bucket: string | null; peak_order_count: number } | null>(null);
  const [tax, setTax] = useState<{ vat_total_aed: string; taxable_net_aed: string } | null>(null);
  const [forecast, setForecast] = useState<{ forecasted_sales_aed: string; predicted_order_count: number } | null>(null);

  async function reload() {
    setLoadError(null);
    try {
      const [
        rollupRows,
        itemRows,
        driverRows,
        ch,
        cat,
        wait,
        pay,
        gp,
        fc,
        disc,
        vo,
        ref,
        was,
        top,
        slow,
        dead,
        aovR,
        del,
        pk,
        tx,
        fcst,
      ] = await Promise.all([
        getSalesRollup(startDate, endDate, granularity),
        getItemPerformance(startDate, endDate),
        getDriverPerformance(startDate, endDate).catch(() => []),
        getSalesByChannel(startDate, endDate).catch(() => []),
        getSalesByCategory(startDate, endDate).catch(() => []),
        getSalesByWaiter(startDate, endDate).catch(() => []),
        getSalesByPayment(startDate, endDate).catch(() => []),
        getGrossProfit(startDate, endDate).catch(() => null),
        getFoodCost(startDate, endDate).catch(() => null),
        getDiscountReport(startDate, endDate).catch(() => null),
        getVoidReport(startDate, endDate).catch(() => null),
        getRefundReport(startDate, endDate).catch(() => null),
        getWastageReport(startDate, endDate).catch(() => null),
        getTopSelling(startDate, endDate).catch(() => []),
        getSlowMoving(startDate, endDate).catch(() => []),
        getDeadMenuItems(startDate, endDate).catch(() => []),
        getAov(startDate, endDate).catch(() => null),
        getAvgDeliveryTime(startDate, endDate).catch(() => null),
        getPeakHours(startDate, endDate).catch(() => null),
        getTaxReport(startDate, endDate).catch(() => null),
        getForecastedSales().catch(() => null),
      ]);
      setRollup(rollupRows);
      setItems(itemRows);
      setDrivers(driverRows);
      setDriversLoaded(true);
      setChannels(ch);
      setCategories(cat);
      setWaiters(wait);
      setPayments(pay);
      setProfit(gp);
      setFoodCost(fc ? { total_food_cost_aed: fc.total_food_cost_aed, food_cost_pct: fc.food_cost_pct } : null);
      setDiscounts(disc);
      setVoids(vo);
      setRefunds(ref);
      setWaste(was);
      setTopItems(top);
      setSlowItems(slow);
      setDeadItems(dead);
      setAov(aovR);
      setAvgDel(del);
      setPeak(pk);
      setTax(tx);
      setForecast(fcst);
    } catch (e) {
      setRollup([]);
      setItems([]);
      setLoadError(e instanceof Error ? e.message : "Could not load reports.");
      toast(e instanceof Error ? e.message : "Could not load reports.", "error");
    } finally {
      setLoaded(true);
    }
  }

  async function exportCsv() {
    setExportingCsv(true);
    try {
      const blob = await fetchItemPerformanceCsv(startDate, endDate);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `item-performance-${startDate}-to-${endDate}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not export CSV.", "error");
    } finally {
      setExportingCsv(false);
    }
  }

  async function exportXlsx() {
    setExportingXlsx(true);
    try {
      const blob = await fetchExcelExport(startDate, endDate);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `reports-${startDate}-to-${endDate}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast("Excel workbook downloaded");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Excel export failed", "error");
    } finally {
      setExportingXlsx(false);
    }
  }

  async function sendOwnerReport() {
    try {
      const res = await sendOwnerWhatsappReport(zDate);
      toast(`Owner report ${res.status} → ${res.to_phone}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Owner report failed", "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load only
  }, []);

  async function loadZReport() {
    try {
      const report = await getZReport(zDate);
      setZReport(report);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load Z-report.", "error");
    }
  }

  async function loadRetention() {
    try {
      const report = await getRetention(startDate, endDate);
      setRetention(report);
    } catch (e) {
      setRetention(null);
      toast(e instanceof Error ? e.message : "Could not load retention report.", "error");
    } finally {
      setRetentionLoaded(true);
    }
  }

  async function loadLaborHours() {
    try {
      const rows = await getLaborHours(laborDate);
      setLaborHours(rows);
    } catch (e) {
      setLaborHours([]);
      toast(e instanceof Error ? e.message : "Could not load labor hours.", "error");
    } finally {
      setLaborLoaded(true);
    }
  }

  async function loadPrepTimeByItem() {
    try {
      const rows = await getPrepTimeByItem(startDate, endDate);
      setPrepByItem(rows);
    } catch (e) {
      setPrepByItem([]);
      toast(e instanceof Error ? e.message : "Could not load prep time by item.", "error");
    } finally {
      setPrepByItemLoaded(true);
    }
  }

  async function loadPrepTimeByStaff() {
    try {
      const rows = await getPrepTimeByStaff(startDate, endDate);
      setPrepByStaff(rows);
    } catch (e) {
      setPrepByStaff([]);
      toast(e instanceof Error ? e.message : "Could not load prep time by staff.", "error");
    } finally {
      setPrepByStaffLoaded(true);
    }
  }

  const totalRevenue = rollup.reduce((sum, r) => sum + Number(r.revenue_aed), 0);
  const totalOrders =
    aov?.order_count ?? rollup.reduce((sum, r) => sum + Number(r.order_count ?? 0), 0);

  return (
    <div className={s.root}>
      <PageHeader
        title="Reports"
        subtitle={`Owner dashboard · ${startDate} → ${endDate}`}
        right={
          <Button type="button" size="md" onClick={() => void sendOwnerReport()}>
            Send WhatsApp
          </Button>
        }
      />

      {!loaded && <ReportsSkeleton />}

      {loaded && (
      <>
      {loadError && <p className={s.error} role="alert">{loadError}</p>}

      {/* Headline numbers for the selected range — the owner's at-a-glance line.
          Gross profit tile intentionally omitted: with no item costs configured
          it can only show "—", so it's carried in the P&L card instead. */}
      <section className={s.kpis} data-testid="reports-kpis">
        <div className={s.kpi}>
          <span className={s.kpiLabel}>Revenue</span>
          <span className={s.kpiValue}>{money(totalRevenue)}</span>
          <span className={s.kpiSub}>{count(totalOrders)} orders</span>
        </div>
        <div className={s.kpi}>
          <span className={s.kpiLabel}>Avg order value</span>
          <span className={s.kpiValue}>{aov ? money(aov.aov_aed) : "—"}</span>
          <span className={s.kpiSub}>across the range</span>
        </div>
        <div className={s.kpi}>
          <span className={s.kpiLabel}>VAT collected</span>
          <span className={s.kpiValue}>{tax ? money(tax.vat_total_aed) : "—"}</span>
          <span className={s.kpiSub}>{tax ? `net ${money(tax.taxable_net_aed)}` : "—"}</span>
        </div>
        <div className={s.kpi}>
          {/* Median, not mean: a few orders with bad timestamps (multi-hour
              "deliveries") skew the average wildly, so the typical (p50) time is
              the honest headline. */}
          <span className={s.kpiLabel}>Median delivery</span>
          <span className={s.kpiValue}>
            {avgDel?.p50_minutes != null ? `${avgDel.p50_minutes} min` : "—"}
          </span>
          {avgDel && (
            <span className={`${s.kpiSub} ${avgDel.late_pct > 0 ? s.neg : s.pos}`}>
              {avgDel.late_pct}% late
            </span>
          )}
        </div>
      </section>

      <div className={s.bento}>
      <section className={`${s.card} ${s.wide}`}>
        <h3 className={s.cardTitle}>Sales rollup</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Start date</span>
            <input aria-label="Report start date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>End date</span>
            <input aria-label="Report end date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>Granularity</span>
            <select
              aria-label="Sales granularity"
              value={granularity}
              onChange={(e) => setGranularity(e.target.value as typeof granularity)}
            >
              <option value="hourly">Hourly</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </label>
          <Button type="button" size="md" onClick={() => void reload()}>Refresh</Button>
          <Button type="button" size="md" variant="ghost" disabled={exportingXlsx} onClick={() => void exportXlsx()}>
            {exportingXlsx ? "Exporting…" : "Export Excel"}
          </Button>
        </div>
        {forecast && (
          <p className={s.hint}>
            Forecast: {money(forecast.forecasted_sales_aed)} on {count(forecast.predicted_order_count)} predicted orders ·
            {peak?.peak_bucket ? ` peak hour ${peak.peak_bucket} (${count(peak.peak_order_count)} orders)` : ""}
          </p>
        )}
        {loaded && !loadError && rollup.length === 0 ? (
          <p className={s.empty}>No data for this range.</p>
        ) : (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead><tr><th>Period</th><th>Revenue</th><th>Orders</th></tr></thead>
              <tbody>
                {rollup.map((r) => (
                  <tr key={r.bucket}>
                    <td>{r.bucket}</td>
                    <td>{money(r.revenue_aed)}</td>
                    <td>{count(Number(r.order_count))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className={s.twoCol}>
      <div className={s.col}>
      <section className={s.card}>
        <h3 className={s.cardTitle}>Driver performance</h3>
        {driversLoaded && drivers.length === 0 ? (
          <p className={s.empty}>No deliveries in this range.</p>
        ) : (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Rider</th>
                  <th>Deliveries</th>
                  <th>Avg min</th>
                  <th>Late %</th>
                </tr>
              </thead>
              <tbody>
                {drivers.map((d) => (
                  <tr key={d.rider_id}>
                    <td>{d.rider_name ?? `#${d.rider_id}`}</td>
                    <td>{count(d.delivery_count)}</td>
                    <td>{d.avg_delivery_minutes ?? "—"}</td>
                    <td>
                      {count(d.late_count)} ({d.late_pct}%)
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={s.card}>
        <div className={s.form}>
          <h3 className={s.cardTitle} style={{ margin: 0, flex: 1 }}>Item performance</h3>
          <Button type="button" size="md" variant="ghost" disabled={exportingCsv} onClick={() => void exportCsv()}>
            {exportingCsv ? "Exporting…" : "Export CSV"}
          </Button>
        </div>
        {loaded && !loadError && items.length === 0 ? (
          <p className={s.empty}>No data for this range.</p>
        ) : (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead><tr><th>Dish</th><th>Orders</th><th>Revenue</th><th>Margin</th></tr></thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.dish_name}>
                    <td>{it.dish_name}</td>
                    <td>{count(it.order_count)}</td>
                    <td>{money(it.revenue_aed)}</td>
                    <td>{money(it.margin_aed)} ({it.margin_pct}%)</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Z-report / cash closing</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Date</span>
            <input aria-label="Z-report date" type="date" value={zDate} onChange={(e) => setZDate(e.target.value)} />
          </label>
          <Button type="button" size="md" variant="ghost" onClick={() => void loadZReport()}>
            Load Z-report
          </Button>
        </div>
        {!zReport && (
          <p className={s.hint}>Pick a date and press <b>Load Z-report</b> for the day's cash closing.</p>
        )}
        {zReport && (
          <ul className={s.stats}>
            <li>Gross sales <b>{money(zReport.gross_sales_aed)}</b></li>
            <li>Discounts <b>{money(zReport.total_discounts_aed)}</b></li>
            <li>COD collected <b>{money(zReport.cod_collected_aed)}</b></li>
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Customer retention</h3>
        <Button type="button" size="md" variant="ghost" onClick={() => void loadRetention()}>
          Load retention
        </Button>
        {!retention && !retentionLoaded && (
          <p className={s.hint}>Load repeat rate and new vs returning customers for this range.</p>
        )}
        {retention && (
          <ul className={s.stats}>
            <li>Repeat rate <b>{retention.repeat_rate_pct}%</b></li>
            <li>New customers <b>{count(retention.new_customers)}</b></li>
            <li>Returning customers <b>{count(retention.returning_customers)}</b></li>
          </ul>
        )}
        {retentionLoaded && !retention && <p className={s.empty}>No data for this range.</p>}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Labor hours</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Date</span>
            <input aria-label="Labor hours date" type="date" value={laborDate} onChange={(e) => setLaborDate(e.target.value)} />
          </label>
          <Button type="button" size="md" variant="ghost" onClick={() => void loadLaborHours()}>
            Load labor hours
          </Button>
        </div>
        {!laborLoaded && (
          <p className={s.hint}>Pick a date and load hours worked per staff member.</p>
        )}
        {laborHours.length > 0 && (
          <ul className={s.stats}>
            {laborHours.map((row) => (
              <li key={row.staff_id}>
                {row.name} <b>{row.hours}h</b>
              </li>
            ))}
          </ul>
        )}
        {laborLoaded && laborHours.length === 0 && <p className={s.empty}>No data for this date.</p>}
      </section>

      </div>
      <div className={s.col}>
      <section className={s.card}>
        <h3 className={s.cardTitle}>Prep time</h3>
        <div className={s.form}>
          <Button type="button" size="md" variant="ghost" onClick={() => void loadPrepTimeByItem()}>
            Load prep time by item
          </Button>
          <Button type="button" size="md" variant="ghost" onClick={() => void loadPrepTimeByStaff()}>
            Load prep time by staff
          </Button>
        </div>
        {!prepByItemLoaded && !prepByStaffLoaded && (
          <p className={s.hint}>Load average prep minutes, by item or by staff / station.</p>
        )}
        {prepByItemLoaded && prepByItem.length === 0 && <p className={s.empty}>No prep-time data by item for this range.</p>}
        {prepByStaffLoaded && prepByStaff.length === 0 && <p className={s.empty}>No prep-time data by staff for this range.</p>}
        <div className={s.cols3}>
          {prepByItem.length > 0 && (
            <div>
              <h4>By item</h4>
              <ul className={s.miniList}>
                {prepByItem.map((row) => (
                  <li key={row.key}>
                    <span>{row.key}</span>
                    <span>{row.avg_prep_minutes} min · {count(row.ticket_count)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {prepByStaff.length > 0 && (
            <div>
              <h4>By staff / station</h4>
              <ul className={s.miniList}>
                {prepByStaff.map((row) => (
                  <li key={row.key}>
                    <span>{row.key}</span>
                    <span>{row.avg_prep_minutes} min · {count(row.ticket_count)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Sales by channel</h3>
        {channels.length === 0 ? (
          <p className={s.empty}>No channel data.</p>
        ) : (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead><tr><th>Channel</th><th>Orders</th><th>Revenue</th></tr></thead>
              <tbody>
                {channels.map((c) => (
                  <tr key={c.channel}>
                    <td>{c.channel}</td>
                    <td>{count(c.order_count)}</td>
                    <td>{money(c.revenue_aed)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Sales by category / waiter / payment</h3>
        <div className={s.cols3}>
          <div>
            <h4>Category</h4>
            <ul className={s.miniList}>
              {categories.map((c) => (
                <li key={c.category}><span>{c.category}</span><span>{money(c.revenue_aed)}</span></li>
              ))}
              {categories.length === 0 && <li className={s.empty}>No data</li>}
            </ul>
          </div>
          <div>
            <h4>Waiter</h4>
            <ul className={s.miniList}>
              {waiters.map((w) => (
                <li key={w.staff_name}><span>{w.staff_name}</span><span>{money(w.revenue_aed)}</span></li>
              ))}
              {waiters.length === 0 && <li className={s.empty}>No data</li>}
            </ul>
          </div>
          <div>
            <h4>Payment method</h4>
            <ul className={s.miniList}>
              {payments.map((p) => (
                <li key={p.tender_type}><span>{p.tender_type}</span><span>{money(p.net_aed)}</span></li>
              ))}
              {payments.length === 0 && <li className={s.empty}>No data</li>}
            </ul>
          </div>
        </div>
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>P&amp;L · tax · discounts · voids · refunds · waste</h3>
        <ul className={s.stats}>
          {profit && Number(profit.food_cost_aed) > 0 ? (
            <li>Gross profit <b>{money(profit.gross_profit_aed)} · {profit.gross_margin_pct}%</b></li>
          ) : (
            <li>Gross profit <b>— (set item costs)</b></li>
          )}
          {foodCost && Number(foodCost.total_food_cost_aed) > 0 && (
            <li>Food cost <b>{money(foodCost.total_food_cost_aed)} · {foodCost.food_cost_pct}%</b></li>
          )}
          {tax && (
            <li>VAT (net {money(tax.taxable_net_aed)}) <b>{money(tax.vat_total_aed)}</b></li>
          )}
          {discounts && (
            <li>Discounts ({count(discounts.discounted_order_count)} orders) <b>{money(discounts.total_discounts_aed)}</b></li>
          )}
          {voids && <li>Voids ({count(voids.void_count)}) <b>{money(voids.void_value_aed)}</b></li>}
          {refunds && (
            <li>Refunds ({count(refunds.refund_txn_count)}) <b>{money(refunds.refunded_total_aed)}</b></li>
          )}
          {waste && (
            <li>Wastage ({count(waste.event_count)} events) <b>{money(waste.estimated_cost_aed)}</b></li>
          )}
        </ul>
      </section>

      </div>
      </div>
      <section className={`${s.card} ${s.wide}`}>
        <h3 className={s.cardTitle}>Top / slow / dead menu items</h3>
        <div className={s.cols3}>
          <div>
            <h4>Top selling</h4>
            <ul className={s.miniList}>
              {topItems.map((t) => (
                <li key={t.dish_name}><span>{t.dish_name}</span><span>{count(t.order_count)}</span></li>
              ))}
              {topItems.length === 0 && <li className={s.empty}>No data</li>}
            </ul>
          </div>
          <div>
            <h4>Slow moving</h4>
            <ul className={s.miniList}>
              {slowItems.map((t) => (
                <li key={t.dish_name}><span>{t.dish_name}</span><span>{count(t.order_count)}</span></li>
              ))}
              {slowItems.length === 0 && <li className={s.empty}>No data</li>}
            </ul>
          </div>
          <div>
            <h4>Dead (zero sales)</h4>
            <ul className={s.miniList}>
              {deadItems.map((t) => (
                <li key={t.dish_name}><span>{t.dish_name}</span><span>—</span></li>
              ))}
              {deadItems.length === 0 && <li className={s.empty}>None 🎉</li>}
            </ul>
          </div>
        </div>
      </section>

      </div>
      </>
      )}
    </div>
  );
}

/** Skeleton mirroring the loaded layout: KPI strip + bento grid of cards, so the
 *  page doesn't reflow when data arrives. */
function ReportsSkeleton() {
  return (
    <div className={s.skWrap} data-testid="reports-skeleton" aria-busy="true" aria-label="Loading reports">
      <div className={s.kpis}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className={s.kpi}>
            <span className={`${s.sk} ${s.skLabel}`} />
            <span className={`${s.sk} ${s.skValue}`} />
            <span className={`${s.sk} ${s.skSub}`} />
          </div>
        ))}
      </div>
      <div className={s.bento}>
        {/* Mirror the real rhythm: a full-width band, then two-up cards, then a
            full-width band — so the page doesn't jump when data lands. */}
        {[
          { wide: true, bar: true, rows: 4 },
          { wide: false, bar: false, rows: 3 },
          { wide: false, bar: false, rows: 3 },
          { wide: false, bar: true, rows: 3 },
          { wide: false, bar: false, rows: 3 },
          { wide: true, bar: false, rows: 5 },
        ].map((c, i) => (
          <div key={i} className={`${s.card} ${c.wide ? s.wide : ""}`}>
            <span className={`${s.sk} ${s.skTitle}`} />
            {c.bar && <span className={`${s.sk} ${s.skBar}`} />}
            {Array.from({ length: c.rows }).map((_, r) => (
              <span
                key={r}
                className={`${s.sk} ${s.skRow}`}
                style={{ width: `${92 - r * 9}%` }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
