import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { SectionBanner } from "../components/SectionBanner";
import { buildForecast } from "../lib/forecast";
import { fetchOrders } from "../lib/ordersApi";
import type { OrderOut } from "../lib/types";
import s from "./ForecastScreen.module.css";

// Pull a generous slice so several weeks of same-weekday samples are available.
// If the feed returns exactly this many rows we treat history as truncated.
const HISTORY_LIMIT = 1000;
const WINDOWS = [28, 56, 90] as const;
type Window = (typeof WINDOWS)[number];

function toYMD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function addDays(d: Date, n: number): Date {
  const c = new Date(d);
  c.setDate(c.getDate() + n);
  return c;
}
function aed(n: number): string {
  return `AED ${Math.round(n).toLocaleString()}`;
}

function LoadingBars() {
  return (
    <div aria-busy="true" aria-label="Loading forecast">
      {Array.from({ length: 7 }).map((_, i) => (
        <span key={i} className={`${s.sk} ${s.skRow}`} style={{ width: `${95 - i * 8}%` }} />
      ))}
    </div>
  );
}

export function ForecastScreen() {
  const [windowDays, setWindowDays] = useState<Window>(28);
  const [orders, setOrders] = useState<OrderOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const bounds = useMemo(() => {
    const now = new Date();
    return {
      fromDate: toYMD(addDays(now, -(windowDays - 1))),
      toDate: toYMD(now),
    };
  }, [windowDays]);

  // Manual poll keyed on the window so changing it refetches immediately
  // (usePoll only re-subscribes on interval change, not on args change).
  useEffect(() => {
    let alive = true;
    setOrders(null);
    const run = () =>
      fetchOrders({
        fromDate: bounds.fromDate,
        toDate: bounds.toDate,
        previewBatch: false,
        limit: HISTORY_LIMIT,
      })
        .then((rows) => {
          if (!alive) return;
          setOrders(rows);
          setError(null);
        })
        .catch((e) => {
          if (alive) setError(e);
        });
    void run();
    const id = setInterval(() => void run(), 120_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [bounds.fromDate, bounds.toDate]);

  const model = useMemo(
    () =>
      orders
        ? buildForecast(orders, {
            today: new Date(),
            windowDays,
            truncated: orders.length >= HISTORY_LIMIT,
          })
        : null,
    [orders, windowDays],
  );

  const maxOrders = useMemo(
    () => (model ? Math.max(1, ...model.next7.map((d) => d.predictedOrders)) : 1),
    [model],
  );
  const maxPeriod = useMemo(
    () => (model ? Math.max(1, ...model.periods.map((p) => p.avgPerDay)) : 1),
    [model],
  );

  const hasHistory = model != null && model.historyOrders > 0;
  const confBadge =
    model?.confidence === "high"
      ? s.badgeHigh
      : model?.confidence === "medium"
        ? s.badgeMedium
        : s.badgeLow;

  return (
    <div className={s.screen}>
      <PageHeader
        title="Forecast"
        subtitle="Demand projected from your real order history"
        right={
          <div className={s.windowPicker} role="group" aria-label="History window">
            {WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                className={`${s.windowBtn} ${windowDays === w ? s.windowActive : ""}`}
                aria-pressed={windowDays === w}
                onClick={() => setWindowDays(w)}
              >
                {w} days
              </button>
            ))}
          </div>
        }
      />

      {error != null && (
        <SectionBanner tone="warning">Could not load history — retrying…</SectionBanner>
      )}
      {model?.truncated && (
        <SectionBanner tone="info">
          Showing the most recent {HISTORY_LIMIT.toLocaleString()} orders — older history in
          this window may be excluded. Try a shorter window for the fullest picture.
        </SectionBanner>
      )}

      {/* ── KPI strip ──────────────────────────────────────────────── */}
      <div className={s.kpiRow}>
        <div className={s.kpi}>
          <div className={s.kpiNum}>
            {model ? Math.round(model.avgOrdersPerDay) : "—"}
            <span className={s.kpiUnit}>/ day</span>
          </div>
          <div className={s.kpiLabel}>Average orders per day</div>
          {model?.trendPct != null && (
            <span
              className={`${s.trend} ${
                model.trendPct > 1 ? s.trendUp : model.trendPct < -1 ? s.trendDown : s.trendFlat
              }`}
              title="Last 7 days vs the 7 before"
            >
              {model.trendPct > 1 ? "▲" : model.trendPct < -1 ? "▼" : "→"}{" "}
              {Math.abs(Math.round(model.trendPct))}% wk/wk
            </span>
          )}
        </div>
        <div className={s.kpi}>
          <div className={s.kpiNum}>{model ? aed(model.avgRevenuePerDay) : "—"}</div>
          <div className={s.kpiLabel}>Average revenue per day</div>
        </div>
        <div className={s.kpi}>
          <div className={s.kpiNum}>{model?.busiestWeekday ?? "—"}</div>
          <div className={s.kpiLabel}>Busiest day of the week</div>
        </div>
        <div className={s.kpi}>
          <div className={s.kpiNum}>
            {model?.busiestPeriod ? (
              <>
                {model.busiestPeriod.emoji} {model.busiestPeriod.label}
              </>
            ) : (
              "—"
            )}
          </div>
          <div className={s.kpiLabel}>Peak service window</div>
        </div>
      </div>

      {/* ── Next 7 days ────────────────────────────────────────────── */}
      <div className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <span className={s.cardTitle}>Next 7 days</span>
            <span className={s.cardSub}>
              Predicted orders &amp; revenue — each day averaged from the same weekday
            </span>
          </div>
          {model && (
            <span className={`${s.badge} ${confBadge}`} title="Based on how much history exists">
              {model.confidence} confidence
            </span>
          )}
        </div>

        {orders === null ? (
          <LoadingBars />
        ) : !hasHistory ? (
          <div className={s.empty}>
            <div className={s.emptyIcon}>📈</div>
            <div className={s.emptyTitle}>Not enough orders yet</div>
            <div className={s.emptyDesc}>
              The forecast builds itself from your order history. Keep taking orders and
              projections appear here within a few days.
            </div>
          </div>
        ) : (
          <div className={s.barList}>
            {model!.next7.map((d) => (
              <div
                key={d.date}
                className={`${s.barRow} ${d.isToday ? s.barRowToday : ""}`}
              >
                <div className={s.barLabel}>
                  {d.weekday}
                  {d.isToday && " · today"}
                  <span className={s.barLabelSub}>{d.date.slice(5)}</span>
                </div>
                <div className={s.barTrack}>
                  <div
                    className={`${s.barFill} ${d.isToday ? s.barFillToday : s.barFillMuted}`}
                    style={{ width: `${(d.predictedOrders / maxOrders) * 100}%` }}
                  />
                </div>
                <div className={s.barVal}>
                  {d.predictedOrders} orders
                  <span className={s.barValSub}>~{aed(d.predictedRevenue)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Meal periods ───────────────────────────────────────────── */}
      {hasHistory && (
        <div className={s.card}>
          <div className={s.cardHead}>
            <div className={s.cardHeadText}>
              <span className={s.cardTitle}>When demand hits</span>
              <span className={s.cardSub}>Average orders per day by service window</span>
            </div>
          </div>
          <div className={s.barList}>
            {model!.periods.map((p) => (
              <div key={p.key} className={s.barRow}>
                <div className={s.barLabel}>
                  {p.emoji} {p.label}
                  <span className={s.barLabelSub}>{Math.round(p.sharePct)}% of orders</span>
                </div>
                <div className={s.barTrack}>
                  <div
                    className={`${s.barFill} ${s.barFillMuted}`}
                    style={{ width: `${(p.avgPerDay / maxPeriod) * 100}%` }}
                  />
                </div>
                <div className={s.barVal}>
                  {p.avgPerDay.toFixed(1)}
                  <span className={s.barValSub}>/ day</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Prep-ahead dishes ──────────────────────────────────────── */}
      {hasHistory && model!.topDishes.length > 0 && (
        <div className={s.card}>
          <div className={s.cardHead}>
            <div className={s.cardHeadText}>
              <span className={s.cardTitle}>Prep ahead</span>
              <span className={s.cardSub}>
                Your most-ordered dishes and how many to have ready on a typical day
              </span>
            </div>
          </div>
          <table className={s.dishTable}>
            <thead>
              <tr>
                <th>Dish</th>
                <th className={s.numCell}>Sold ({windowDays}d)</th>
                <th className={s.numCell}>Avg / day</th>
                <th className={s.numCell}>Prep</th>
              </tr>
            </thead>
            <tbody>
              {model!.topDishes.map((d) => (
                <tr key={d.name}>
                  <td className={s.dishName}>{d.name}</td>
                  <td className={s.numCell}>{d.totalQty}</td>
                  <td className={s.numCell}>{d.avgPerDay.toFixed(1)}</td>
                  <td className={s.numCell}>
                    <span className={s.prepPill}>{d.suggestedPrep}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hasHistory && (
        <p className={s.foot}>
          Projected from {model!.historyOrders.toLocaleString()} orders across{" "}
          {model!.activeDays} active {model!.activeDays === 1 ? "day" : "days"} in the last{" "}
          {windowDays} days. Weekdays are predicted from the average of that same weekday;
          revenue and prep counts follow the same history. Refreshes automatically.
        </p>
      )}
    </div>
  );
}
