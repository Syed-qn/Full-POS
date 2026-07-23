import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  bumpItem,
  fetchKitchenPerformance,
  fetchPrinterStatus,
  fetchReadyForPickup,
  fetchStationTickets,
  fetchStations,
  missingItemConfirm,
  packagingCheck,
  recallItem,
  seedDefaultStations,
  ticketUrgency,
  type KdsStation,
  type KdsTicketItem,
  type KitchenPerformance,
  type ReadyPickupOrder,
  type TicketUrgency,
} from "../lib/kdsApi";
import { formatCountdown, SLA_WINDOW_MS } from "../lib/sla";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
import { useRestaurantName } from "../lib/brand";
import { logout } from "../lib/auth";
import { getRoleChrome, getSessionRole } from "../lib/navAccess";
import s from "./KdsScreen.module.css";

type Tab = "tickets" | "pickup" | "performance";

/** Board slice selected by the filter chips. Single-select; "all" is the reset. */
type BoardFilter = "all" | "late" | "rush" | "dine" | "takeaway";

/** KDS board theme; persisted per device. */
type KdsTheme = "dark" | "light" | "blue";
const KDS_THEME_KEY = "kds_theme";
const THEME_NEXT_LABEL: Record<KdsTheme, string> = {
  dark: "🌙 Dark",
  light: "☀️ Light",
  blue: "🌊 Blue",
};

/** Card = one order. Items are the station lines belonging to that order. */
interface TicketCard {
  orderId: number;
  orderNumber: string;
  orderType: string | null;
  /** Dine-in table this ticket came from — null for takeaway/delivery. */
  tableLabel: string | null;
  priority: string | null;
  urgency: TicketUrgency;
  ageSeconds: number;
  /** Start of the 40-min SLA; the board counts down from it, then shows LATE. */
  slaStartedAt: string | null;
  estimatedReadyAt: string | null;
  /** Bill already paid while the food is still on the pass. */
  settled: boolean;
  customerAllergyNotes: string | null;
  allReady: boolean;
  items: KdsTicketItem[];
}

const URGENCY_RANK: Record<TicketUrgency, number> = { ok: 0, warning: 1, late: 2 };

function modifierLabel(m: { name?: string } | string): string {
  if (typeof m === "string") return m;
  return m.name ?? JSON.stringify(m);
}

/**
 * Short channel badge for the card header. Only the order_type values defined in
 * `app.ordering.order_types` are mapped — anything else falls back to the raw
 * value so the board never displays an invented channel.
 */
function orderTypeBadge(orderType: string | null | undefined): string | null {
  if (!orderType) return null;
  switch (orderType) {
    case "dine_in":
    case "tableside":
    case "qr":
      return "DINE";
    case "takeaway":
    case "drive_thru":
      return "TK";
    case "delivery":
    case "online":
      // A customer delivery order is a WhatsApp order (order_types.py: "WhatsApp
      // defaults use delivery") — same label the cashier queue uses.
      return "WhatsApp";
    case "aggregator":
      return "AGG";
    default:
      return orderType.replace(/_/g, " ").toUpperCase();
  }
}

function itemUrgency(item: KdsTicketItem): TicketUrgency {
  return (
    item.urgency ?? ticketUrgency(item.kitchen_received_at || item.created_at)
  );
}

function itemAgeSeconds(item: KdsTicketItem): number {
  if (item.age_seconds != null) return item.age_seconds;
  const base = item.kitchen_received_at || item.created_at;
  return Math.max(0, Math.floor((Date.now() - new Date(base).getTime()) / 1000));
}

/**
 * Group station lines into one card per order. Card urgency is the worst
 * urgency across its items; the card timer is the oldest item's age.
 */
export function groupTicketsByOrder(items: KdsTicketItem[]): TicketCard[] {
  const byOrder = new Map<number, TicketCard>();
  for (const item of items) {
    const urgency = itemUrgency(item);
    const age = itemAgeSeconds(item);
    const existing = byOrder.get(item.order_id);
    if (!existing) {
      byOrder.set(item.order_id, {
        orderId: item.order_id,
        orderNumber: item.order_number ?? String(item.order_id),
        orderType: item.order_type ?? null,
        tableLabel: item.table_label ?? null,
        priority: item.order_priority ?? null,
        urgency,
        ageSeconds: age,
        slaStartedAt: item.sla_started_at ?? null,
        estimatedReadyAt: item.estimated_ready_at ?? null,
        customerAllergyNotes: item.customer_allergy_notes ?? null,
        allReady: item.kitchen_status === "ready",
        settled: !!item.order_settled,
        items: [item],
      });
      continue;
    }
    existing.items.push(item);
    if (URGENCY_RANK[urgency] > URGENCY_RANK[existing.urgency]) {
      existing.urgency = urgency;
    }
    if (age > existing.ageSeconds) existing.ageSeconds = age;
    if (!existing.slaStartedAt && item.sla_started_at) {
      existing.slaStartedAt = item.sla_started_at;
    }
    if (!existing.estimatedReadyAt && item.estimated_ready_at) {
      existing.estimatedReadyAt = item.estimated_ready_at;
    }
    if (!existing.customerAllergyNotes && item.customer_allergy_notes) {
      existing.customerAllergyNotes = item.customer_allergy_notes;
    }
    if (!existing.tableLabel && item.table_label) {
      existing.tableLabel = item.table_label;
    }
    if (item.kitchen_status !== "ready") existing.allReady = false;
  }
  const cards = [...byOrder.values()];
  for (const card of cards) {
    card.items.sort(
      (a, b) => (a.course_number ?? 1) - (b.course_number ?? 1) || a.id - b.id,
    );
  }
  // Rush/priority first, then oldest first — mirrors the server-side ordering.
  cards.sort((a, b) => {
    const ap = (a.priority ?? "normal") === "normal" ? 1 : 0;
    const bp = (b.priority ?? "normal") === "normal" ? 1 : 0;
    if (ap !== bp) return ap - bp;
    return b.ageSeconds - a.ageSeconds;
  });
  return cards;
}

export function KdsScreen() {
  const { stationId: stationIdParam } = useParams<{ stationId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const stationId = stationIdParam ? Number(stationIdParam) : null;
  /** Expo / ready-pickup surface stub (full expo UX lands Phase 2). */
  const isExpoView = searchParams.get("view") === "expo";
  /** True when this board is embedded in the manager dashboard (sidebar +
   *  top bar already on screen), false on the chrome-free kitchen surface. */
  const hasShell = getRoleChrome(getSessionRole()).showSidebar;

  const [stations, setStations] = useState<KdsStation[]>([]);
  const restaurantName = useRestaurantName();
  const [items, setItems] = useState<KdsTicketItem[]>([]);
  const [pickup, setPickup] = useState<ReadyPickupOrder[]>([]);
  const [perf, setPerf] = useState<KitchenPerformance | null>(null);
  const [printers, setPrinters] = useState<
    Array<{ station_id: number; healthy: boolean }>
  >([]);
  const [tab, setTab] = useState<Tab>(isExpoView ? "pickup" : "tickets");
  // Board theme (dark default). Persisted per device so a station keeps its look.
  const [theme, setTheme] = useState<KdsTheme>(() => {
    const saved = localStorage.getItem(KDS_THEME_KEY);
    return saved === "light" || saved === "blue" || saved === "dark" ? saved : "dark";
  });
  const cycleTheme = () => {
    setTheme((t) => {
      const next: KdsTheme = t === "dark" ? "light" : t === "light" ? "blue" : "dark";
      localStorage.setItem(KDS_THEME_KEY, next);
      return next;
    });
  };
  // Ready tickets stay on the board until bumped; the "Show ready" toggle was
  // removed, so this is fixed off (ready items show via their own ✓ state).
  const includeReady = false;
  const [boardFilter, setBoardFilter] = useState<BoardFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const [, forceTick] = useState(0);
  /** Wall-clock at which `items` (and their age_seconds) were fetched. */
  const fetchedAtRef = useRef<number>(Date.now());
  /** Stack of bumped ticket item-id groups, for the ↺ Bumped recall button. */
  const [bumpedStack, setBumpedStack] = useState<number[][]>([]);

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
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load stations");
    }
  }, []);

  /**
   * `list_station_tickets` is per-station, so the ALL board fans out over every
   * station and merges client-side (no new backend surface).
   */
  const reloadTickets = useCallback(async () => {
    const targets = stationId
      ? stations.filter((st) => st.id === stationId)
      : stations;
    if (targets.length === 0) return;
    try {
      const batches = await Promise.all(
        targets.map((st) => fetchStationTickets(st.id, includeReady)),
      );
      const merged = new Map<number, KdsTicketItem>();
      for (const batch of batches) {
        for (const row of batch) merged.set(row.id, row);
      }
      fetchedAtRef.current = Date.now();
      setItems([...merged.values()]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tickets");
    }
  }, [stationId, stations, includeReady]);

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
    // Printer health drives the header pill on every view, not just Performance.
    reloadPrinters();
    const interval = setInterval(reloadPrinters, 30000);
    return () => clearInterval(interval);
  }, [reloadPrinters]);

  useEffect(() => {
    if (tab === "pickup") {
      reloadPickup();
      const interval = setInterval(reloadPickup, 5000);
      return () => clearInterval(interval);
    }
    if (tab === "performance") {
      reloadPerf();
    }
  }, [tab, reloadPickup, reloadPerf]);


  const allCards = useMemo(() => groupTicketsByOrder(items), [items]);

  const isRushCard = (c: (typeof allCards)[number]) =>
    c.priority === "rush" || c.priority === "priority";
  // Channel slices group by the SAME badge mapping the cards show, so a chip
  // and a card badge can never disagree.
  const matches = (c: (typeof allCards)[number], f: BoardFilter) => {
    if (f === "all") return true;
    if (f === "late") return c.urgency === "late";
    if (f === "rush") return isRushCard(c);
    return orderTypeBadge(c.orderType) === (f === "dine" ? "DINE" : "TK");
  };

  /** What selecting this chip would actually show. */
  const countFor = (f: BoardFilter) => allCards.filter((c) => matches(c, f)).length;

  const cards = useMemo(
    // No slice drops allReady cards: a ready ticket stays up until someone
    // bumps it, and hiding it would strand the bump.
    () => allCards.filter((c) => matches(c, boardFilter)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allCards, boardFilter],
  );

  const unhealthyPrinters = printers.filter((p) => !p.healthy).length;

  /** Live MM:SS — server age plus wall-clock drift since the last poll. */
  function liveAge(baseSeconds: number): number {
    const drift = Math.floor((Date.now() - fetchedAtRef.current) / 1000);
    return Math.max(0, baseSeconds + Math.max(0, drift));
  }

  /**
   * Board timer, matching the manager dashboard: count DOWN from the 40-min SLA,
   * then show "LATE" instead of a climbing number. Uses sla_started_at when the
   * order carries one (the 40-min customer clock); otherwise it falls back to the
   * ticket's own age so an on-premise line still shows time-left / LATE.
   */
  function slaTimer(card: TicketCard): { text: string; late: boolean } {
    const elapsedMs = card.slaStartedAt
      ? Date.now() - Date.parse(card.slaStartedAt)
      : liveAge(card.ageSeconds) * 1000;
    const remaining = SLA_WINDOW_MS - elapsedMs;
    return remaining <= 0
      ? { text: "LATE", late: true }
      : { text: formatCountdown(remaining), late: false };
  }

  /** Marks every not-yet-ready, not-held line of an order ready. */
  async function handleReady(card: TicketCard) {
    const targets = card.items.filter(
      (i) => i.kitchen_status !== "ready" && !i.course_held,
    );
    for (const i of targets) await bumpItem(i.id);
    const readyIds = new Set(targets.map((i) => i.id));
    setItems((prev) =>
      prev.map((i) =>
        readyIds.has(i.id) ? { ...i, kitchen_status: "ready" } : i,
      ),
    );
  }

  /** Clears the ticket off the board (bumping anything still pending). */
  async function handleBumpCard(card: TicketCard) {
    const pending = card.items.filter(
      (i) => i.kitchen_status !== "ready" && !i.course_held,
    );
    for (const i of pending) await bumpItem(i.id);
    const cleared = card.items.filter((i) => !i.course_held).map((i) => i.id);
    const clearedSet = new Set(cleared);
    setItems((prev) => prev.filter((i) => !clearedSet.has(i.id)));
    if (cleared.length > 0) setBumpedStack((prev) => [...prev, cleared]);
  }

  /** ↺ Bumped — pulls the most recently bumped ticket back onto the board. */
  async function handleRecallLast() {
    const last = bumpedStack[bumpedStack.length - 1];
    if (!last) return;
    setBumpedStack((prev) => prev.slice(0, -1));
    const restored: KdsTicketItem[] = [];
    for (const id of last) {
      try {
        restored.push(await recallItem(id));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Recall failed");
      }
    }
    if (restored.length > 0) {
      fetchedAtRef.current = Date.now();
      setItems((prev) => {
        const ids = new Set(restored.map((i) => i.id));
        return [...prev.filter((i) => !ids.has(i.id)), ...restored];
      });
    }
  }


  return (
    <div
      className={`${s.root} ${hasShell ? s.rootEmbedded : ""}`}
      data-testid="kds-screen"
      data-theme={theme}
      data-view={isExpoView ? "expo" : "station"}
    >
      <OfflineLimitsBanner surface="kds" />

      <header className={s.topStrip}>
        <div className={s.brand}>
          {/* Same blue POS mark + name/role stack as the manager sidebar and
              the waiter/cashier top bar — one identity across every surface. */}
          <span className={s.brandMark}>POS</span>
          <span className={s.brandText}>
            <strong className={s.brandName}>{restaurantName}</strong>
            <span className={s.brandRole}>Kitchen Display</span>
          </span>
        </div>

        <div className={s.topRight}>
          <button
            type="button"
            className={s.chromeBtn}
            data-testid="kds-theme"
            title="Switch board theme (dark → light → blue)"
            onClick={cycleTheme}
          >
            {THEME_NEXT_LABEL[theme]}
          </button>
          <button
            type="button"
            className={s.chromeBtn}
            data-testid="kds-recall-bumped"
            disabled={bumpedStack.length === 0}
            onClick={handleRecallLast}
          >
            ↺ Bumped
          </button>
          <button
            type="button"
            className={s.chromeBtn}
            onClick={() => setTab("performance")}
          >
            Performance
          </button>
          {/* A kitchen session runs chrome-free (no sidebar, no top bar), so
              this is its ONLY way out. A manager opening the same board from
              the dashboard already has Sign out in the sidebar — two of them
              on one screen is just clutter. */}
          {!hasShell && (
            <button
              type="button"
              className={s.chromeBtn}
              data-testid="kitchen-signout"
              title="Sign out"
              onClick={() => {
                logout();
                navigate("/login", { replace: true });
              }}
            >
              🔒 Sign out
            </button>
          )}
        </div>
      </header>

      {isExpoView && (
        <div className={s.expoBanner} data-testid="kds-expo-banner" role="status">
          Expo / ready for delivery &amp; pickup — packaging, missing items, then
          handoff.
        </div>
      )}

      {tab !== "tickets" && !isExpoView && (
        <div className={s.stationTabs}>
          <button
            type="button"
            className={s.stationTab}
            onClick={() => setTab("tickets")}
          >
            ← Back to tickets
          </button>
        </div>
      )}

      {error ? (
        <div className={s.alert} role="alert">
          {error}
        </div>
      ) : null}

      {/* Filters sit in the page, directly above the cards they filter — not
          on a chrome strip. The "N tickets" label was dropped with that strip:
          the ACTIVE chip already carries the count. */}
      {tab === "tickets" && (
        <section className={s.boardFilters} aria-label="Filter tickets">
          <span className={s.filterLabel}>Filter</span>
          <div className={s.counters} role="group" data-testid="kds-counters">
          {/* "All" first: it is the reset, not a state, so it should never be
              the loudest chip in the row. */}
          <button
            type="button"
            className={`${s.counter} ${boardFilter === "all" ? s.counterOn : ""}`}
            aria-pressed={boardFilter === "all"}
            onClick={() => setBoardFilter("all")}
            data-testid="kds-filter-active"
          >
            All <b>{countFor("all")}</b>
          </button>
          <button
            type="button"
            className={`${s.counter} ${s.counterLate} ${
              boardFilter === "late" ? s.counterOn : ""
            }`}
            aria-pressed={boardFilter === "late"}
            onClick={() => setBoardFilter(boardFilter === "late" ? "all" : "late")}
            data-testid="kds-filter-late"
          >
            Late <b>{countFor("late")}</b>
          </button>
          <button
            type="button"
            className={`${s.counter} ${s.counterRush} ${
              boardFilter === "rush" ? s.counterOn : ""
            }`}
            aria-pressed={boardFilter === "rush"}
            onClick={() => setBoardFilter(boardFilter === "rush" ? "all" : "rush")}
            data-testid="kds-filter-rush"
          >
            Rush <b>{countFor("rush")}</b>
          </button>
          <button
            type="button"
            className={`${s.counter} ${boardFilter === "dine" ? s.counterOn : ""}`}
            aria-pressed={boardFilter === "dine"}
            onClick={() => setBoardFilter(boardFilter === "dine" ? "all" : "dine")}
            data-testid="kds-filter-dine"
          >
            Dine <b>{countFor("dine")}</b>
          </button>
          <button
            type="button"
            className={`${s.counter} ${boardFilter === "takeaway" ? s.counterOn : ""}`}
            aria-pressed={boardFilter === "takeaway"}
            onClick={() =>
              setBoardFilter(boardFilter === "takeaway" ? "all" : "takeaway")
            }
            data-testid="kds-filter-takeaway"
          >
            Take Away <b>{countFor("takeaway")}</b>
          </button>
          {printers.length > 0 ? (
            <span
              className={`${s.counter} ${s.counterStatic} ${
                unhealthyPrinters > 0 ? s.counterLate : ""
              }`}
              data-testid="kds-printer-status"
            >
              {unhealthyPrinters > 0
                ? `Printers: ${unhealthyPrinters} down`
                : "Printers OK"}
            </span>
          ) : null}
          </div>
        </section>
      )}

      {tab === "tickets" && (
        <div className={s.board} data-testid="kds-ticket-grid">
          {cards.length === 0 ? (
            <div className={s.empty}>No active tickets</div>
          ) : (
            cards.map((card) => {
              const channel = orderTypeBadge(card.orderType);
              const isRush =
                card.priority === "rush" || card.priority === "priority";
              return (
                <article
                  key={card.orderId}
                  className={`${s.card} ${s[`card_${card.urgency}`]} ${
                    card.allReady ? s.cardReady : ""
                  }`}
                  data-urgency={card.urgency}
                  data-testid={`kds-ticket-${card.orderId}`}
                >
                  <div className={s.cardHead}>
                    <div className={s.cardHeadLeft}>
                      <span className={s.orderRef}>{card.orderNumber}</span>
                      {/* Channel + table in ONE coloured pill. They were two
                          badges, and the channel one was ink-dim on panel-2 —
                          the least visible thing on a card whose whole job is
                          telling the kitchen where the food is going. Colour is
                          per channel so DINE / TK / DEL are told apart at a
                          glance, not read. */}
                      {channel ? (
                        <span
                          className={`${s.chanBadge} ${s[`chan_${channel}`] ?? ""}`}
                          data-testid={card.tableLabel ? "kds-table" : "kds-channel"}
                        >
                          {channel === "DINE" ? "DINE" : channel}
                          {card.tableLabel ? ` · ${card.tableLabel}` : ""}
                        </span>
                      ) : card.tableLabel ? (
                        <span className={s.chanBadge} data-testid="kds-table">
                          {card.tableLabel}
                        </span>
                      ) : null}
                      {isRush ? (
                        <span className={s.rushBadge}>⚡RUSH</span>
                      ) : null}
                      {/* Bill settled while the food is still on the pass —
                          the guest has paid and is standing at the counter. */}
                      {card.settled ? (
                        <span className={s.paidBadge} data-testid="kds-paid">
                          PAID · WAITING
                        </span>
                      ) : null}
                    </div>
                    {(() => {
                      const t = slaTimer(card);
                      // A breached SLA is always the red "late" style, even if the
                      // per-item urgency hasn't ticked over yet.
                      const tone = t.late ? "late" : card.urgency;
                      return (
                        <span
                          className={`${s.timer} ${s[`timer_${tone}`]}`}
                          data-testid="kds-timer"
                        >
                          {t.text}
                        </span>
                      );
                    })()}
                  </div>

                  {card.customerAllergyNotes ? (
                    <div className={s.customerAllergy}>
                      CUSTOMER ALLERGY: {card.customerAllergyNotes}
                    </div>
                  ) : null}

                  <ul className={s.itemList}>
                    {card.items.map((item, idx) => {
                      const mods = item.selected_modifiers ?? [];
                      const allergens = item.allergens ?? [];
                      return (
                        <li
                          key={item.id}
                          className={`${s.item} ${item.course_held ? s.itemHeld : ""}`}
                          data-testid={`kds-item-${item.id}`}
                        >
                          <div className={s.itemMain}>
                            {/* Line number on the ticket. Was "C<course>", but
                                the course number is always 1 (nothing sets it),
                                so it read as a constant badge with no meaning. */}
                            <span className={s.course}>{idx + 1}</span>
                            <span className={s.dish}>
                              {item.qty > 1 ? `${item.qty}× ` : ""}
                              {item.dish_name}
                              {item.variant_name ? ` (${item.variant_name})` : ""}
                            </span>
                            {item.is_takeaway ? (
                              <span className={s.toGoMark} data-testid="kds-togo">
                                📦 TO GO
                              </span>
                            ) : null}
                            {item.course_held ? (
                              <span className={s.heldMark}>HELD</span>
                            ) : null}
                            {item.kitchen_status === "ready" ? (
                              <span className={s.itemReady}>✓</span>
                            ) : null}
                          </div>

                          {mods.length > 0 ? (
                            <div className={s.sub} data-testid="kds-modifiers">
                              {mods.map(modifierLabel).join(", ")}
                            </div>
                          ) : null}
                          {item.notes ? (
                            <div className={s.noteText} data-testid="kds-note">
                              {item.notes}
                            </div>
                          ) : null}

                          {allergens.length > 0 ? (
                            <div className={s.chips}>
                              <span
                                className={s.allergenGroup}
                                data-testid="kds-allergens"
                              >
                                {allergens.map((a) => (
                                  <span key={a} className={s.allergenChip}>
                                    {a.toUpperCase()}
                                  </span>
                                ))}
                              </span>
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>

                  {card.estimatedReadyAt ? (
                    <div className={s.eta} data-testid="kds-eta">
                      ETA {new Date(card.estimatedReadyAt).toLocaleTimeString()}
                    </div>
                  ) : null}

                  <div className={s.cardFoot}>
                    {card.allReady ? (
                      <>
                        <span className={s.readyState}>✓ READY</span>
                        <button
                          type="button"
                          className={s.bumpBtn}
                          onClick={() => handleBumpCard(card)}
                        >
                          Served — Bump
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className={s.readyBtn}
                          onClick={() => handleReady(card)}
                        >
                          ✓ Ready
                        </button>
                        <button
                          type="button"
                          className={s.bumpBtn}
                          onClick={() => handleBumpCard(card)}
                        >
                          ⇄ Bump
                        </button>
                      </>
                    )}
                  </div>

                </article>
              );
            })
          )}
        </div>
      )}

      {tab === "pickup" && (
        <div className={s.panel} data-testid="kds-pickup">
          <div className={s.panelTitle}>
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
                <strong className={s.orderRef}>{o.order_number}</strong>
                <ul className={s.pickupList}>
                  {o.items.map((i) => (
                    <li key={i.id}>
                      {i.qty}× {i.dish_name}
                      {i.packaging_checked ? " · pack✓" : ""}
                      {i.quality_checked ? " · qc✓" : ""}
                      {i.missing_item_confirmed ? " · missing noted" : ""}
                    </li>
                  ))}
                </ul>
                {isExpoView && (
                  <div className={s.cardFoot}>
                    <button
                      type="button"
                      className={s.readyBtn}
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
                      className={s.bumpBtn}
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
                      className={s.miniBtn}
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
        <div className={s.panel} data-testid="kds-performance">
          <div className={s.panelTitle}>Kitchen performance (today)</div>
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
            <div className={s.panelBlock}>
              <div className={s.panelTitle}>By station</div>
              {perf.by_station.map((row) => (
                <div key={String(row.station_id)} className={s.perfRow}>
                  {row.station_name}: {row.avg_prep_minutes}m ({row.ticket_count}{" "}
                  tickets)
                </div>
              ))}
            </div>
          ) : null}
          <div className={s.panelBlock}>
            <div className={s.panelTitle}>Printer health</div>
            {printers.length === 0 ? (
              <div className={s.empty}>No printer heartbeats yet</div>
            ) : (
              printers.map((p) => (
                <div
                  key={p.station_id}
                  className={p.healthy ? s.printerOk : s.printerBad}
                >
                  Station {p.station_id}:{" "}
                  {p.healthy ? "healthy" : "DOWN — fallback may apply"}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
