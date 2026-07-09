import { useCallback, useEffect, useMemo, useState } from "react";
import s from "./RiderAppScreen.module.css";

const DEVICE_TOKEN_KEY = "rider_app_device_token";
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export type RiderStop = {
  orderId: number;
  orderNumber: string;
  sequence: number;
  customerName: string | null;
  customerPhone: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  codAmount: number;
  delivered: boolean;
  outcome: "pending" | "delivered" | "not_delivered";
  doNotCall: boolean;
};

export type RiderRun = {
  batchId: number | null;
  status: string | null; // planned | picked_up | null
  stops: RiderStop[];
  onDuty: boolean;
};

type PrimaryAction = "pickup" | "arriving" | "delivered" | "idle" | "none";

const FAIL_REASONS = [
  { id: "customer_unreachable", label: "Customer unreachable" },
  { id: "wrong_address", label: "Wrong address" },
  { id: "customer_refused", label: "Customer refused" },
  { id: "other", label: "Other" },
] as const;

/** Demo stops when unpaired / API unavailable so the mobile UI is reviewable. */
const MOCK_RUN: RiderRun = {
  batchId: 9001,
  status: "planned",
  onDuty: true,
  stops: [
    {
      orderId: 101,
      orderNumber: "R1-0101",
      sequence: 1,
      customerName: "Aisha K.",
      customerPhone: "+971501234567",
      address: "Marina Walk, Dubai Marina",
      latitude: 25.0805,
      longitude: 55.1403,
      codAmount: 48.5,
      delivered: false,
      outcome: "pending",
      doNotCall: false,
    },
    {
      orderId: 102,
      orderNumber: "R1-0102",
      sequence: 2,
      customerName: "Omar S.",
      customerPhone: "+971509876543",
      address: "JBR Walk, The Beach",
      latitude: 25.0772,
      longitude: 55.1336,
      codAmount: 32.0,
      delivered: false,
      outcome: "pending",
      doNotCall: true,
    },
  ],
};

async function riderReq<T>(
  path: string,
  token: string | null,
  init?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const j = (await resp.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

function money(n: number): string {
  return `AED ${n.toFixed(2)}`;
}

export function RiderAppScreen() {
  const [token, setToken] = useState<string | null>(() => {
    try {
      return localStorage.getItem(DEVICE_TOKEN_KEY);
    } catch {
      return null;
    }
  });
  const [demoMode, setDemoMode] = useState(false);
  const [run, setRun] = useState<RiderRun | null>(null);
  const [onDuty, setOnDuty] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pairCode, setPairCode] = useState("");
  const [pairBusy, setPairBusy] = useState(false);
  const [riderName, setRiderName] = useState<string | null>(null);
  /** Local progression after pickup: mark arriving before delivered. */
  const [arrivingOrderId, setArrivingOrderId] = useState<number | null>(null);
  const [failFor, setFailFor] = useState<RiderStop | null>(null);

  useEffect(() => {
    const meta = document.querySelector('meta[name="viewport"]');
    const prev = meta?.getAttribute("content") ?? null;
    meta?.setAttribute("content", "width=device-width, initial-scale=1");
    return () => {
      if (meta && prev !== null) meta.setAttribute("content", prev);
    };
  }, []);

  const loadRun = useCallback(async () => {
    if (demoMode) {
      setRun((prev) => prev ?? MOCK_RUN);
      return;
    }
    if (!token) return;
    try {
      const data = await riderReq<RiderRun>("/api/v1/rider-app/orders", token);
      setRun(data);
      setOnDuty(data.onDuty);
      setError(null);
      // If API returns empty, keep mock so UI is still reviewable (API limited).
      if (!data.batchId && (!data.stops || data.stops.length === 0)) {
        setRun((prev) => prev ?? null);
      }
    } catch (e) {
      // Fall back to mock task list when API is limited / offline.
      setError(e instanceof Error ? e.message : "Could not load tasks");
      setRun((prev) => prev ?? MOCK_RUN);
      setDemoMode(true);
    }
  }, [token, demoMode]);

  useEffect(() => {
    if (!token && !demoMode) return;
    void loadRun();
    if (!demoMode && token) {
      const t = window.setInterval(() => void loadRun(), 15000);
      return () => window.clearInterval(t);
    }
  }, [token, demoMode, loadRun]);

  useEffect(() => {
    if (!token || demoMode) return;
    riderReq<{ riderName: string }>("/api/v1/rider-app/me", token)
      .then((me) => setRiderName(me.riderName))
      .catch(() => {
        /* optional */
      });
  }, [token, demoMode]);

  const pending = useMemo(
    () => (run?.stops ?? []).filter((st) => st.outcome === "pending"),
    [run],
  );
  const activeStop = pending[0] ?? null;
  const pickedUp = run?.status === "picked_up";
  const hasRun = Boolean(run?.batchId);
  const todayCod = useMemo(
    () => (run?.stops ?? []).reduce((sum, st) => sum + (st.codAmount || 0), 0),
    [run],
  );

  const primary: PrimaryAction = useMemo(() => {
    if (!hasRun) return "none";
    if (!pickedUp) return "pickup";
    if (!activeStop) return "idle";
    if (arrivingOrderId === activeStop.orderId) return "delivered";
    return "arriving";
  }, [hasRun, pickedUp, activeStop, arrivingOrderId]);

  async function pair() {
    setPairBusy(true);
    setError(null);
    try {
      const data = await riderReq<{ device_token: string; rider_name: string }>(
        "/api/v1/rider-app/pair",
        null,
        { method: "POST", body: JSON.stringify({ code: pairCode.trim().toUpperCase() }) },
      );
      localStorage.setItem(DEVICE_TOKEN_KEY, data.device_token);
      setToken(data.device_token);
      setRiderName(data.rider_name);
      setDemoMode(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pairing failed");
    } finally {
      setPairBusy(false);
    }
  }

  function enterDemo() {
    setDemoMode(true);
    setRun(structuredClone(MOCK_RUN));
    setOnDuty(true);
    setRiderName("Demo Rider");
    setError(null);
    setArrivingOrderId(null);
  }

  function unpair() {
    localStorage.removeItem(DEVICE_TOKEN_KEY);
    setToken(null);
    setDemoMode(false);
    setRun(null);
    setRiderName(null);
    setArrivingOrderId(null);
    setFailFor(null);
  }

  async function toggleDuty() {
    const next = !onDuty;
    setOnDuty(next);
    if (demoMode || !token) return;
    try {
      const res = await riderReq<{ onDuty: boolean }>("/api/v1/rider-app/duty", token, {
        method: "POST",
        body: JSON.stringify({ onDuty: next }),
      });
      setOnDuty(res.onDuty);
    } catch (e) {
      setOnDuty(!next);
      setError(e instanceof Error ? e.message : "Duty update failed");
    }
  }

  async function doPrimary() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (primary === "pickup") {
        if (demoMode || !token) {
          setRun((r) => (r ? { ...r, status: "picked_up" } : r));
        } else {
          const next = await riderReq<RiderRun>("/api/v1/rider-app/orders/pickup", token, {
            method: "POST",
          });
          setRun(next);
        }
      } else if (primary === "arriving" && activeStop) {
        // No dedicated arriving endpoint on rider-app API — local progress only.
        setArrivingOrderId(activeStop.orderId);
      } else if (primary === "delivered" && activeStop) {
        if (demoMode || !token) {
          setRun((r) =>
            r
              ? {
                  ...r,
                  stops: r.stops.map((st) =>
                    st.orderId === activeStop.orderId
                      ? { ...st, delivered: true, outcome: "delivered" as const }
                      : st,
                  ),
                }
              : r,
          );
          setArrivingOrderId(null);
        } else {
          await riderReq(`/api/v1/rider-app/orders/${activeStop.orderId}/delivered`, token, {
            method: "POST",
          });
          setArrivingOrderId(null);
          await loadRun();
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  async function doFailed(reason: string) {
    if (!failFor) return;
    setBusy(true);
    setError(null);
    try {
      if (demoMode || !token) {
        setRun((r) =>
          r
            ? {
                ...r,
                stops: r.stops.map((st) =>
                  st.orderId === failFor.orderId
                    ? { ...st, delivered: true, outcome: "not_delivered" as const }
                    : st,
                ),
              }
            : r,
        );
      } else {
        await riderReq(
          `/api/v1/rider-app/orders/${failFor.orderId}/not-delivered`,
          token,
          { method: "POST", body: JSON.stringify({ reason }) },
        );
        await loadRun();
      }
      setFailFor(null);
      setArrivingOrderId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not mark failed");
    } finally {
      setBusy(false);
    }
  }

  const primaryLabel =
    primary === "pickup"
      ? busy
        ? "…"
        : "Picked Up"
      : primary === "arriving"
        ? busy
          ? "…"
          : "Arriving"
        : primary === "delivered"
          ? busy
            ? "…"
            : activeStop
              ? `Delivered · Collect ${money(activeStop.codAmount)}`
              : "Delivered"
          : primary === "idle"
            ? "All stops done"
            : "No active task";

  const primaryClass =
    primary === "delivered"
      ? `${s.primary} ${s.primaryWarn}`
      : primary === "arriving"
        ? s.primary
        : s.primary;

  if (!token && !demoMode) {
    return (
      <main className={s.page}>
        <div className={s.pairWrap}>
          <div className={s.logo} aria-hidden>
            🛵
          </div>
          <h1>Rider App</h1>
          <p>Enter the pairing code from your WhatsApp invite, or try the demo task list.</p>
          <input
            className={s.pairInput}
            value={pairCode}
            onChange={(e) => setPairCode(e.target.value)}
            placeholder="AB3K9P"
            autoCapitalize="characters"
            autoCorrect="off"
            maxLength={12}
            aria-label="Pairing code"
          />
          {error ? <div className={s.error}>{error}</div> : null}
          <button
            type="button"
            className={s.primary}
            style={{ maxWidth: 280 }}
            disabled={pairBusy || pairCode.trim().length < 4}
            onClick={() => void pair()}
          >
            {pairBusy ? "Pairing…" : "Pair device"}
          </button>
          <button type="button" className={s.demoBtn} onClick={enterDemo}>
            Use demo task list
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className={s.page}>
      <header className={s.header}>
        <div>
          <h1>Deliveries</h1>
          <p className={s.headerMeta}>
            {riderName ?? "Rider"}
            {demoMode ? " · Demo" : ""}
          </p>
        </div>
        <span className={`${s.livePill} ${hasRun && pickedUp ? "" : s.livePillWarn}`}>
          {hasRun ? (pickedUp ? "EN ROUTE" : "PICKUP") : "STANDBY"}
        </span>
      </header>

      <button
        type="button"
        className={`${s.dutyBar} ${onDuty ? s.dutyOn : s.dutyOff}`}
        onClick={() => void toggleDuty()}
        data-testid="duty-toggle"
      >
        <span className={s.dutyLabel}>{onDuty ? "ON DUTY" : "OFF DUTY"}</span>
        <span aria-hidden>{onDuty ? "●" : "○"}</span>
      </button>
      {!onDuty ? (
        <p className={s.dutyHint}>No new assignments. Finish any open stops below.</p>
      ) : null}

      {hasRun ? (
        <div className={s.codStrip} data-testid="cod-strip">
          <span>COD this run</span>
          <strong>{money(todayCod)}</strong>
        </div>
      ) : null}

      {demoMode ? (
        <div className={s.mockBanner} data-testid="demo-banner">
          Demo / offline task list — actions update locally. Pair a device for live runs.
        </div>
      ) : null}

      {error ? <div className={s.error}>{error}</div> : null}

      {failFor ? (
        <div className={s.failPanel} role="dialog" aria-label="Failure reason" data-testid="fail-panel">
          <h3>Why couldn&apos;t you deliver {failFor.orderNumber}?</h3>
          <div className={s.failOptions}>
            {FAIL_REASONS.map((r) => (
              <button
                key={r.id}
                type="button"
                className={s.failOption}
                disabled={busy}
                onClick={() => void doFailed(r.id)}
              >
                {r.label}
              </button>
            ))}
          </div>
          <button type="button" className={s.ghost} onClick={() => setFailFor(null)}>
            Cancel
          </button>
        </div>
      ) : null}

      <div className={s.list}>
        {!hasRun ? (
          <div className={s.empty}>
            <strong>{onDuty ? "No deliveries right now" : "You're off duty"}</strong>
            {onDuty
              ? "You'll see tasks here when a run is assigned."
              : "Turn on duty to start receiving deliveries."}
          </div>
        ) : !pickedUp ? (
          <div className={`${s.card} ${s.cardActive}`} data-testid="pickup-card">
            <h2 className={s.orderNo}>
              {pending.length} {pending.length === 1 ? "order" : "orders"} ready to pick up
            </h2>
            {pending.map((st) => (
              <p key={st.orderId} className={s.line}>
                • {st.orderNumber}
                {st.customerName ? ` · ${st.customerName}` : ""}
                {st.codAmount > 0 ? ` · COD ${money(st.codAmount)}` : ""}
              </p>
            ))}
          </div>
        ) : pending.length === 0 ? (
          <div className={s.empty}>
            <strong>Run complete</strong>
            Head back to the restaurant.
          </div>
        ) : (
          pending.map((st, i) => (
            <article
              key={st.orderId}
              className={`${s.card} ${i === 0 ? s.cardActive : s.cardDim}`}
              data-testid={i === 0 ? "active-stop" : `stop-${st.orderId}`}
            >
              <div className={s.cardTop}>
                <h2 className={s.orderNo}>{st.orderNumber}</h2>
                <span className={`${s.seq} ${i === 0 ? s.seqFirst : ""}`}>
                  {i === 0 ? "DELIVER FIRST" : `LATER · ${i + 1}/${pending.length}`}
                </span>
              </div>
              {st.customerName ? <p className={s.cust}>{st.customerName}</p> : null}
              {st.address ? <p className={s.line}>📍 {st.address}</p> : null}
              {st.doNotCall ? (
                <p className={s.line}>🚫 Don&apos;t call — message only</p>
              ) : st.customerPhone ? (
                <a className={s.phoneLink} href={`tel:${st.customerPhone}`}>
                  📞 {st.customerPhone}
                </a>
              ) : null}
              <div className={s.codBadge} data-testid={`cod-${st.orderId}`}>
                COD {money(st.codAmount)}
              </div>
              {i === 0 && arrivingOrderId === st.orderId ? (
                <p className={s.line}>Status: Arriving — collect COD then mark delivered.</p>
              ) : null}
            </article>
          ))
        )}
      </div>

      <div className={s.actionBar} data-testid="primary-action-bar">
        {pickedUp && activeStop ? (
          <div className={s.secondaryRow}>
            <button
              type="button"
              className={s.secondary}
              disabled={busy}
              onClick={() => setFailFor(activeStop)}
            >
              Failed
            </button>
            {activeStop.latitude != null && activeStop.longitude != null ? (
              <a
                className={s.secondary}
                style={{
                  display: "grid",
                  placeItems: "center",
                  textDecoration: "none",
                }}
                href={`https://www.google.com/maps/dir/?api=1&destination=${activeStop.latitude},${activeStop.longitude}`}
                target="_blank"
                rel="noreferrer"
              >
                Navigate
              </a>
            ) : null}
          </div>
        ) : null}
        <button
          type="button"
          className={primaryClass}
          disabled={busy || primary === "none" || primary === "idle"}
          onClick={() => void doPrimary()}
          data-testid="primary-action"
        >
          {primaryLabel}
        </button>
        <button type="button" className={s.ghost} onClick={unpair}>
          {demoMode ? "Exit demo" : "Unpair device"}
        </button>
      </div>
    </main>
  );
}
