import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  accountantExport,
  createRefundNote,
  getEInvoiceReadiness,
  getTaxSettings,
  listEInvoiceTransmissions,
  listRefundNotes,
  listRetentionRuns,
  patchTaxSettings,
  runRetention,
  transmitEInvoice,
  type TaxSettings,
} from "../lib/complianceApi";
import { clearTaxConfigCache } from "../lib/useTaxConfig";
import s from "./ComplianceScreen.module.css";

type ComplianceTab = "tax" | "einvoice" | "refunds" | "retention" | "export";

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function monthStartISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

/** First day of the previous month. Day 0 of this month is the last of the one
 *  before, which handles year rollover and month lengths without a table. */
function lastMonthStartISO() {
  const d = new Date();
  return iso(new Date(d.getFullYear(), d.getMonth() - 1, 1));
}

function lastMonthEndISO() {
  const d = new Date();
  return iso(new Date(d.getFullYear(), d.getMonth(), 0));
}

/** The API's own limits (TaxSettingsPatch: ge=30, le=3650). Mirrored here so the
 *  form can explain them instead of letting the server reject the save. */
/** The API stores a rate ("0.0500"); the form shows a percentage ("5"). */
function rateToPercent(rate: unknown): string {
  const n = Number(rate);
  if (!Number.isFinite(n)) return "5";
  // Trim the float noise 0.0825 * 100 would otherwise produce.
  return String(Number((n * 100).toFixed(4)));
}

const RETENTION_MIN = 30;
const RETENTION_MAX = 3650;

/**
 * Hidden, not deleted.
 *
 * The only ASP adapter that exists is the mock, which files nothing with the
 * Federal Tax Authority, so the tab let you press Send and watch a fabricated
 * MOCK-AE reference come back looking exactly like a real filing. The screen,
 * the API, the guard and the transmission table all stay put; flip this to true
 * the day an accredited provider is contracted.
 */
const SHOW_EINVOICE_TAB = false;

/**
 * Hidden, not deleted.
 *
 * Despite the name, the retention purge is not a compliance feature: it deletes
 * app error logs, idempotency keys and never-confirmed draft carts, and
 * explicitly leaves every fiscal record alone. That is disk housekeeping, and it
 * belongs on a nightly schedule, not on a button an owner presses on a screen
 * about tax law. Nothing calls `run_data_retention` except that button, so today
 * the tab's only effect is to invite someone to press Purge and wonder what they
 * just destroyed. The retention DAYS field on Tax profile stays: it is the
 * 7-year record-keeping window a scheduled job would read.
 */
const SHOW_RETENTION_TAB = false;

export function ComplianceScreen() {
  const [tax, setTax] = useState<TaxSettings | null>(null);
  const [readiness, setReadiness] = useState<{
    ready: boolean;
    e_invoice_enabled: boolean;
    asp_provider: string;
    missing_fields: string[];
    is_live: boolean;
    blockers: string[];
    summary: string;
    notes: string;
    structured_profile: string;
  } | null>(null);
  const [refunds, setRefunds] = useState<
    Array<{
      id: number;
      refund_note_number: string;
      order_id: number;
      amount_aed: string;
      vat_amount_aed: string;
      reason: string | null;
      issued_at: string | null;
    }>
  >([]);
  const [txns, setTxns] = useState<
    Array<{ id: number; order_id: number; status: string; external_id: string | null }>
  >([]);
  const [runs, setRuns] = useState<
    Array<{ id: number; status: string; purged_counts: Record<string, number> }>
  >([]);
  // The whole summary object, not a pre-joined sentence. Six figures run
  // together in one grey line is the shape of a log message, not of numbers an
  // accountant is going to read off and reconcile.
  const [exportSummary, setExportSummary] = useState<{
    order_count: number;
    net_total_aed: string;
    vat_total_aed: string;
    gross_total_aed: string;
    refund_note_count: number;
    credit_note_count: number;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  // The form fields are seeded with plausible-looking values (5%, exclusive,
  // 2555 days) so the inputs are controlled from the first render. Those are
  // placeholders, not this restaurant's settings, and showing them while the
  // real ones are still in flight reads as fact: a restaurant on 20% saw "5"
  // sitting in the VAT box. Nothing renders until the server has answered.
  const [loaded, setLoaded] = useState(false);

  // editable tax fields
  const [trn, setTrn] = useState("");
  const [legalName, setLegalName] = useState("");
  const [legalNameAr, setLegalNameAr] = useState("");
  const [mode, setMode] = useState<"exclusive" | "inclusive">("exclusive");
  // Entered as a PERCENTAGE ("5"), stored by the API as a rate ("0.0500").
  // Nobody running a restaurant thinks in 0.0500, and the screen previously
  // printed the raw rate as read-only text with no way to change it at all.
  const [vatPercent, setVatPercent] = useState("5");
  const [eInv, setEInv] = useState(false);
  // Kept as text, not a number. `Number(e.target.value) || 2555` silently
  // rewrote an empty box, or a typed "0", back to 2555 while you were still
  // typing, so the field fought the person using it.
  const [retentionDays, setRetentionDays] = useState("2555");

  // action forms
  const [rnOrderId, setRnOrderId] = useState("");
  const [rnAmount, setRnAmount] = useState("");
  const [rnReason, setRnReason] = useState("");
  const [rnOpen, setRnOpen] = useState(false);
  const [eiOrderId, setEiOrderId] = useState("");
  const [buyerTrn, setBuyerTrn] = useState("");
  const [exportStart, setExportStart] = useState(monthStartISO());
  const [exportEnd, setExportEnd] = useState(todayISO());
  const [tab, setTab] = useState<ComplianceTab>("tax");

  const reload = useCallback(async () => {
    try {
      const [t, r, notes, transmissions, retention] = await Promise.all([
        getTaxSettings(),
        getEInvoiceReadiness(),
        listRefundNotes(),
        listEInvoiceTransmissions(),
        listRetentionRuns().catch(() => []),
      ]);
      setTax(t);
      setTrn(t.trn ?? "");
      setLegalName(t.legal_name ?? "");
      setLegalNameAr(t.legal_name_ar ?? "");
      setMode((t.tax_pricing_mode as "exclusive" | "inclusive") || "exclusive");
      setEInv(!!t.e_invoice_enabled);
      setVatPercent(rateToPercent(t.default_vat_rate));
      setRetentionDays(String(t.data_retention_days ?? 2555));
      setReadiness(r);
      setRefunds(notes);
      setTxns(transmissions);
      setRuns(retention);
      setLoaded(true);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Load failed", "error");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function saveTax() {
    setBusy(true);
    try {
      // The API accepts 30..3650 and returns a raw validation blob outside it.
      // Saying so here means the limit is explained in the form rather than
      // discovered by pressing Save and reading a 422.
      const days = Number(retentionDays);
      if (!Number.isInteger(days) || days < RETENTION_MIN || days > RETENTION_MAX) {
        toast(
          `Data retention must be a whole number between ${RETENTION_MIN} and ${RETENTION_MAX} days (about 1 month to 10 years).`,
          "error",
        );
        setBusy(false);
        return;
      }
      const pct = Number(vatPercent);
      if (!Number.isFinite(pct) || pct < 0 || pct > 100) {
        toast("VAT rate must be a percentage between 0 and 100.", "error");
        setBusy(false);
        return;
      }
      const updated = await patchTaxSettings({
        trn: trn.trim() || null,
        legal_name: legalName.trim() || null,
        legal_name_ar: legalNameAr.trim() || null,
        tax_pricing_mode: mode,
        default_vat_rate: pct / 100,
        e_invoice_enabled: eInv,
        data_retention_days: days,
      });
      setTax(updated);
      // The tills cache this. Without the drop, a rate change only reached them
      // on the next full page load, which on a till is the next shift.
      clearTaxConfigCache();
      toast("Tax settings saved", "success");
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onRefundNote() {
    const oid = Number(rnOrderId);
    if (!oid || !rnAmount) {
      toast("Order id and amount required", "error");
      return;
    }
    setBusy(true);
    try {
      const note = await createRefundNote({
        order_id: oid,
        amount_aed: rnAmount,
        reason: rnReason || undefined,
      });
      toast(`Refund note ${note.refund_note_number} issued`, "success");
      setRnOrderId("");
      setRnAmount("");
      setRnReason("");
      // Only on success. A failed issue keeps the dialog open with what was
      // typed still in it, so the number can be corrected instead of re-entered.
      setRnOpen(false);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Refund note failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onTransmit() {
    const num = eiOrderId.trim();
    if (!num) {
      toast("Enter the order number from the bill, for example R1-0007.", "error");
      return;
    }
    setBusy(true);
    try {
      const row = await transmitEInvoice({
        order_number: num,
        buyer_trn: buyerTrn.trim() || undefined,
        document_type: buyerTrn.trim() ? "tax_invoice" : undefined,
      });
      toast(`E-invoice ${row.status}${row.external_id ? `, ref ${row.external_id}` : ""}`, "success");
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Transmit failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onRetention(dryRun: boolean) {
    setBusy(true);
    try {
      const run = await runRetention({ dry_run: dryRun, retention_days: Number(retentionDays) });
      toast(
        dryRun
          ? `Retention dry-run: ${JSON.stringify(run.purged_counts)}`
          : `Retention completed: ${JSON.stringify(run.purged_counts)}`,
        "success",
      );
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Retention failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onExport(format: "json" | "csv") {
    // The server rejects an inverted range with a raw 400. Saying so here means
    // the mistake is named where it was made.
    if (exportEnd < exportStart) {
      toast("The end date is before the start date.", "error");
      return;
    }
    setBusy(true);
    try {
      const pack = await accountantExport(exportStart, exportEnd, format);
      setExportSummary(pack.summary);
      if (format === "csv" && pack.csv) {
        const blob = new Blob([pack.csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `accountant-${exportStart}-${exportEnd}.csv`;
        a.click();
        URL.revokeObjectURL(url);
        toast("CSV downloaded", "success");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Export failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.page}>
      <PageHeader
        title="Compliance (UAE)"
        subtitle="VAT settings, tax invoices, credit notes, retention and the accountant export"
      />

      {/* The four status cards are gone. Three of them counted rows that are
          listed in full one tab away, and "E-invoice ready: No" repeated what
          the E-invoice tab already says in a sentence with the reason attached.
          A strip of numbers nobody acts on is not a dashboard. */}
      <div className={s.tabBar}>
        <div className={s.tabGroup} role="tablist" aria-label="Compliance sections">
          {(
            [
              ["tax", "Tax profile"],
              ...(SHOW_EINVOICE_TAB ? ([["einvoice", "E-invoice"]] as const) : []),
              ["refunds", "Refund notes"],
              ...(SHOW_RETENTION_TAB ? ([["retention", "Retention"]] as const) : []),
              ["export", "Accountant export"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={`${s.tab} ${tab === key ? s.tabActive : ""}`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "tax" && !loaded && (
        <section className={s.card} aria-busy="true" aria-label="Loading tax settings">
          <h3 className={s.cardTitle}>Tax settings and branch TRN</h3>
          <div className={s.row2}>
            {["TRN", "Tax pricing mode", "VAT rate (%)", "Legal name (EN)", "Legal name (AR)", "Data retention (days)"].map(
              (label) => (
                <div key={label} className={s.col}>
                  <span className={s.rowName}>{label}</span>
                  <span className={s.skelInput} />
                </div>
              ),
            )}
          </div>
        </section>
      )}

      {tab === "tax" && loaded && (
      <section className={s.card}>
        <h3 className={s.cardTitle}>Tax settings and branch TRN</h3>
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>TRN</span>
            <input className={s.input} value={trn} onChange={(e) => setTrn(e.target.value)} maxLength={32} />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Tax pricing mode</span>
            <select
              className={s.input}
              value={mode}
              onChange={(e) => setMode(e.target.value as "exclusive" | "inclusive")}
            >
              <option value="exclusive">Tax exclusive (VAT on top)</option>
              <option value="inclusive">Tax inclusive (VAT extracted)</option>
            </select>
          </label>
          <label className={s.col}>
            <span className={s.rowName}>VAT rate (%)</span>
            <input
              className={s.input}
              type="number"
              min={0}
              max={100}
              step="0.01"
              value={vatPercent}
              onChange={(e) => setVatPercent(e.target.value)}
            />
            <span className={s.fieldHint}>UAE standard is 5. Applies to new orders.</span>
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Legal name (EN)</span>
            <input className={s.input} value={legalName} onChange={(e) => setLegalName(e.target.value)} />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Legal name (AR)</span>
            <input
              className={s.input}
              value={legalNameAr}
              onChange={(e) => setLegalNameAr(e.target.value)}
              dir="rtl"
            />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Data retention (days)</span>
            <input
              className={s.input}
              type="number"
              min={RETENTION_MIN}
              max={RETENTION_MAX}
              value={retentionDays}
              onChange={(e) => setRetentionDays(e.target.value)}
            />
            <span className={s.fieldHint}>
              {RETENTION_MIN} to {RETENTION_MAX}. 2555 is 7 years.
            </span>
          </label>
          {/* Hidden with the tab it governs. A switch whose feature has no screen
              is a control that appears to do nothing. The value is still saved
              and still enforced server-side. */}
          {SHOW_EINVOICE_TAB && (
            <label className={s.checkRow}>
              <input type="checkbox" checked={eInv} onChange={(e) => setEInv(e.target.checked)} />
              <span className={s.rowName}>E-invoicing enabled</span>
            </label>
          )}
        </div>
        {/* Read-only trivia, dropped. The threshold is applied automatically per
            order and cannot be changed from here, and the provider name only
            meant anything while the E-invoice tab existed. */}
        <div className={s.stickySave}>
          <Button size="md" onClick={() => void saveTax()} disabled={busy}>
            Save tax settings
          </Button>
        </div>
      </section>
      )}

      {SHOW_EINVOICE_TAB && tab === "einvoice" && (
      <section className={s.card}>
        <h3 className={s.cardTitle}>Send invoices to the tax authority</h3>
        {/* Sentences, not a field dump. "Ready: no / Missing: trn, legal_name"
            told a manager nothing about what to go and do. */}
        {readiness ? (
          <>
            <p className={s.rowHint}>{readiness.summary}</p>
            {(readiness.blockers ?? []).length > 0 && (
              <ul className={s.list}>
                {(readiness.blockers ?? []).map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <p className={s.rowHint}>Loading…</p>
        )}
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>Order number</span>
            <input
              className={s.input}
              value={eiOrderId}
              onChange={(e) => setEiOrderId(e.target.value)}
              placeholder="R1-0007"
            />
            <span className={s.fieldHint}>The number printed on the bill.</span>
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Buyer TRN</span>
            <input className={s.input} value={buyerTrn} onChange={(e) => setBuyerTrn(e.target.value)} />
            <span className={s.fieldHint}>
              Only for business customers. Filling it in makes this a full tax invoice
              instead of a simplified one.
            </span>
          </label>
        </div>
        {/* Disabled, not hidden. The tab still has to show past transmissions
            and what is missing; it is the ACTION that the switch governs. The
            server refuses too, so this is a courtesy, not the control. */}
        {!tax?.e_invoice_enabled && (
          <p className={s.rowHint}>
            E-invoicing is switched off. Turn it on under Tax profile to transmit.
          </p>
        )}
        <div className={s.actions}>
          <Button
            size="md"
            onClick={() => void onTransmit()}
            disabled={busy || !tax?.e_invoice_enabled}
          >
            {readiness?.is_live ? `Send via ${tax?.asp_provider}` : "Send (test run)"}
          </Button>
        </div>
        {txns.length > 0 ? (
          <ul className={s.list}>
            {txns.slice(0, 10).map((t) => (
              <li key={t.id}>
                #{t.id} order {t.order_id}, {t.status}
                {t.external_id ? `, ref ${t.external_id}` : ""}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No transmissions yet" description="Transmit an order to see ASP status." />
        )}
      </section>
      )}

      {tab === "refunds" && (
      <section className={s.card}>
        {/* The issue form used to sit permanently above the list, so three empty
            boxes were the first thing on a screen whose job is to show the notes
            already issued. Issuing is the occasional action; reading the list is
            the constant one. */}
        <div className={s.cardHead}>
          <h3 className={s.cardTitle}>Refund notes</h3>
          <Button size="md" onClick={() => setRnOpen(true)} disabled={busy}>
            New refund note
          </Button>
        </div>
        {refunds.length > 0 ? (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Note</th>
                  <th>Order</th>
                  <th className={s.num}>Amount</th>
                  <th className={s.num}>VAT reclaimed</th>
                  <th className={s.grow}>Reason</th>
                  <th>Issued</th>
                </tr>
              </thead>
              <tbody>
                {refunds.map((n) => (
                  <tr key={n.id}>
                    <td className={s.mono}>{n.refund_note_number}</td>
                    <td>{n.order_id}</td>
                    <td className={s.num}>AED {n.amount_aed}</td>
                    <td className={s.num}>AED {n.vat_amount_aed ?? "0.00"}</td>
                    <td>{n.reason || "not stated"}</td>
                    <td>{n.issued_at ? new Date(n.issued_at).toLocaleDateString() : "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No refund notes yet"
            description="Issue one whenever you refund a customer, so the VAT you already declared is reclaimed."
          />
        )}
      </section>
      )}

      {rnOpen && (
        <ConfirmDialog
          title="Issue a refund note"
          message="Records a refund against an order and reclaims the VAT you already declared on it. The note number is allocated automatically."
          confirmLabel="Issue note"
          size="md"
          busy={busy}
          confirmDisabled={!rnOrderId.trim() || !rnAmount.trim()}
          onCancel={() => setRnOpen(false)}
          onConfirm={() => void onRefundNote()}
        >
          <div className={s.dialogFields}>
            <label className={s.col}>
              <span className={s.rowName}>Order ID</span>
              <input
                className={s.input}
                value={rnOrderId}
                onChange={(e) => setRnOrderId(e.target.value)}
              />
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Amount refunded (AED)</span>
              <input
                className={s.input}
                inputMode="decimal"
                value={rnAmount}
                onChange={(e) => setRnAmount(e.target.value)}
              />
              <span className={s.fieldHint}>
                What the customer actually got back. The VAT portion is worked out from it.
              </span>
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Reason</span>
              <input
                className={s.input}
                value={rnReason}
                onChange={(e) => setRnReason(e.target.value)}
              />
            </label>
          </div>
        </ConfirmDialog>
      )}

      {SHOW_RETENTION_TAB && tab === "retention" && (
      <section className={s.card}>
        <h3 className={s.cardTitle}>Data retention</h3>
        <p className={s.rowHint}>
          Purges operational noise older than retention days. Fiscal confirmed orders are counted, not
          deleted.
        </p>
        <div className={s.actions}>
          <Button size="md" onClick={() => void onRetention(true)} disabled={busy}>
            Dry-run purge
          </Button>
          <Button size="md" onClick={() => void onRetention(false)} disabled={busy}>
            Run purge
          </Button>
        </div>
        {runs.length > 0 ? (
          <ul className={s.list}>
            {runs.slice(0, 5).map((r) => (
              <li key={r.id}>
                #{r.id} {r.status}, {JSON.stringify(r.purged_counts)}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No retention runs" description="Dry-run first to preview purge counts." />
        )}
      </section>
      )}

      {tab === "export" && (
      <section className={s.card}>
        <h3 className={s.cardTitle}>Accountant export</h3>
        <p className={s.rowHint}>
          Every order in the period with its net, VAT and gross, plus the refund and
          credit notes issued against them. This is what your accountant files the VAT
          return from.
        </p>
        {/* Presets first. Nobody reconciles an arbitrary window: it is always a
            month, and picking one from two date fields is four clicks. */}
        <div className={s.presets}>
          {[
            ["This month", monthStartISO(), todayISO()],
            ["Last month", lastMonthStartISO(), lastMonthEndISO()],
          ].map(([label, from, to]) => (
            <button
              key={label}
              type="button"
              className={`${s.preset} ${
                exportStart === from && exportEnd === to ? s.presetActive : ""
              }`}
              onClick={() => {
                setExportStart(from);
                setExportEnd(to);
                setExportSummary(null);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>Start</span>
            <input
              className={s.input}
              type="date"
              value={exportStart}
              max={exportEnd}
              onChange={(e) => {
                setExportStart(e.target.value);
                setExportSummary(null);
              }}
            />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>End</span>
            <input
              className={s.input}
              type="date"
              value={exportEnd}
              min={exportStart}
              onChange={(e) => {
                setExportEnd(e.target.value);
                setExportSummary(null);
              }}
            />
          </label>
        </div>
        <div className={s.actions}>
          {/* "Export JSON" downloaded nothing: it fetched the pack and updated a
              line of text. Named for what it does. Only the CSV is a file, so
              only the CSV is the primary button. */}
          <Button size="md" variant="ghost" onClick={() => void onExport("json")} disabled={busy}>
            Show totals
          </Button>
          <Button size="md" onClick={() => void onExport("csv")} disabled={busy}>
            Download CSV
          </Button>
        </div>
        {exportSummary && (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <tbody>
                {[
                  ["Orders", String(exportSummary.order_count)],
                  ["Net", `AED ${exportSummary.net_total_aed}`],
                  ["VAT", `AED ${exportSummary.vat_total_aed}`],
                  ["Gross", `AED ${exportSummary.gross_total_aed}`],
                  ["Refund notes", String(exportSummary.refund_note_count)],
                  ["Credit notes", String(exportSummary.credit_note_count)],
                ].map(([label, value]) => (
                  <tr key={label}>
                    <td className={s.grow}>{label}</td>
                    <td className={s.num}>{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      )}
    </div>
  );
}
