import { useEffect, useRef, useState } from "react";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
import {
  broadcast,
  createTemplate,
  deleteTemplate,
  draftTemplate,
  fetchAudience,
  fetchTemplates,
  refreshTemplate,
  submitTemplate,
  uploadTemplateImage,
  type AudienceSegment,
  type TemplateResponse,
} from "../lib/marketingApi";
import s from "./MarketingScreen.module.css";

/** Shape of settings.todays_special (mirrors the backend DEFAULT_SETTINGS block). */
type TodaysSpecial = {
  enabled: boolean;
  template_id: number | null;
  lead_minutes: number;
  default_time: string;
  // Custom send-time range ("from"–"to", HH:MM). Null = "Until today" (no range).
  window_start: string | null;
  window_end: string | null;
};

/** Auto-generate a Meta-safe template name from the offer text (the backend
 *  also datestamps + de-duplicates it, so collisions are handled). */
function autoName(describe: string): string {
  const words = describe.toLowerCase().match(/[a-z0-9]+/g)?.slice(0, 4) ?? [];
  return ("promo_" + words.join("_")).slice(0, 60) || "promo_offer";
}

/** Humanise a raw Meta template name (e.g. "promo_20_off_biryani_20260625")
 *  into a short, title-cased label ("20 Off Biryani") for the pills. The raw
 *  name still shows on hover (title attr) and in the delete confirm. */
function prettyTemplateName(raw: string): string {
  let s = raw
    .replace(/^promo[_-]/i, "") // drop the auto "promo_" prefix
    .replace(/[_-]\d{6,8}(?:[_-]\d{1,3})?$/, "") // drop datestamp (+ dedup counter), keep "20_off"
    .replace(/[_-]+/g, " ")
    .trim();
  if (!s) s = raw.replace(/[_-]+/g, " ").trim();
  s = s.replace(/\b\w/g, (c) => c.toUpperCase()); // Title Case
  return s.length > 26 ? s.slice(0, 25).trimEnd() + "…" : s;
}

// Always appended to every template (Meta requires an opt-out path). Hidden from
// the manager — they never edit it, but it ships with every template + broadcast.
const OPT_OUT_FOOTER = "Reply STOP to opt out";

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  pending_meta: "Pending",
  approved: "Approved",
  rejected: "Rejected",
};

export function MarketingScreen() {
  const [templates, setTemplates] = useState<TemplateResponse[]>([]);
  const [loaded, setLoaded] = useState(false);

  // Create-template form
  const [describe, setDescribe] = useState("");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [withButton, setWithButton] = useState(false);
  const [buttonLabel, setButtonLabel] = useState("");
  const [buttonUrl, setButtonUrl] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Selected template — drives the left live-preview panel, the contextual
  // actions and the bottom Send bar (broadcast-composer style layout).
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Top tab: WhatsApp broadcast vs the one-day promotion (Today's Special) view.
  const [tab, setTab] = useState<"whatsapp" | "promotion">("whatsapp");

  // Audience — named RFM buckets with live counts; "all" targets everyone.
  const [audience, setAudience] = useState<AudienceSegment[]>([]);
  const [audienceLoaded, setAudienceLoaded] = useState(false);
  const [segment, setSegment] = useState<string>("all");

  // Broadcast — armed via the bottom Send bar (two-tap confirm)
  const [armedId, setArmedId] = useState<number | null>(null);
  const [sendingId, setSendingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  // Template pending a delete confirmation (styled dialog, not window.confirm).
  const [confirmDelete, setConfirmDelete] = useState<TemplateResponse | null>(null);

  // Today's Special automation (settings.todays_special)
  const [special, setSpecial] = useState<TodaysSpecial>({
    enabled: false,
    template_id: null,
    lead_minutes: 15,
    default_time: "11:45",
    window_start: null,
    window_end: null,
  });
  const [savingSpecial, setSavingSpecial] = useState(false);
  // Today's Special pill UI: reveal the custom time / custom lead-minutes inputs.
  const [customTime, setCustomTime] = useState(false);
  const [leadCustom, setLeadCustom] = useState(false);

  async function reload() {
    const rows = await fetchTemplates().catch(() => []);
    setTemplates(rows);
    setLoaded(true);
    // Pre-select a template (prefer an approved one) so the preview + Send are
    // ready on load. Keep the manager's current pick if it still exists.
    setSelectedId((cur) => {
      if (cur != null && rows.some((t) => t.id === cur)) return cur;
      const pick =
        rows.find((t) => t.status === "approved") ?? rows.find((t) => t.status !== "draft");
      return pick ? pick.id : null;
    });
    const aud = await fetchAudience().catch(() => []);
    setAudience(aud);
    setAudienceLoaded(true);
    const me = await apiClient.get<RestaurantOut>("/api/v1/me").catch(() => null);
    const cfg = (me?.settings as Record<string, unknown> | undefined)?.todays_special as
      | Partial<TodaysSpecial>
      | undefined;
    if (cfg) {
      const lead = cfg.lead_minutes ?? 15;
      setSpecial({
        enabled: !!cfg.enabled,
        template_id: cfg.template_id ?? null,
        lead_minutes: lead,
        default_time: cfg.default_time ?? "11:45",
        window_start: cfg.window_start ?? null,
        window_end: cfg.window_end ?? null,
      });
      setLeadCustom(![15, 30, 45].includes(lead));
      setCustomTime(!!(cfg.window_start && cfg.window_end));
    }
  }
  useEffect(() => {
    reload();
  }, []);

  const approvedTemplates = templates.filter((t) => t.status === "approved");
  // The list shows only meaningful states — drafts (unsubmitted) are noise.
  const visibleTemplates = templates.filter((t) => t.status !== "draft");
  // Resolve from the live list so a status change (refresh) reflects instantly.
  const selectedTpl = templates.find((t) => t.id === selectedId) ?? null;
  // The template chosen for the Today's Special automation (drives its preview).
  const specialTpl = templates.find((t) => t.id === special.template_id) ?? null;
  // Block Save when the chosen special template isn't approved yet.
  const specialSaveBlocked =
    special.enabled && specialTpl != null && specialTpl.status !== "approved";

  async function onDeleteTemplate(t: TemplateResponse) {
    setDeletingId(t.id);
    try {
      await deleteTemplate(t.id);
      setTemplates((prev) => prev.filter((x) => x.id !== t.id));
      // Drop the deleted template from selection + the auto-special slot.
      setSelectedId((cur) => (cur === t.id ? null : cur));
      setSpecial((p) => (p.template_id === t.id ? { ...p, template_id: null } : p));
      setConfirmDelete(null);
      toast("Template deleted.");
    } catch {
      toast("Could not delete the template.", "error");
    } finally {
      setDeletingId(null);
    }
  }

  async function onSaveSpecial() {
    if (special.enabled && special.template_id === null) {
      toast("Select an approved template before turning this on.");
      return;
    }
    if (special.enabled && customTime) {
      if (
        !special.window_start ||
        !special.window_end ||
        special.window_start >= special.window_end
      ) {
        toast("Set a valid time range — the From time must be before the To time.");
        return;
      }
    }
    setSavingSpecial(true);
    try {
      await apiClient.patch("/api/v1/settings", { todays_special: special });
      toast(special.enabled ? "Today's Special is ON ✅" : "Today's Special turned off");
    } catch {
      toast("Could not save. Please try again.");
    } finally {
      setSavingSpecial(false);
    }
  }

  async function onDraft() {
    if (describe.trim().length < 3) return;
    setDrafting(true);
    try {
      const d = await draftTemplate({ describe: describe.trim() });
      if (!name) setName(d.suggested_name);
      setBody(d.body);
      toast("Draft ready. Review and edit, then submit.", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't draft the message.", "error");
    } finally {
      setDrafting(false);
    }
  }

  async function onPickImage(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    try {
      const { url } = await uploadTemplateImage(file);
      setImageUrl(url);
      toast("Header image uploaded.", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Image upload failed.", "error");
    } finally {
      setUploading(false);
    }
  }

  async function onSubmit() {
    if (body.trim().length < 10) {
      toast("Write a longer message body first.", "error");
      return;
    }
    if (withButton && (!buttonLabel.trim() || !/^https:\/\//i.test(buttonUrl.trim()))) {
      toast("Button needs a label and an https:// link.", "error");
      return;
    }
    // Template name is automatic (backend also datestamps + de-dupes it).
    const tplName = name.trim() || autoName(describe || body);
    setSubmitting(true);
    try {
      const created = await createTemplate({
        meta_template_name: tplName,
        body: body.trim(),
        footer: OPT_OUT_FOOTER,
        header: imageUrl ? { type: "IMAGE", image_url: imageUrl } : null,
        buttons: withButton
          ? [{ type: "URL", label: buttonLabel.trim(), url: buttonUrl.trim() }]
          : null,
      });
      const submitted = await submitTemplate(created.id);
      if (submitted.status === "approved") {
        toast("Template approved. Ready to broadcast! 🎉", "success");
      } else if (submitted.status === "rejected") {
        toast(`Rejected: ${submitted.rejection_reason ?? "see Meta"}`, "error");
      } else {
        toast("Submitted to Meta. Awaiting approval (refresh to check).", "success");
      }
      // Reset the form for the next template.
      setDescribe("");
      setName("");
      setBody("");
      setImageUrl(null);
      setWithButton(false);
      setButtonLabel("");
      setButtonUrl("");
      setShowCreate(false);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Submit failed.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function onRefresh(id: number) {
    try {
      const t = await refreshTemplate(id);
      setTemplates((rows) => rows.map((r) => (r.id === id ? t : r)));
      if (t.status === "approved") toast("Approved! ✅", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Refresh failed.", "error");
    }
  }

  async function onBroadcast(id: number) {
    if (armedId !== id) {
      setArmedId(id); // first tap arms; second within 6s confirms
      window.setTimeout(() => setArmedId((cur) => (cur === id ? null : cur)), 6000);
      return;
    }
    setArmedId(null);
    setSendingId(id);
    try {
      const res = await broadcast({ template_id: id, rfm_segment: segment, type: "promotional" });
      const extras = [
        res.suppressed_optout ? `${res.suppressed_optout} opted-out` : "",
        res.suppressed_cap ? `${res.suppressed_cap} over 24h cap` : "",
        res.suppressed_window ? `${res.suppressed_window} outside the send window` : "",
      ].filter(Boolean);
      toast(
        `Sent to ${res.queued} customer${res.queued === 1 ? "" : "s"}.` +
          (extras.length ? ` Skipped: ${extras.join(", ")}.` : ""),
        "success",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "Broadcast failed.", "error");
    } finally {
      setSendingId(null);
    }
  }

  const segLabel = audience.find((a) => a.key === segment)?.label ?? "All Customers";
  const sendDisabled =
    !selectedTpl || selectedTpl.status !== "approved" || sendingId === selectedId;
  const sendLabel = !selectedTpl
    ? "Select a template to send"
    : selectedTpl.status !== "approved"
      ? "Template must be approved to send"
      : sendingId === selectedId
        ? "Sending…"
        : armedId === selectedId
          ? "Tap again to confirm"
          : `📣 Send via WhatsApp · ${segLabel}`;

  return (
    <div className={s.root}>
      {/* Big composer-style header */}
      <div className={s.topbar}>
        <div>
          <h1 className={s.pageTitle}>Marketing</h1>
          <p className={s.pageSub}>
            WhatsApp promotions. Create a template, get it approved, broadcast.
          </p>
        </div>
      </div>

      {/* Mode tabs (broadcast "Channels"-style bar) + the New-template action */}
      <div className={s.tabBar}>
        <div className={s.tabGroup}>
          <button
            type="button"
            className={`${s.tab} ${tab === "whatsapp" ? s.tabActive : ""}`}
            onClick={() => setTab("whatsapp")}
          >
            WhatsApp
          </button>
          <button
            type="button"
            className={`${s.tab} ${tab === "promotion" ? s.tabActive : ""}`}
            onClick={() => setTab("promotion")}
          >
            Today's Special
          </button>
        </div>
      </div>

      {/* WHATSAPP TAB — LIVE PREVIEW (left) + options (right) */}
      {tab === "whatsapp" && (
      <div className={s.mainGrid}>
        {/* LEFT — persistent live preview of the selected template */}
        <div className={s.previewPanel}>
          <div className={s.previewPanelLabel}>Live preview</div>
          {selectedTpl ? (
            <div className={s.previewPanelBody}>
              <TemplatePreview
                imageUrl={selectedTpl.header?.image_url ?? null}
                body={selectedTpl.body ?? ""}
                withButton={(selectedTpl.buttons?.length ?? 0) > 0}
                buttonLabel={selectedTpl.buttons?.[0]?.label ?? ""}
              />
            </div>
          ) : (
            <div className={s.previewEmpty}>Select a template to preview</div>
          )}
        </div>

        {/* RIGHT — segment, template pills, and the Send bar */}
        <div className={s.rightCol}>
          {/* SEGMENT PICKER — named RFM buckets with live counts */}
          <div className={s.card}>
            <div className={s.cardTitle}>Select Audience</div>
            <p className={s.note}>
              Choose who receives this broadcast. Customer counts update live.
            </p>
            {!audienceLoaded ? (
              <div className={s.pillRow} aria-busy="true" aria-label="Loading segments">
                {Array.from({ length: 6 }).map((_, i) => (
                  <span key={i} className={`${s.sk} ${s.skPill}`} />
                ))}
              </div>
            ) : (
              <div className={s.pillRow}>
                {audience.map((a) => (
                  <button
                    key={a.key}
                    type="button"
                    className={`${s.pill} ${segment === a.key ? s.pillActive : ""}`}
                    onClick={() => setSegment(a.key)}
                  >
                    {a.label}
                    <span className={s.pillTag}>{a.count}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* TEMPLATE PICKER — pills */}
          <div className={s.card}>
            <div className={s.cardHead}>
              <div className={s.cardTitle}>Select Template</div>
              {selectedTpl && (
                <div className={s.tplHeadRight}>
                  {selectedTpl.status === "pending_meta" && (
                    <button
                      type="button"
                      className={s.refresh}
                      onClick={() => onRefresh(selectedTpl.id)}
                    >
                      ↻ Refresh
                    </button>
                  )}
                  <span
                    className={`${s.badge} ${s["badge_" + selectedTpl.status] ?? ""}`}
                    title={
                      selectedTpl.status === "pending_meta" ? "Awaiting Meta approval" : undefined
                    }
                  >
                    {STATUS_LABEL[selectedTpl.status] ?? selectedTpl.status}
                  </span>
                </div>
              )}
            </div>
            <p className={s.note}>
              Pick an <strong>approved</strong> template, preview it on the left, then{" "}
              <strong>Send</strong> to all opted in customers. We skip anyone who opted out and
              anyone already messaged twice in the last 24h.
            </p>

            {!loaded ? (
              <div className={s.pillRow} aria-busy="true" aria-label="Loading templates">
                {Array.from({ length: 5 }).map((_, i) => (
                  <span key={i} className={`${s.sk} ${s.skPill}`} />
                ))}
              </div>
            ) : (
              <div className={s.pillRow}>
                {visibleTemplates.map((t) => (
                  <div
                    key={t.id}
                    className={`${s.pill} ${selectedId === t.id ? s.pillActive : ""}`}
                    onClick={() => setSelectedId(t.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedId(t.id);
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    title={t.meta_template_name}
                  >
                    <span className={s.pillName}>{prettyTemplateName(t.meta_template_name)}</span>
                    {selectedId === t.id && (
                      <button
                        type="button"
                        className={s.pillX}
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDelete(t);
                        }}
                        title="Delete template"
                        aria-label={`Delete ${prettyTemplateName(t.meta_template_name)}`}
                      >
                        ×
                      </button>
                    )}
                  </div>
                ))}
                <button type="button" className={s.createPill} onClick={() => setShowCreate(true)}>
                  ＋ New template
                </button>
              </div>
            )}

            {loaded && visibleTemplates.length === 0 && (
              <div className={s.empty}>No submitted templates yet.</div>
            )}

            {/* Rejection reason for the selected template (Refresh lives in the header) */}
            {selectedTpl && selectedTpl.status === "rejected" && selectedTpl.rejection_reason && (
              <div className={s.selActions}>
                <span className={s.reject}>{selectedTpl.rejection_reason}</span>
              </div>
            )}
          </div>

          {/* SEND BAR — full-width primary action, broadcast-composer style */}
          <button
            type="button"
            className={`${s.sendBar} ${armedId === selectedId ? s.sendBarArmed : ""}`}
            disabled={sendDisabled}
            onClick={() => selectedId != null && onBroadcast(selectedId)}
          >
            {sendLabel}
          </button>
        </div>
      </div>
      )}

      {/* ONE DAY PROMOTION TAB — composer layout: preview (left) + setup (right) */}
      {tab === "promotion" && (
        <div className={s.mainGrid}>
          {/* LEFT — preview of the chosen special template */}
          <div className={s.previewPanel}>
            <div className={s.previewPanelLabel}>Live preview</div>
            {specialTpl ? (
              <div className={s.previewPanelBody}>
                <TemplatePreview
                  imageUrl={specialTpl.header?.image_url ?? null}
                  body={specialTpl.body ?? ""}
                  withButton={(specialTpl.buttons?.length ?? 0) > 0}
                  buttonLabel={specialTpl.buttons?.[0]?.label ?? ""}
                />
              </div>
            ) : (
              <div className={s.previewEmpty}>Select a template to preview</div>
            )}
          </div>

          {/* RIGHT — template selection + settings + save */}
          <div className={s.rightCol}>
            {/* When to send */}
            <div className={s.card}>
              <div className={s.cardTitle}>When to send</div>
              <p className={s.note}>
                <strong>None</strong> (off), <strong>Until today</strong> (auto-timed to each
                customer during the day), or a <strong>Custom time</strong> range (only send
                between a start and end time, e.g. 6:00pm to 10:00pm).
              </p>
              <div className={s.pillRow}>
                <button
                  type="button"
                  className={`${s.pill} ${!special.enabled ? s.pillActive : ""}`}
                  onClick={() => setSpecial((p) => ({ ...p, enabled: false }))}
                >
                  None
                </button>
                <button
                  type="button"
                  className={`${s.pill} ${special.enabled && !customTime ? s.pillActive : ""}`}
                  onClick={() => {
                    setCustomTime(false);
                    setSpecial((p) => ({ ...p, enabled: true, window_start: null, window_end: null }));
                  }}
                >
                  Until today
                </button>
                <button
                  type="button"
                  className={`${s.pill} ${special.enabled && customTime ? s.pillActive : ""}`}
                  onClick={() => {
                    setCustomTime(true);
                    setSpecial((p) => ({
                      ...p,
                      enabled: true,
                      window_start: p.window_start ?? "18:00",
                      window_end: p.window_end ?? "22:00",
                    }));
                  }}
                >
                  Custom time
                </button>
              </div>
              {special.enabled && customTime && (
                <div className={s.fieldGrid}>
                  <div>
                    <label className={s.label}>From</label>
                    <input
                      className={s.input}
                      type="time"
                      value={special.window_start ?? "18:00"}
                      onChange={(e) => setSpecial((p) => ({ ...p, window_start: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className={s.label}>To</label>
                    <input
                      className={s.input}
                      type="time"
                      value={special.window_end ?? "22:00"}
                      onChange={(e) => setSpecial((p) => ({ ...p, window_end: e.target.value }))}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* How early */}
            <div className={s.card}>
              <div className={s.cardTitle}>Send how early</div>
              <p className={s.note}>
                How long before each customer's usual order time the message goes out.
              </p>
              <div className={s.pillRow}>
                {[15, 30, 45].map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={`${s.pill} ${
                      !leadCustom && special.lead_minutes === n ? s.pillActive : ""
                    }`}
                    onClick={() => {
                      setLeadCustom(false);
                      setSpecial((p) => ({ ...p, lead_minutes: n }));
                    }}
                  >
                    {n} min
                  </button>
                ))}
                <button
                  type="button"
                  className={`${s.pill} ${leadCustom ? s.pillActive : ""}`}
                  onClick={() => setLeadCustom(true)}
                >
                  Custom
                </button>
              </div>
              {leadCustom && (
                <input
                  className={s.input}
                  type="number"
                  min={0}
                  max={120}
                  value={special.lead_minutes}
                  onChange={(e) =>
                    setSpecial((p) => ({ ...p, lead_minutes: Number(e.target.value) }))
                  }
                />
              )}
            </div>

            {/* Template */}
            <div className={s.card}>
              <div className={s.cardHead}>
                <div className={s.cardTitle}>Select Template</div>
                {specialTpl && (
                  <div className={s.tplHeadRight}>
                    {specialTpl.status === "pending_meta" && (
                      <button
                        type="button"
                        className={s.refresh}
                        onClick={() => onRefresh(specialTpl.id)}
                      >
                        ↻ Refresh
                      </button>
                    )}
                    <span
                      className={`${s.badge} ${s["badge_" + specialTpl.status] ?? ""}`}
                      title={
                        specialTpl.status === "pending_meta" ? "Awaiting Meta approval" : undefined
                      }
                    >
                      {STATUS_LABEL[specialTpl.status] ?? specialTpl.status}
                    </span>
                  </div>
                )}
              </div>
              <p className={s.note}>
                The approved template that gets sent. Pending ones show here until approved.
              </p>
              <div className={s.pillRow}>
                {visibleTemplates.map((t) => (
                  <div
                    key={t.id}
                    className={`${s.pill} ${special.template_id === t.id ? s.pillActive : ""}`}
                    onClick={() => setSpecial((p) => ({ ...p, template_id: t.id }))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSpecial((p) => ({ ...p, template_id: t.id }));
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    title={t.meta_template_name}
                  >
                    <span className={s.pillName}>{prettyTemplateName(t.meta_template_name)}</span>
                    {special.template_id === t.id && (
                      <button
                        type="button"
                        className={s.pillX}
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDelete(t);
                        }}
                        title="Delete template"
                        aria-label={`Delete ${prettyTemplateName(t.meta_template_name)}`}
                      >
                        ×
                      </button>
                    )}
                  </div>
                ))}
                <button type="button" className={s.createPill} onClick={() => setShowCreate(true)}>
                  ＋ New template
                </button>
              </div>
              {approvedTemplates.length === 0 && (
                <span className={s.hint}>
                  No approved templates yet. Select one once Meta approves it (use Refresh to check).
                </span>
              )}
            </div>

            {/* Full-width save bar (mirrors the WhatsApp tab's Send bar) */}
            <button
              type="button"
              className={s.sendBar}
              disabled={savingSpecial || specialSaveBlocked}
              onClick={onSaveSpecial}
            >
              {savingSpecial
                ? "Saving…"
                : specialSaveBlocked
                  ? "Template must be approved to save"
                  : `💾 Save automation · ${special.enabled ? "On" : "Off"}`}
            </button>
          </div>
        </div>
      )}

      {/* DELETE CONFIRM — styled dialog (replaces window.confirm) */}
      {confirmDelete && (
        <ConfirmDialog
          title="Delete template"
          message={`Delete "${prettyTemplateName(confirmDelete.meta_template_name)}"? This can't be undone.`}
          confirmLabel="Delete"
          danger
          busy={deletingId === confirmDelete.id}
          onConfirm={() => onDeleteTemplate(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}

      {/* CREATE TEMPLATE — preview (left) + form (right), shown in a dialog */}
      {showCreate && (
        <div className={s.overlay} onClick={() => setShowCreate(false)}>
          <div className={s.modal} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHead}>
              <div className={s.cardTitle}>Create WhatsApp template</div>
              <button
                className={s.modalClose}
                onClick={() => setShowCreate(false)}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <p className={s.note}>
              Describe your offer and we'll draft a Meta compliant message. WhatsApp
              must approve every promotional template before it can be sent.
            </p>

            <div className={s.createBody}>
              {/* LEFT — live preview */}
              <div className={s.previewCol}>
                <div className={s.previewLabel}>Preview</div>
                <TemplatePreview
                  imageUrl={imageUrl}
                  body={body}
                  withButton={withButton}
                  buttonLabel={buttonLabel}
                />
              </div>

              {/* RIGHT — form */}
              <div className={s.formCol}>
                <label className={s.label}>Describe your offer</label>
                <textarea
                  className={s.textarea}
                  rows={2}
                  value={describe}
                  onChange={(e) => setDescribe(e.target.value)}
                  placeholder="e.g. 20% off all biryani this weekend, free delivery over AED 50"
                />
                <div className={s.draftActions}>
                  <Button variant="ghost" onClick={onDraft} disabled={drafting || describe.trim().length < 3}>
                    {drafting ? "Generating…" : "✨ Generate message"}
                  </Button>
                </div>

                <label className={s.label}>Header image (optional)</label>
                <div className={s.imageActions}>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/jpeg,image/png"
                    hidden
                    onChange={(e) => onPickImage(e.target.files?.[0])}
                  />
                  <Button variant="ghost" onClick={() => fileRef.current?.click()} disabled={uploading}>
                    {uploading ? "Uploading…" : imageUrl ? "Replace image" : "Upload image"}
                  </Button>
                  <span className={s.soonWrap}>
                    <Button variant="ghost" disabled title="Coming soon">
                      🖼️ Generate image
                    </Button>
                    <span className={s.soonBadge}>Soon</span>
                  </span>
                  <span className={s.soonWrap}>
                    <Button variant="ghost" disabled title="Coming soon">
                      🎬 Generate video
                    </Button>
                    <span className={s.soonBadge}>Soon</span>
                  </span>
                </div>

                <label className={s.label}>Message body</label>
                <textarea
                  className={s.textarea}
                  rows={5}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="Hi {{1}}, enjoy 20% off all biryani this weekend. Reply to order!"
                />
                <span className={s.hint}>
                  Use <code>{"{{1}}"}</code> once for the customer's name. {body.length}/1024
                </span>

                <label className={s.checkRow}>
                  <input
                    type="checkbox"
                    checked={withButton}
                    onChange={(e) => setWithButton(e.target.checked)}
                  />
                  Add a button (optional)
                </label>
                {withButton && (
                  <div className={s.row}>
                    <input
                      className={s.input}
                      value={buttonLabel}
                      maxLength={25}
                      onChange={(e) => setButtonLabel(e.target.value)}
                      placeholder="Order now"
                    />
                    <input
                      className={s.input}
                      value={buttonUrl}
                      onChange={(e) => setButtonUrl(e.target.value)}
                      placeholder="https://…"
                    />
                  </div>
                )}

                <div className={s.actions}>
                  <Button onClick={onSubmit} disabled={submitting}>
                    {submitting ? "Submitting…" : "Submit for approval"}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Live WhatsApp-style preview of the template as the manager fills it in. The
 *  {{1}} placeholder is shown filled with a sample name so it reads naturally. */
function TemplatePreview({
  imageUrl,
  body,
  withButton,
  buttonLabel,
}: {
  imageUrl: string | null;
  body: string;
  withButton: boolean;
  buttonLabel: string;
}) {
  const rendered = (body || "Your message will appear here…").replace(/\{\{1\}\}/g, "Ahmed");
  return (
    <div className={s.previewWrap}>
      <div className={s.bubble}>
        {imageUrl && <img src={imageUrl} alt="header" className={s.bubbleImg} />}
        <div className={s.bubbleBody}>{rendered}</div>
        <div className={s.bubbleFooter}>{OPT_OUT_FOOTER}</div>
        <div className={s.bubbleTime}>12:45</div>
      </div>
      {withButton && buttonLabel.trim() && (
        <div className={s.bubbleBtn}>🔗 {buttonLabel.trim()}</div>
      )}
    </div>
  );
}
