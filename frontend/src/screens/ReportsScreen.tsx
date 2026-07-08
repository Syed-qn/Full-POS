import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  getItemPerformance,
  getRetention,
  getSalesRollup,
  getZReport,
  itemPerformanceCsvUrl,
} from "../lib/reportsApi";
import type { ItemPerformanceRow, RetentionReport, SalesRollupRow, ZReport } from "../lib/types";
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
  const [rollup, setRollup] = useState<SalesRollupRow[]>([]);
  const [items, setItems] = useState<ItemPerformanceRow[]>([]);
  const [zDate, setZDate] = useState(end);
  const [zReport, setZReport] = useState<ZReport | null>(null);
  const [retention, setRetention] = useState<RetentionReport | null>(null);

  async function reload() {
    try {
      const [rollupRows, itemRows] = await Promise.all([
        getSalesRollup(startDate, endDate, "daily"),
        getItemPerformance(startDate, endDate),
      ]);
      setRollup(rollupRows);
      setItems(itemRows);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load reports.", "error");
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
      toast(e instanceof Error ? e.message : "Could not load retention report.", "error");
    }
  }

  const totalRevenue = rollup.reduce((sum, r) => sum + Number(r.revenue_aed), 0);

  return (
    <div className={s.root}>
      <PageHeader title="Reports" subtitle="Sales, item performance, and cash closing" />

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
          <Button type="button" onClick={() => void reload()}>Refresh</Button>
        </div>
        <p>Total revenue: AED {totalRevenue.toFixed(2)}</p>
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
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Item performance</h3>
        <a href={itemPerformanceCsvUrl(startDate, endDate)} target="_blank" rel="noreferrer">
          Export CSV
        </a>
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
      </section>
    </div>
  );
}
