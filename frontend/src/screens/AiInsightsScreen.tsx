import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  type AiInsight,
  abandonedCopy,
  createReservation,
  escalateNegativeReviews,
  generateBundles,
  generateDailySales,
  generateFestival,
  generateFoodCost,
  generateLowStock,
  generateSalesDrop,
  generateSegments,
  generateSlowMoving,
  generateStaffSummary,
  getCombos,
  listAiFeatures,
  listCalls,
  listInsights,
  listReservations,
  listReviewReplies,
  reorderPrompt,
  startCall,
  suggestReviewReply,
  translateMenu,
  turnCall,
} from "../lib/aiApi";
import s from "./AiInsightsScreen.module.css";

type Panel = "insights" | "marketing" | "reviews" | "reservations" | "calls";

const PANELS: Array<[Panel, string]> = [
  ["insights", "Insights"],
  ["marketing", "Marketing AI"],
  ["reviews", "Reviews"],
  ["reservations", "Reservations"],
  ["calls", "Calls"],
];

/** The eight insight generators, as clean labelled actions. */
const GENERATORS: Array<{ label: string; run: () => Promise<AiInsight> }> = [
  { label: "Daily sales summary", run: generateDailySales },
  { label: "Why sales dropped", run: () => generateSalesDrop(7) },
  { label: "Staff AI summary", run: () => generateStaffSummary(7) },
  { label: "Slow moving items", run: () => generateSlowMoving(14) },
  { label: "Food cost anomalies", run: generateFoodCost },
  { label: "Low stock prediction", run: generateLowStock },
  { label: "Customer segments", run: generateSegments },
  { label: "Best menu bundles", run: generateBundles },
];

/** Prettify an insight kind slug ("sales_drop") into a label ("Sales drop"). */
function prettyKind(kind: string): string {
  if (!kind) return "Insight";
  const t = kind.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function AiInsightsScreen() {
  const [featureCount, setFeatureCount] = useState(0);
  const [insights, setInsights] = useState<AiInsight[]>([]);
  const [reviews, setReviews] = useState<
    Array<{ id: number; sentiment: string; suggested_reply: string; escalated: boolean }>
  >([]);
  const [reservations, setReservations] = useState<
    Array<{ id: number; status: string; party_size: number; guest_name: string | null; ai_summary: string | null }>
  >([]);
  const [calls, setCalls] = useState<
    Array<{ id: number; status: string; outcome: string | null }>
  >([]);
  const [combos, setCombos] = useState<Array<{ items: string[]; ai_message: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [latestSummary, setLatestSummary] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>("insights");
  const [kindFilter, setKindFilter] = useState<string>("all");

  // forms
  const [festival, setFestival] = useState("Eid");
  const [reviewComment, setReviewComment] = useState("Food was cold");
  const [reviewScore, setReviewScore] = useState(3);
  const [partySize, setPartySize] = useState(4);
  const [guestName, setGuestName] = useState("");
  const [callId, setCallId] = useState<number | null>(null);
  const [callText, setCallText] = useState("I want to order biryani");
  const [callTranscript, setCallTranscript] = useState<Array<{ role: string; text: string }>>([]);

  const reload = useCallback(async () => {
    try {
      const [f, i, r, res, c, comb] = await Promise.all([
        listAiFeatures(),
        listInsights(),
        listReviewReplies().catch(() => []),
        listReservations().catch(() => []),
        listCalls().catch(() => []),
        getCombos().catch(() => ({ combos: [] })),
      ]);
      setFeatureCount(f.features.length);
      setInsights(i);
      setReviews(r);
      setReservations(res);
      setCalls(c);
      setCombos(comb.combos ?? []);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Load failed", "error");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function run<T>(fn: () => Promise<T>, ok?: (v: T) => void) {
    setBusy(true);
    try {
      const v = await fn();
      ok?.(v);
      await reload();
      toast("Done", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    } finally {
      setBusy(false);
    }
  }

  const kinds = useMemo(() => {
    const set = new Set(insights.map((i) => i.kind).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [insights]);

  const visibleInsights = useMemo(() => {
    if (kindFilter === "all") return insights;
    return insights.filter((i) => i.kind === kindFilter);
  }, [insights, kindFilter]);

  function regenerateForKind(kind: string) {
    const map: Record<string, () => Promise<AiInsight>> = {
      daily_sales: generateDailySales,
      sales_drop: () => generateSalesDrop(7),
      staff_summary: () => generateStaffSummary(7),
      slow_moving: () => generateSlowMoving(14),
      food_cost: generateFoodCost,
      low_stock: generateLowStock,
      segments: generateSegments,
      bundles: generateBundles,
    };
    const fn = map[kind];
    if (!fn) {
      toast("No regenerate action for this insight type", "error");
      return;
    }
    void run(fn, (r) => setLatestSummary(r.summary));
  }

  const kpis: Array<{ label: string; value: number }> = [
    { label: "Insights", value: insights.length },
    { label: "Review replies", value: reviews.length },
    { label: "Reservations", value: reservations.length },
    { label: "AI features live", value: featureCount },
  ];

  return (
    <div className={s.screen}>
      <PageHeader
        title="AI Insights"
        subtitle="Generate sales and stock insights, reply to reviews, plan campaigns, and handle reservations and calls."
      />

      {/* Overview KPIs — same glanceable strip as Forecast and Analytics. */}
      <div className={s.kpis}>
        {kpis.map((k) => (
          <div className={s.kpi} key={k.label}>
            <span className={s.kpiNum}>{k.value}</span>
            <span className={s.kpiLabel}>{k.label}</span>
          </div>
        ))}
      </div>

      <div className={s.pills} role="tablist" aria-label="AI panels">
        {PANELS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={panel === key}
            className={`${s.pill} ${panel === key ? s.pillActive : ""}`}
            onClick={() => setPanel(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Whatever the last generator/reply produced, pinned for quick copy. */}
      {latestSummary && (
        <div className={`${s.card} ${s.focusCard}`}>
          <div className={s.cardHead}>
            <h3 className={s.cardTitle}>Latest AI output</h3>
            <span className={s.cardSub}>The most recent generated text</span>
          </div>
          <p className={s.focusText}>{latestSummary}</p>
        </div>
      )}

      {panel === "insights" && (
        <>
          <section className={s.card}>
            <div className={s.cardHead}>
              <h3 className={s.cardTitle}>Generate an insight</h3>
              <span className={s.cardSub}>Pick a report for the AI to write up</span>
            </div>
            <div className={s.genGrid}>
              {GENERATORS.map((g) => (
                <Button
                  key={g.label}
                  disabled={busy}
                  variant="ghost"
                  onClick={() => void run(g.run, (r) => setLatestSummary(r.summary))}
                >
                  {g.label}
                </Button>
              ))}
            </div>
          </section>

          <section className={s.card}>
            <div className={s.cardHead}>
              <h3 className={s.cardTitle}>Insights</h3>
              <span className={s.cardSub}>
                {visibleInsights.length} of {insights.length} shown
              </span>
            </div>
            {kinds.length > 1 && (
              <div className={s.pills} role="group" aria-label="Insight kinds">
                {kinds.map((k) => (
                  <button
                    key={k}
                    type="button"
                    className={`${s.pill} ${kindFilter === k ? s.pillActive : ""}`}
                    onClick={() => setKindFilter(k)}
                  >
                    {k === "all" ? "All" : prettyKind(k)}
                  </button>
                ))}
              </div>
            )}
            {visibleInsights.length === 0 ? (
              <EmptyState
                title="No insights yet"
                description="Run a generator above to create sales, stock, or menu insights."
              />
            ) : (
              <div className={s.bento}>
                {visibleInsights.slice(0, 12).map((i) => (
                  <article key={i.id} className={s.insightCard}>
                    <span className={s.tagAi}>{prettyKind(i.kind)}</span>
                    <h4 className={s.insightTitle}>{i.title}</h4>
                    <p className={s.insightSummary}>{i.summary}</p>
                    <div className={s.cardActions}>
                      <Button type="button" variant="ghost" onClick={() => setLatestSummary(i.summary)}>
                        Focus
                      </Button>
                      <Button type="button" disabled={busy} onClick={() => regenerateForKind(i.kind)}>
                        Regenerate
                      </Button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {panel === "marketing" && (
        <section className={s.card}>
          <div className={s.cardHead}>
            <h3 className={s.cardTitle}>Marketing AI</h3>
            <span className={s.cardSub}>Campaigns, upsell copy, and cart recovery</span>
          </div>
          <div className={s.formRow}>
            <label className={s.field}>
              <span className={s.fieldName}>Festival</span>
              <input className={s.input} value={festival} onChange={(e) => setFestival(e.target.value)} />
            </label>
          </div>
          <div className={s.genGrid}>
            <Button
              disabled={busy}
              variant="ghost"
              onClick={() => void run(() => generateFestival(festival), (r) => setLatestSummary(r.summary))}
            >
              Festival campaign
            </Button>
            <Button
              disabled={busy}
              variant="ghost"
              onClick={() => void run(reorderPrompt, (r) => setLatestSummary(r.body))}
            >
              Reorder prompt copy
            </Button>
            <Button
              disabled={busy}
              variant="ghost"
              onClick={() => void run(() => abandonedCopy("2x Biryani"), (r) => setLatestSummary(r.body))}
            >
              Abandoned cart copy
            </Button>
            <Button disabled={busy} variant="ghost" onClick={() => void run(translateMenu)}>
              Translate menu to Arabic
            </Button>
          </div>
          {combos.length > 0 && (
            <div className={s.comboList}>
              {combos.slice(0, 5).map((c, idx) => (
                <div className={s.comboRow} key={idx}>
                  <span className={s.comboItems}>{c.items.join(" + ")}</span>
                  <span className={s.comboMsg}>{c.ai_message}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {panel === "reviews" && (
        <section className={s.card}>
          <div className={s.cardHead}>
            <h3 className={s.cardTitle}>Reviews</h3>
            <span className={s.cardSub}>Suggest replies and escalate the negative ones</span>
          </div>
          <div className={s.formRow}>
            <label className={s.field}>
              <span className={s.fieldName}>Comment</span>
              <input
                className={s.input}
                value={reviewComment}
                onChange={(e) => setReviewComment(e.target.value)}
              />
            </label>
            <label className={s.fieldNarrow}>
              <span className={s.fieldName}>Score (0 to 10)</span>
              <input
                className={s.input}
                type="number"
                min={0}
                max={10}
                value={reviewScore}
                onChange={(e) => setReviewScore(Number(e.target.value))}
              />
            </label>
          </div>
          <div className={s.genGrid}>
            <Button
              disabled={busy}
              variant="ghost"
              onClick={() =>
                void run(
                  () =>
                    suggestReviewReply({
                      comment: reviewComment,
                      score: reviewScore,
                      escalate: reviewScore <= 6,
                    }),
                  (r) => setLatestSummary(r.suggested_reply),
                )
              }
            >
              Suggest reply
            </Button>
            <Button disabled={busy} variant="ghost" onClick={() => void run(escalateNegativeReviews)}>
              Escalate negative NPS
            </Button>
          </div>
          {reviews.length > 0 ? (
            <div className={s.bento}>
              {reviews.slice(0, 6).map((r) => (
                <article key={r.id} className={s.insightCard}>
                  <span className={r.escalated ? s.tagWarn : s.tagAi}>
                    {r.sentiment}
                    {r.escalated ? " · escalated" : ""}
                  </span>
                  <p className={s.insightSummary}>{r.suggested_reply}</p>
                  <div className={s.cardActions}>
                    <Button type="button" variant="ghost" onClick={() => setLatestSummary(r.suggested_reply)}>
                      Use reply
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="No review replies yet" description="Suggest a reply from a comment above." />
          )}
        </section>
      )}

      {panel === "reservations" && (
        <section className={s.card}>
          <div className={s.cardHead}>
            <h3 className={s.cardTitle}>Reservations</h3>
            <span className={s.cardSub}>AI handled bookings</span>
          </div>
          <div className={s.formRow}>
            <label className={s.fieldNarrow}>
              <span className={s.fieldName}>Party size</span>
              <input
                className={s.input}
                type="number"
                min={1}
                value={partySize}
                onChange={(e) => setPartySize(Number(e.target.value) || 2)}
              />
            </label>
            <label className={s.field}>
              <span className={s.fieldName}>Guest name</span>
              <input className={s.input} value={guestName} onChange={(e) => setGuestName(e.target.value)} />
            </label>
          </div>
          <div className={s.genGrid}>
            <Button
              disabled={busy}
              variant="ghost"
              onClick={() => {
                const when = new Date(Date.now() + 86400000).toISOString();
                void run(
                  () =>
                    createReservation({
                      party_size: partySize,
                      requested_for: when,
                      guest_name: guestName || "Guest",
                    }),
                  (r) => setLatestSummary((r as { ai_summary?: string }).ai_summary ?? "Booked"),
                );
              }}
            >
              Create reservation
            </Button>
          </div>
          {reservations.length > 0 ? (
            <div className={s.bento}>
              {reservations.slice(0, 6).map((r) => (
                <article key={r.id} className={s.insightCard}>
                  <span className={s.tagAi}>{r.status}</span>
                  <h4 className={s.insightTitle}>
                    {r.guest_name || "Guest"} · party of {r.party_size}
                  </h4>
                  {r.ai_summary && <p className={s.insightSummary}>{r.ai_summary}</p>}
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="No reservations" description="Create a reservation to see AI handling notes." />
          )}
        </section>
      )}

      {panel === "calls" && (
        <section className={s.card}>
          <div className={s.cardHead}>
            <h3 className={s.cardTitle}>AI call answering</h3>
            <span className={s.cardSub}>Mock IVR to preview how calls are handled</span>
          </div>
          <div className={s.formRow}>
            <Button
              disabled={busy}
              variant="ghost"
              onClick={() =>
                void run(
                  () => startCall("+971500000001"),
                  (r) => {
                    setCallId(r.id);
                    setCallTranscript(r.transcript);
                  },
                )
              }
            >
              Start call
            </Button>
            <label className={s.field}>
              <span className={s.fieldName}>Caller text</span>
              <input className={s.input} value={callText} onChange={(e) => setCallText(e.target.value)} />
            </label>
            <Button
              disabled={busy || !callId}
              variant="ghost"
              onClick={() => void run(() => turnCall(callId!, callText), (r) => setCallTranscript(r.transcript))}
            >
              Send turn
            </Button>
          </div>
          {callTranscript.length > 0 && (
            <div className={s.chat}>
              {callTranscript.map((t, i) => (
                <div
                  key={i}
                  className={`${s.bubble} ${t.role === "assistant" ? s.bubbleAi : s.bubbleUser}`}
                >
                  <span className={s.bubbleRole}>{t.role === "assistant" ? "AI" : "Caller"}</span>
                  {t.text}
                </div>
              ))}
            </div>
          )}
          {calls.length > 0 && (
            <p className={s.cardSub}>
              {calls.length} call session{calls.length === 1 ? "" : "s"} recorded
            </p>
          )}
        </section>
      )}
    </div>
  );
}
