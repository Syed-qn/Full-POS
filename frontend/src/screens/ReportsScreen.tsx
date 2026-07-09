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
  const [avgDel, setAvgDel] = useState<{ avg_delivery_minutes: number | null; late_pct: number } | null>(null);
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

  return (
    <div className={s.root}>
      <PageHeader title="Reports" subtitle="Owner dashboard — sales, P&L, channels, tax, voids, Excel & WhatsApp daily report" />

      {!loaded && <p className={s.loading}>Loading reports…</p>}
      {loadError && <p className={s.error} role="alert">{loadError}</p>}

      <section className={s.card}>
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
          <Button type="button" onClick={() => void reload()}>Refresh</Button>
          <Button type="button" variant="ghost" disabled={exportingXlsx} onClick={() => void exportXlsx()}>
            {exportingXlsx ? "Exporting…" : "Export Excel"}
          </Button>
        </div>
        <p>Total revenue: AED {totalRevenue.toFixed(2)}</p>
        {aov && <p>AOV: AED {aov.aov_aed} · Orders: {aov.order_count}</p>}
        {forecast && (
          <p>
            Forecast ({forecast.predicted_order_count} orders): AED {forecast.forecasted_sales_aed}
          </p>
        )}
        {loaded && !loadError && rollup.length === 0 ? (
          <p className={s.empty}>No data for this range.</p>
        ) : (
          <table className={s.table}>
            <thead><tr><th>Period</th><th>Revenue</th><th>Orders</th></tr></thead>
            <tbody>
              {rollup.map((r) => (
                <tr key={r.bucket}>
                  <td>{r.bucket}</td>
                  <td>AED {Number(r.revenue_aed).toFixed(2)}</td>
                  <td>{r.order_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Driver performance</h3>
        {driversLoaded && drivers.length === 0 ? (
          <p className={s.empty}>No deliveries in this range.</p>
        ) : (
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
                  <td>{d.delivery_count}</td>
                  <td>{d.avg_delivery_minutes ?? "—"}</td>
                  <td>
                    {d.late_count} ({d.late_pct}%)
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Item performance</h3>
        <Button type="button" variant="ghost" disabled={exportingCsv} onClick={() => void exportCsv()}>
          {exportingCsv ? "Exporting…" : "Export CSV"}
        </Button>
        {loaded && !loadError && items.length === 0 ? (
          <p className={s.empty}>No data for this range.</p>
        ) : (
          <table className={s.table}>
            <thead><tr><th>Dish</th><th>Orders</th><th>Revenue</th><th>Margin</th></tr></thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.dish_name}>
                  <td>{it.dish_name}</td>
                  <td>{it.order_count}</td>
                  <td>AED {Number(it.revenue_aed).toFixed(2)}</td>
                  <td>AED {Number(it.margin_aed).toFixed(2)} ({it.margin_pct}%)</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Z-report / cash closing</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Date</span>
            <input aria-label="Z-report date" type="date" value={zDate} onChange={(e) => setZDate(e.target.value)} />
          </label>
          <Button type="button" variant="ghost" onClick={() => void loadZReport()}>
            Load Z-report
          </Button>
        </div>
        {zReport && (
          <ul>
            <li>Gross sales: AED {Number(zReport.gross_sales_aed).toFixed(2)}</li>
            <li>Discounts: AED {Number(zReport.total_discounts_aed).toFixed(2)}</li>
            <li>COD collected: AED {Number(zReport.cod_collected_aed).toFixed(2)}</li>
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Customer retention</h3>
        <Button type="button" variant="ghost" onClick={() => void loadRetention()}>
          Load retention
        </Button>
        {retention && (
          <ul>
            <li>Repeat rate: {retention.repeat_rate_pct}%</li>
            <li>New customers: {retention.new_customers}</li>
            <li>Returning customers: {retention.returning_customers}</li>
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
          <Button type="button" variant="ghost" onClick={() => void loadLaborHours()}>
            Load labor hours
          </Button>
        </div>
        {laborHours.length > 0 && (
          <ul>
            {laborHours.map((row) => (
              <li key={row.staff_id}>
                {row.name}: {row.hours}h
              </li>
            ))}
          </ul>
        )}
        {laborLoaded && laborHours.length === 0 && <p className={s.empty}>No data for this date.</p>}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Prep time</h3>
        <div className={s.form}>
          <Button type="button" variant="ghost" onClick={() => void loadPrepTimeByItem()}>
            Load prep time by item
          </Button>
          <Button type="button" variant="ghost" onClick={() => void loadPrepTimeByStaff()}>
            Load prep time by staff
          </Button>
        </div>
        {prepByItemLoaded && prepByItem.length === 0 && <p className={s.empty}>No prep-time data by item for this range.</p>}
        {prepByStaffLoaded && prepByStaff.length === 0 && <p className={s.empty}>No prep-time data by staff for this range.</p>}
        {prepByItem.length > 0 && (
          <>
            <h4>By item</h4>
            <ul>
              {prepByItem.map((row) => (
                <li key={row.key}>
                  {row.key}: {row.avg_prep_minutes} min avg ({row.ticket_count} tickets)
                </li>
              ))}
            </ul>
          </>
        )}
        {prepByStaff.length > 0 && (
          <>
            <h4>By staff/station</h4>
            <ul>
              {prepByStaff.map((row) => (
                <li key={row.key}>
                  {row.key}: {row.avg_prep_minutes} min avg ({row.ticket_count} tickets)
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Sales by channel</h3>
        {channels.length === 0 ? (
          <p className={s.empty}>No channel data.</p>
        ) : (
          <table className={s.table}>
            <thead><tr><th>Channel</th><th>Orders</th><th>Revenue</th></tr></thead>
            <tbody>
              {channels.map((c) => (
                <tr key={c.channel}>
                  <td>{c.channel}</td>
                  <td>{c.order_count}</td>
                  <td>AED {Number(c.revenue_aed).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Sales by category / waiter / payment</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
          <div>
            <h4>Category</h4>
            <ul>
              {categories.map((c) => (
                <li key={c.category}>{c.category}: {c.qty} · AED {c.revenue_aed}</li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Waiter</h4>
            <ul>
              {waiters.map((w) => (
                <li key={w.staff_name}>{w.staff_name}: {w.order_count} · AED {w.revenue_aed}</li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Payment method</h4>
            <ul>
              {payments.map((p) => (
                <li key={p.tender_type}>{p.tender_type}: {p.txn_count} · net AED {p.net_aed}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>P&amp;L · tax · discounts · voids · refunds · waste</h3>
        <ul>
          {profit && (
            <li>
              Gross profit: AED {profit.gross_profit_aed} ({profit.gross_margin_pct}% margin) · food cost AED {profit.food_cost_aed}
            </li>
          )}
          {foodCost && (
            <li>Food cost: AED {foodCost.total_food_cost_aed} ({foodCost.food_cost_pct}%)</li>
          )}
          {tax && (
            <li>VAT: AED {tax.vat_total_aed} · net taxable AED {tax.taxable_net_aed}</li>
          )}
          {discounts && (
            <li>
              Discounts: AED {discounts.total_discounts_aed} across {discounts.discounted_order_count} orders
            </li>
          )}
          {voids && <li>Voids: {voids.void_count} · AED {voids.void_value_aed}</li>}
          {refunds && (
            <li>Refunds: {refunds.refund_txn_count} · AED {refunds.refunded_total_aed}</li>
          )}
          {waste && (
            <li>Wastage events: {waste.event_count} · est. cost AED {waste.estimated_cost_aed}</li>
          )}
          {avgDel && (
            <li>
              Avg delivery: {avgDel.avg_delivery_minutes ?? "n/a"} min · late {avgDel.late_pct}%
            </li>
          )}
          {peak && (
            <li>
              Peak hour: {peak.peak_bucket ?? "—"} ({peak.peak_order_count} orders)
            </li>
          )}
        </ul>
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Top / slow / dead menu items</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
          <div>
            <h4>Top selling</h4>
            <ul>
              {topItems.map((t) => (
                <li key={t.dish_name}>{t.dish_name} ({t.order_count})</li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Slow moving</h4>
            <ul>
              {slowItems.map((t) => (
                <li key={t.dish_name}>{t.dish_name} ({t.order_count})</li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Dead (zero sales)</h4>
            <ul>
              {deadItems.map((t) => (
                <li key={t.dish_name}>{t.dish_name}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>WhatsApp daily owner report</h3>
        <p>Sends today&apos;s Z-summary, AOV, delivery KPIs, top items &amp; channels to the owner WhatsApp.</p>
        <Button type="button" onClick={() => void sendOwnerReport()}>
          Send owner WhatsApp report
        </Button>
      </section>
    </div>
  );
}
