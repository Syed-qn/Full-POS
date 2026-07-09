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
  const [eInv, setEInv] = useState(false);
  const [retentionDays, setRetentionDays] = useState(2555);

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
      setRetentionDays(t.data_retention_days ?? 2555);
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
      const updated = await patchTaxSettings({
        trn: trn.trim() || null,
        legal_name: legalName.trim() || null,
        legal_name_ar: legalNameAr.trim() || null,
        tax_pricing_mode: mode,
        e_invoice_enabled: eInv,
        data_retention_days: retentionDays,
      } as Partial<TaxSettings>);
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
      toast(`E-invoice ${row.status}${row.external_id ? ` · ${row.external_id}` : ""}`, "success");
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
      const run = await runRetention({ dry_run: dryRun, retention_days: retentionDays });
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
        `${sum.order_count} orders · net AED ${sum.net_total_aed} · VAT AED ${sum.vat_total_aed} · gross AED ${sum.gross_total_aed}`,
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
        subtitle="VAT invoices · TRN · e-invoicing ASP · refund notes · retention · accountant export"
      />

      <div className={s.healthGrid}>
        <div className={`${s.healthCard} ${readiness?.ready ? s.healthOk : s.healthWarn}`}>
          <span>E-invoice ready</span>
          <strong>{readiness ? (readiness.ready ? "Yes" : "No") : "—"}</strong>
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
        <h3 className={s.cardTitle}>Tax settings · branch TRN</h3>
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
              min={30}
              value={retentionDays}
              onChange={(e) => setRetentionDays(Number(e.target.value) || 2555)}
            />
          </label>
          <label className={s.col}>
            <span className={s.rowName}>E-invoicing enabled</span>
            <input type="checkbox" checked={eInv} onChange={(e) => setEInv(e.target.checked)} />
          </label>
        </div>
        {tax && (
          <p className={s.rowHint}>
            Default VAT {tax.default_vat_rate} · simplified threshold AED{" "}
            {tax.simplified_invoice_threshold_aed} · ASP {tax.asp_provider}
          </p>
        )}
        <div className={s.stickySave}>
          <Button onClick={() => void saveTax()} disabled={busy}>
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
          <Button onClick={() => void onTransmit()} disabled={busy}>
            Transmit via Mock ASP
          </Button>
        </div>
        {txns.length > 0 ? (
          <ul className={s.list}>
            {txns.slice(0, 10).map((t) => (
              <li key={t.id}>
                #{t.id} order {t.order_id} · {t.status}
                {t.external_id ? ` · ${t.external_id}` : ""}
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
          <Button onClick={() => void onRefundNote()} disabled={busy}>
            Issue refund note
          </Button>
        </div>
        {refunds.length > 0 ? (
          <ul className={s.list}>
            {refunds.map((n) => (
              <li key={n.id}>
                {n.refund_note_number} · order {n.order_id} · AED {n.amount_aed}
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
          <Button onClick={() => void onRetention(true)} disabled={busy}>
            Dry-run purge
          </Button>
          <Button onClick={() => void onRetention(false)} disabled={busy}>
            Run purge
          </Button>
        </div>
        {runs.length > 0 ? (
          <ul className={s.list}>
            {runs.slice(0, 5).map((r) => (
              <li key={r.id}>
                #{r.id} {r.status} · {JSON.stringify(r.purged_counts)}
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
          <Button onClick={() => void onExport("json")} disabled={busy}>
            Export JSON
          </Button>
          <Button onClick={() => void onExport("csv")} disabled={busy}>
            Download CSV
          </Button>
        </div>
        {exportSummary && <p className={s.rowHint}>{exportSummary}</p>}
      </section>
      )}
    </div>
  );
}
