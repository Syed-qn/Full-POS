import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/Button";
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
import s from "./BranchOpsScreen.module.css";

export function AiInsightsScreen() {
  const [features, setFeatures] = useState<
    Array<{ key: string; status: string; path?: string }>
  >([]);
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
      setFeatures(f.features);
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

  return (
    <div className={s.page}>
      <PageHeader
        title="AI Insights"
        subtitle="25 AI features — sales, stock, reviews, upsell, festival, translation, calls, reservations"
      />

      <section className={s.card}>
        <h3 className={s.cardTitle}>Feature catalog ({features.length})</h3>
        <ul className={s.list}>
          {features.map((f) => (
            <li key={f.key}>
              <strong>{f.key}</strong> · {f.status}
              {f.path ? ` · ${f.path}` : ""}
            </li>
          ))}
        </ul>
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Generate insights</h3>
        <div className={s.row2}>
          <Button
            disabled={busy}
            onClick={() =>
              void run(generateDailySales, (r) => setLatestSummary(r.summary))
            }
          >
            Daily sales summary
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(() => generateSalesDrop(7), (r) => setLatestSummary(r.summary))
            }
          >
            Why sales dropped
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(() => generateStaffSummary(7), (r) => setLatestSummary(r.summary))
            }
          >
            Staff AI summary
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(() => generateSlowMoving(14), (r) => setLatestSummary(r.summary))
            }
          >
            Slow-moving items
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(generateFoodCost, (r) => setLatestSummary(r.summary))
            }
          >
            Food-cost anomalies
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(generateLowStock, (r) => setLatestSummary(r.summary))
            }
          >
            Low-stock prediction
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(generateSegments, (r) => setLatestSummary(r.summary))
            }
          >
            Customer segments
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(generateBundles, (r) => setLatestSummary(r.summary))
            }
          >
            Best menu bundles
          </Button>
        </div>
        {latestSummary && <p className={s.rowHint}>{latestSummary}</p>}
        {insights.length > 0 && (
          <ul className={s.list}>
            {insights.slice(0, 8).map((i) => (
              <li key={i.id}>
                <strong>{i.title}</strong>: {i.summary}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Marketing AI · upsell · recovery</h3>
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>Festival</span>
            <input className={s.input} value={festival} onChange={(e) => setFestival(e.target.value)} />
          </label>
        </div>
        <div className={s.row2}>
          <Button
            disabled={busy}
            onClick={() =>
              void run(() => generateFestival(festival), (r) => setLatestSummary(r.summary))
            }
          >
            Festival campaign
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(reorderPrompt, (r) => setLatestSummary(r.body))
            }
          >
            Reorder prompt copy
          </Button>
          <Button
            disabled={busy}
            onClick={() =>
              void run(
                () => abandonedCopy("2x Biryani"),
                (r) => setLatestSummary(r.body),
              )
            }
          >
            Abandoned cart copy
          </Button>
          <Button disabled={busy} onClick={() => void run(translateMenu)}>
            Translate menu → AR
          </Button>
        </div>
        {combos.length > 0 && (
          <ul className={s.list}>
            {combos.slice(0, 5).map((c, idx) => (
              <li key={idx}>
                {c.items.join(" + ")} — {c.ai_message}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Reviews · reply · escalation</h3>
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>Comment</span>
            <input
              className={s.input}
              value={reviewComment}
              onChange={(e) => setReviewComment(e.target.value)}
            />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Score (0–10)</span>
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
        <div className={s.row2}>
          <Button
            disabled={busy}
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
          <Button disabled={busy} onClick={() => void run(escalateNegativeReviews)}>
            Escalate negative NPS
          </Button>
        </div>
        {reviews.length > 0 && (
          <ul className={s.list}>
            {reviews.slice(0, 5).map((r) => (
              <li key={r.id}>
                {r.sentiment}
                {r.escalated ? " · escalated" : ""}: {r.suggested_reply}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Reservations (AI handled)</h3>
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>Party size</span>
            <input
              className={s.input}
              type="number"
              min={1}
              value={partySize}
              onChange={(e) => setPartySize(Number(e.target.value) || 2)}
            />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Guest name</span>
            <input className={s.input} value={guestName} onChange={(e) => setGuestName(e.target.value)} />
          </label>
        </div>
        <Button
          disabled={busy}
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
        {reservations.length > 0 && (
          <ul className={s.list}>
            {reservations.slice(0, 5).map((r) => (
              <li key={r.id}>
                #{r.id} {r.guest_name} · party {r.party_size} · {r.status}
                {r.ai_summary ? ` — ${r.ai_summary}` : ""}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>AI call answering (mock IVR)</h3>
        <div className={s.row2}>
          <Button
            disabled={busy}
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
          <label className={s.col}>
            <span className={s.rowName}>Caller text</span>
            <input className={s.input} value={callText} onChange={(e) => setCallText(e.target.value)} />
          </label>
          <Button
            disabled={busy || !callId}
            onClick={() =>
              void run(
                () => turnCall(callId!, callText),
                (r) => setCallTranscript(r.transcript),
              )
            }
          >
            Send turn
          </Button>
        </div>
        {callTranscript.length > 0 && (
          <ul className={s.list}>
            {callTranscript.map((t, i) => (
              <li key={i}>
                <strong>{t.role}</strong>: {t.text}
              </li>
            ))}
          </ul>
        )}
        {calls.length > 0 && (
          <p className={s.rowHint}>
            Sessions: {calls.map((c) => `#${c.id} ${c.status}/${c.outcome ?? "-"}`).join(" · ")}
          </p>
        )}
      </section>
    </div>
  );
}
