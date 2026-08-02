import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/Button";
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
import s from "./ComplianceScreen.module.css";

type ComplianceTab = "tax" | "einvoice" | "refunds" | "retention" | "export";

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function monthStartISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
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

export function ComplianceScreen() {
  const [tax, setTax] = useState<TaxSettings | null>(null);
  const [readiness, setReadiness] = useState<{
    ready: boolean;
    e_invoice_enabled: boolean;
    asp_provider: string;
    missing_fields: string[];
    notes: string;
    structured_profile: string;
  } | null>(null);
  const [refunds, setRefunds] = useState<
    Array<{ id: number; refund_note_number: string; order_id: number; amount_aed: string }>
  >([]);
  const [txns, setTxns] = useState<
    Array<{ id: number; order_id: number; status: string; external_id: string | null }>
  >([]);
  const [runs, setRuns] = useState<
    Array<{ id: number; status: string; purged_counts: Record<string, number> }>
  >([]);
  const [exportSummary, setExportSummary] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Refund note failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onTransmit() {
    const oid = Number(eiOrderId);
    if (!oid) {
      toast("Order id required", "error");
      return;
    }
    setBusy(true);
    try {
      const row = await transmitEInvoice({
        order_id: oid,
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
    setBusy(true);
    try {
      const pack = await accountantExport(exportStart, exportEnd, format);
      const sum = pack.summary;
      setExportSummary(
        `${sum.order_count} orders, net AED ${sum.net_total_aed}, VAT AED ${sum.vat_total_aed}, gross AED ${sum.gross_total_aed}`,
      );
      if (format === "csv" && pack.csv) {
        const blob = new Blob([pack.csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `accountant-${exportStart}-${exportEnd}.csv`;
        a.click();
        URL.revokeObjectURL(url);
      }
      toast("Accountant export ready", "success");
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

      <div className={s.healthGrid}>
        <div className={`${s.healthCard} ${readiness?.ready ? s.healthOk : s.healthWarn}`}>
          <span>E-invoice ready</span>
          <strong>{readiness ? (readiness.ready ? "Yes" : "No") : "unknown"}</strong>
        </div>
        <div className={s.healthCard}>
          <span>E-invoicing</span>
          <strong>{eInv ? "On" : "Off"}</strong>
        </div>
        <div className={s.healthCard}>
          <span>Refund notes</span>
          <strong>{refunds.length}</strong>
        </div>
        <div className={s.healthCard}>
          <span>Retention runs</span>
          <strong>{runs.length}</strong>
        </div>
      </div>

      <div className={s.tabs} role="tablist" aria-label="Compliance sections">
        {(
          [
            ["tax", "Tax profile"],
            ["einvoice", "E-invoice"],
            ["refunds", "Refund notes"],
            ["retention", "Retention"],
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

      {tab === "tax" && (
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
          <label className={s.checkRow}>
            <input type="checkbox" checked={eInv} onChange={(e) => setEInv(e.target.checked)} />
            <span className={s.rowName}>E-invoicing enabled</span>
          </label>
        </div>
        {tax && (
          <p className={s.rowHint}>
            Simplified invoice threshold AED {tax.simplified_invoice_threshold_aed},
            e-invoicing provider {tax.asp_provider}
          </p>
        )}
        <div className={s.stickySave}>
          <Button size="md" onClick={() => void saveTax()} disabled={busy}>
            Save tax settings
          </Button>
        </div>
      </section>
      )}

      {tab === "einvoice" && (
      <section className={s.card}>
        <h3 className={s.cardTitle}>E-invoicing readiness (PINT-AE / ASP)</h3>
        {readiness ? (
          <ul className={s.list}>
            <li>Ready: {readiness.ready ? "yes" : "no"}</li>
            <li>Profile: {readiness.structured_profile}</li>
            <li>ASP: {readiness.asp_provider}</li>
            <li>Enabled: {readiness.e_invoice_enabled ? "yes" : "no"}</li>
            {readiness.missing_fields.length > 0 && (
              <li>Missing: {readiness.missing_fields.join(", ")}</li>
            )}
            <li className={s.rowHint}>{readiness.notes}</li>
          </ul>
        ) : (
          <p className={s.rowHint}>Loading…</p>
        )}
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>Order ID</span>
            <input className={s.input} value={eiOrderId} onChange={(e) => setEiOrderId(e.target.value)} />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Buyer TRN (B2B → full tax invoice)</span>
            <input className={s.input} value={buyerTrn} onChange={(e) => setBuyerTrn(e.target.value)} />
          </label>
        </div>
        <div className={s.actions}>
          <Button size="md" onClick={() => void onTransmit()} disabled={busy}>
            Transmit via Mock ASP
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
        <h3 className={s.cardTitle}>Refund notes (RN-…)</h3>
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>Order ID</span>
            <input className={s.input} value={rnOrderId} onChange={(e) => setRnOrderId(e.target.value)} />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Amount AED</span>
            <input className={s.input} value={rnAmount} onChange={(e) => setRnAmount(e.target.value)} />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>Reason</span>
            <input className={s.input} value={rnReason} onChange={(e) => setRnReason(e.target.value)} />
          </label>
        </div>
        <div className={s.actions}>
          <Button size="md" onClick={() => void onRefundNote()} disabled={busy}>
            Issue refund note
          </Button>
        </div>
        {refunds.length > 0 ? (
          <ul className={s.list}>
            {refunds.map((n) => (
              <li key={n.id}>
                {n.refund_note_number}, order {n.order_id}, AED {n.amount_aed}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No refund notes" description="Issued credit notes appear here." />
        )}
      </section>
      )}

      {tab === "retention" && (
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
        <div className={s.row2}>
          <label className={s.col}>
            <span className={s.rowName}>Start</span>
            <input
              className={s.input}
              type="date"
              value={exportStart}
              onChange={(e) => setExportStart(e.target.value)}
            />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>End</span>
            <input
              className={s.input}
              type="date"
              value={exportEnd}
              onChange={(e) => setExportEnd(e.target.value)}
            />
          </label>
        </div>
        <div className={s.actions}>
          <Button size="md" onClick={() => void onExport("json")} disabled={busy}>
            Export JSON
          </Button>
          <Button size="md" onClick={() => void onExport("csv")} disabled={busy}>
            Download CSV
          </Button>
        </div>
        {exportSummary && <p className={s.rowHint}>{exportSummary}</p>}
      </section>
      )}
    </div>
  );
}
