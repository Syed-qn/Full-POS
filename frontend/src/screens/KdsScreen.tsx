import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  bumpItem,
  fetchKitchenPerformance,
  fetchPrinterStatus,
  fetchReadyForPickup,
  fetchStationTickets,
  fetchStations,
  formatElapsed,
  missingItemConfirm,
  packagingCheck,
  qualityCheck,
  recallItem,
  seedDefaultStations,
  startPrep,
  ticketUrgency,
  type KdsStation,
  type KdsTicketItem,
  type KitchenPerformance,
  type ReadyPickupOrder,
} from "../lib/kdsApi";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
import s from "./KdsScreen.module.css";

type Tab = "tickets" | "pickup" | "performance";

function modifierLabel(m: { name?: string } | string): string {
  if (typeof m === "string") return m;
  return m.name ?? JSON.stringify(m);
}

function urgencyCardClass(urgency: string): string {
  if (urgency === "late") return s.cardUrgencyLate;
  if (urgency === "warning") return s.cardUrgencyWarning;
  return s.cardUrgencyOk;
}

export function KdsScreen() {
  const { stationId: stationIdParam } = useParams<{ stationId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const stationId = stationIdParam ? Number(stationIdParam) : null;
  /** Expo / ready-pickup surface stub (full expo UX lands Phase 2). */
  const isExpoView = searchParams.get("view") === "expo";

  const [stations, setStations] = useState<KdsStation[]>([]);
  const [items, setItems] = useState<KdsTicketItem[]>([]);
  const [pickup, setPickup] = useState<ReadyPickupOrder[]>([]);
  const [perf, setPerf] = useState<KitchenPerformance | null>(null);
  const [printers, setPrinters] = useState<
    Array<{ station_id: number; healthy: boolean }>
  >([]);
  const [tab, setTab] = useState<Tab>(isExpoView ? "pickup" : "tickets");
  const [includeReady, setIncludeReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, forceTick] = useState(0);

  useEffect(() => {
    if (isExpoView) setTab("pickup");
  }, [isExpoView]);

  useEffect(() => {
    const tick = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(tick);
  }, []);

  const loadStations = useCallback(async () => {
    try {
      let rows = await fetchStations();
      if (rows.length === 0) {
        rows = await seedDefaultStations("main");
      }
      setStations(rows);
      if (!stationId && rows[0] && !isExpoView) {
        navigate(`/kds/${rows[0].id}`, { replace: true });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load stations");
    }
  }, [navigate, stationId, isExpoView]);

  const reloadTickets = useCallback(async () => {
    if (!stationId) return;
    try {
      const rows = await fetchStationTickets(stationId, includeReady);
      setItems(rows);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tickets");
    }
  }, [stationId, includeReady]);

  const reloadPickup = useCallback(async () => {
    try {
      setPickup(await fetchReadyForPickup());
    } catch {
      /* optional panel */
    }
  }, []);

  const reloadPerf = useCallback(async () => {
    const today = new Date().toISOString().slice(0, 10);
    try {
      setPerf(await fetchKitchenPerformance(today, today));
    } catch {
      /* optional */
    }
  }, []);

  const reloadPrinters = useCallback(async () => {
    try {
      setPrinters(await fetchPrinterStatus());
    } catch {
      /* optional */
    }
  }, []);

  useEffect(() => {
    loadStations();
  }, [loadStations]);

  useEffect(() => {
    if (tab !== "tickets") return;
    reloadTickets();
    const interval = setInterval(reloadTickets, 5000);
    return () => clearInterval(interval);
  }, [tab, reloadTickets]);

  useEffect(() => {
    if (tab === "pickup") {
      reloadPickup();
      const interval = setInterval(reloadPickup, 5000);
      return () => clearInterval(interval);
    }
    if (tab === "performance") {
      reloadPerf();
      reloadPrinters();
    }
  }, [tab, reloadPickup, reloadPerf, reloadPrinters]);

  const currentStation = useMemo(
    () => stations.find((st) => st.id === stationId) ?? null,
    [stations, stationId],
  );

  const unhealthyPrinters = printers.filter((p) => !p.healthy).length;

  async function handleBump(id: number) {
    await bumpItem(id);
    setItems((prev) => prev.filter((i) => i.id !== id));
  }

  async function handleRecall(id: number) {
    const updated = await recallItem(id);
    setItems((prev) => {
      const rest = prev.filter((i) => i.id !== id);
      return [...rest, updated];
    });
  }

  async function handleStartPrep(id: number) {
    const updated = await startPrep(id);
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...updated } : i)));
  }

  async function handlePackaging(id: number) {
    await packagingCheck(id);
    setItems((prev) =>
      prev.map((i) => (i.id === id ? { ...i, packaging_checked: true } : i)),
    );
  }

  async function handleQuality(id: number) {
    await qualityCheck(id);
    setItems((prev) =>
      prev.map((i) => (i.id === id ? { ...i, quality_checked: true } : i)),
    );
  }

  async function handleMissing(id: number) {
    await missingItemConfirm(id, "missing/short on ticket");
    setItems((prev) =>
      prev.map((i) =>
        i.id === id
          ? { ...i, missing_item_confirmed: true, missing_item_note: "missing/short on ticket" }
          : i,
      ),
    );
  }

  return (
    <div
      className={`${s.root} ${isExpoView ? s.rootExpo : ""}`}
      data-testid="kds-screen"
      data-view={isExpoView ? "expo" : "station"}
    >
      <OfflineLimitsBanner surface="kds" />
      <div className={s.header}>
        <h1 className={s.title}>
          {isExpoView ? "Expo / Ready Pickup" : "Kitchen Display"}
          {!isExpoView && currentStation ? ` — ${currentStation.name}` : ""}
          {currentStation?.station_type ? (
            <span className={`${s.badge} ${s.badgeInfo}`}>{currentStation.station_type}</span>
          ) : null}
          {currentStation?.kitchen_code ? (
            <span className={`${s.badge} ${s.badgeOk}`}>kitchen:{currentStation.kitchen_code}</span>
          ) : null}
          {printers.length > 0 ? (
            <span
              className={`${s.badge} ${unhealthyPrinters > 0 ? "" : s.badgeOk}`}
              data-testid="kds-printer-status"
            >
              {unhealthyPrinters > 0
                ? `Printers: ${unhealthyPrinters} down`
                : "Printers OK"}
            </span>
          ) : null}
        </h1>
        <div className={s.controls}>
          {!isExpoView && (
            <>
              <select
                className={s.select}
                aria-label="Station"
                value={stationId ?? ""}
                onChange={(e) => navigate(`/kds/${e.target.value}`)}
              >
                {stations.map((st) => (
                  <option key={st.id} value={st.id}>
                    {st.name} ({st.station_type}) [{st.kitchen_code}]
                  </option>
                ))}
              </select>
              <label className={s.includeReady}>
                <input
                  type="checkbox"
                  checked={includeReady}
                  onChange={(e) => setIncludeReady(e.target.checked)}
                />{" "}
                Show ready
              </label>
            </>
          )}
          <button
            type="button"
            className={`${s.btn} ${isExpoView ? s.btnActive : ""}`}
            data-testid="kds-expo-toggle"
            onClick={() => {
              if (isExpoView) {
                const first = stations[0];
                navigate(first ? `/kds/${first.id}` : "/kds");
              } else {
                navigate("/kds?view=expo");
              }
            }}
          >
            {isExpoView ? "← Stations" : "Expo / Ready"}
          </button>
          <button
            type="button"
            className={s.btn}
            onClick={() => seedDefaultStations().then(loadStations)}
          >
            Seed stations
          </button>
        </div>
      </div>

      {isExpoView && (
        <div className={s.expoBanner} data-testid="kds-expo-banner" role="status">
          Expo / ready for delivery & pickup — packaging, missing items, then handoff.
        </div>
      )}

      <div className={s.tabs} role="tablist">
        {(["tickets", "pickup", "performance"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={`${s.tab} ${tab === t ? s.tabActive : ""}`}
            onClick={() => {
              setTab(t);
              if (t === "pickup" && !isExpoView) {
                navigate("/kds?view=expo");
              }
            }}
          >
            {t === "tickets"
              ? "Tickets"
              : t === "pickup"
                ? "Ready for delivery"
                : "Performance"}
          </button>
        ))}
      </div>

      {error ? (
        <div className={s.alert} role="alert">
          {error}
        </div>
      ) : null}

      {tab === "tickets" && (
        <div className={s.grid} data-testid="kds-ticket-grid">
          {items.length === 0 ? (
            <div className={s.empty}>No active tickets for this station</div>
          ) : (
            items.map((item) => {
              const ageSec =
                item.age_seconds ??
                Math.floor(
                  (Date.now() -
                    new Date(item.kitchen_received_at || item.created_at).getTime()) /
                    1000,
                );
              const urgency =
                item.urgency ??
                ticketUrgency(item.kitchen_received_at || item.created_at);
              const mods = item.selected_modifiers ?? [];
              const allergens = item.allergens ?? [];
              const hasAllergy =
                allergens.length > 0 || Boolean(item.customer_allergy_notes);
              return (
                <div
                  key={item.id}
                  className={`${s.card} ${urgencyCardClass(urgency)}`}
                  data-urgency={urgency}
                  data-testid={`kds-ticket-${item.id}`}
                >
                  <div className={s.meta}>
                    <span className={s.orderRef}>
                      #{item.order_number ?? item.order_id}
                      {item.order_priority && item.order_priority !== "normal" ? (
                        <span className={s.badge} style={{ marginLeft: 6 }}>
                          {item.order_priority.toUpperCase()}
                        </span>
                      ) : null}
                      {item.course_number && item.course_number > 1 ? (
                        <span className={`${s.badge} ${s.badgeInfo}`} style={{ marginLeft: 4 }}>
                          Course {item.course_number}
                        </span>
                      ) : null}
                    </span>
                    <span
                      className={`${s.timer} ${
                        urgency === "late"
                          ? s.timerLate
                          : urgency === "warning"
                            ? s.timerWarn
                            : ""
                      }`}
                      data-testid="kds-timer"
                    >
                      {formatElapsed(Math.max(0, ageSec))}
                    </span>
                  </div>

                  {(item.is_delayed || urgency !== "ok") && (
                    <div
                      className={`${s.urgencyBanner} ${
                        urgency === "late" ? s.urgencyBannerLate : s.urgencyBannerWarn
                      }`}
                    >
                      {urgency === "late" ? "DELAYED — late ticket" : "Aging ticket"}
                    </div>
                  )}

                  <div className={s.dish}>
                    {item.qty}x {item.dish_name}
                    {item.variant_name ? ` (${item.variant_name})` : ""}
                  </div>

                  {mods.length > 0 && (
                    <div className={s.modifiers} data-testid="kds-modifiers">
                      Modifiers: {mods.map(modifierLabel).join(", ")}
                    </div>
                  )}
                  {item.notes && <div className={s.notes}>Note: {item.notes}</div>}

                  {hasAllergy && (
                    <div className={s.allergenBlock}>
                      {allergens.length > 0 && (
                        <div className={s.allergenBanner} data-testid="kds-allergens">
                          ⚠ ALLERGENS: {allergens.join(", ").toUpperCase()}
                        </div>
                      )}
                      {item.customer_allergy_notes && (
                        <div className={s.customerAllergy}>
                          CUSTOMER ALLERGY: {item.customer_allergy_notes}
                        </div>
                      )}
                    </div>
                  )}

                  {item.estimated_ready_at && (
                    <div className={s.meta} data-testid="kds-eta">
                      ETA ready: {new Date(item.estimated_ready_at).toLocaleTimeString()}
                    </div>
                  )}

                  <div className={s.meta}>
                    Status: {item.kitchen_status}
                    {item.packaging_checked ? " · Pack ✓" : ""}
                    {item.quality_checked ? " · QC ✓" : ""}
                    {item.missing_item_confirmed ? " · Missing noted" : ""}
                  </div>

                  <div className={s.actions}>
                    {item.kitchen_status === "received" && (
                      <button
                        type="button"
                        className={`${s.btn} ${s.btnStart}`}
                        onClick={() => handleStartPrep(item.id)}
                      >
                        Start prep
                      </button>
                    )}
                    {item.kitchen_status !== "ready" && (
                      <button
                        type="button"
                        className={`${s.btn} ${s.btnPrimary}`}
                        onClick={() => handleBump(item.id)}
                      >
                        Bump
                      </button>
                    )}
                    {item.kitchen_status === "ready" && (
                      <button
                        type="button"
                        className={s.btn}
                        onClick={() => handleRecall(item.id)}
                      >
                        Recall
                      </button>
                    )}
                    <button
                      type="button"
                      className={`${s.btn} ${s.btnGhost}`}
                      onClick={() => handlePackaging(item.id)}
                      disabled={item.packaging_checked}
                    >
                      Packaging
                    </button>
                    <button
                      type="button"
                      className={`${s.btn} ${s.btnGhost}`}
                      onClick={() => handleQuality(item.id)}
                      disabled={item.quality_checked}
                    >
                      Quality
                    </button>
                    <button
                      type="button"
                      className={`${s.btn} ${s.btnDanger}`}
                      onClick={() => handleMissing(item.id)}
                      disabled={item.missing_item_confirmed}
                    >
                      Missing item
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {tab === "pickup" && (
        <div className={s.section} data-testid="kds-pickup">
          <div className={s.sectionTitle}>
            Ready for pickup
            {isExpoView ? ` · ${pickup.length} ready` : ""}
          </div>
          {pickup.length === 0 ? (
            <div className={s.empty}>No orders ready for pickup</div>
          ) : (
            pickup.map((o) => (
              <div
                key={o.order_id}
                className={s.pickupCard}
                data-testid={`expo-ticket-${o.order_id}`}
              >
                <strong>#{o.order_number}</strong>
                <ul>
                  {o.items.map((i) => (
                    <li key={i.id}>
                      {i.qty}x {i.dish_name}
                      {i.packaging_checked ? " · pack✓" : ""}
                      {i.quality_checked ? " · qc✓" : ""}
                      {i.missing_item_confirmed ? " · missing noted" : ""}
                    </li>
                  ))}
                </ul>
                {isExpoView && (
                  <div className={s.actions} style={{ marginTop: 8 }}>
                    <button
                      type="button"
                      className={`${s.btn} ${s.btnPrimary}`}
                      onClick={async () => {
                        for (const i of o.items) {
                          if (!i.packaging_checked) await packagingCheck(i.id);
                        }
                        await reloadPickup();
                      }}
                    >
                      Packaging checklist
                    </button>
                    <button
                      type="button"
                      className={s.btn}
                      onClick={async () => {
                        for (const i of o.items) {
                          if (!i.missing_item_confirmed) {
                            await missingItemConfirm(i.id, "expo check");
                          }
                        }
                        await reloadPickup();
                      }}
                    >
                      Confirm missing
                    </button>
                    <button
                      type="button"
                      className={`${s.btn} ${s.btnGhost}`}
                      onClick={async () => {
                        for (const i of o.items) {
                          await recallItem(i.id);
                        }
                        await reloadPickup();
                      }}
                    >
                      Reopen ticket
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {tab === "performance" && (
        <div className={s.section} data-testid="kds-performance">
          <div className={s.sectionTitle}>Kitchen performance (today)</div>
          {perf ? (
            <div className={s.perfGrid}>
              <div className={s.metric}>
                <div className={s.metricValue}>{perf.ticket_count}</div>
                <div className={s.metricLabel}>Tickets</div>
              </div>
              <div className={s.metric}>
                <div className={s.metricValue}>{perf.bumped_count}</div>
                <div className={s.metricLabel}>Bumped</div>
              </div>
              <div className={s.metric}>
                <div className={s.metricValue}>{perf.late_ticket_count}</div>
                <div className={s.metricLabel}>Late</div>
              </div>
              <div className={s.metric}>
                <div className={s.metricValue}>
                  {perf.avg_prep_minutes != null ? `${perf.avg_prep_minutes}m` : "—"}
                </div>
                <div className={s.metricLabel}>Avg prep</div>
              </div>
            </div>
          ) : (
            <div className={s.empty}>No performance data yet</div>
          )}
          {perf?.by_station?.length ? (
            <div className={s.section}>
              <div className={s.sectionTitle}>By station</div>
              {perf.by_station.map((row) => (
                <div key={String(row.station_id)} className={s.meta}>
                  {row.station_name}: {row.avg_prep_minutes}m ({row.ticket_count} tickets)
                </div>
              ))}
            </div>
          ) : null}
          <div className={s.section}>
            <div className={s.sectionTitle}>Printer health</div>
            {printers.length === 0 ? (
              <div className={s.empty}>No printer heartbeats yet</div>
            ) : (
              printers.map((p) => (
                <div key={p.station_id} className={p.healthy ? s.printerOk : s.printerBad}>
                  Station {p.station_id}: {p.healthy ? "healthy" : "DOWN — fallback may apply"}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
