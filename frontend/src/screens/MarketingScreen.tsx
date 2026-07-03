import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApprovalTimeline } from "../components/ApprovalTimeline";
import { Button } from "../components/Button";
import {
  CampaignSummarySkeleton,
  CampaignSummaryStrip,
} from "../components/CampaignSummaryStrip";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { SideDrawer } from "../components/SideDrawer";
import { toast } from "../components/Toaster";
import { computeCampaignSummary, statNum } from "../lib/campaignSummary";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
import {
  broadcast,
  cancelCampaign,
  compileSegment,
  createSegment,
  createTemplate,
  deleteSegment,
  deleteTemplate,
  draftTemplate,
  fixTemplate,
  fetchAudience,
  fetchAutomations,
  fetchCampaigns,
  fetchSegments,
  fetchTemplates,
  generateTemplateImage,
  patchAutomation,
  getCampaignStats,
  refreshTemplate,
  rescheduleCampaign,
  submitTemplate,
  uploadTemplateImage,
  type AudienceSegment,
  type AutomationResponse,
  type CampaignResponse,
  type CampaignStatsResponse,
  type SegmentCompileResponse,
  type SegmentResponse,
  type TemplateResponse,
} from "../lib/marketingApi";
import { usePoll } from "../lib/usePoll";
import s from "./MarketingScreen.module.css";

/** Shape of settings.todays_special (mirrors the backend DEFAULT_SETTINGS block). */
type TodaysSpecial = {
  enabled: boolean;
  template_id: number | null;
  fallback_template_id: number | null;
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

const CAMPAIGN_TYPE_LABEL: Record<string, string> = {
  promotional: "Broadcast",
  todays_special: "Today's Special",
  reactivation: "Reactivation",
  announcement: "Announcement",
};

const CAMPAIGN_STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  scheduled: "Scheduled",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
  cancelled: "Cancelled",
};

function formatCampaignDate(c: CampaignResponse): string {
  const raw = c.status === "scheduled" && c.scheduled_at ? c.scheduled_at : c.created_at;
  if (!raw) return "—";
  return new Date(raw).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Dubai is always UTC+4 (no DST). */
function dubaiLocalToUtcIso(date: string, time: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  return new Date(Date.UTC(y, m - 1, d, hh - 4, mm, 0, 0)).toISOString();
}

function formatScheduledLocal(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    timeZone: "Asia/Dubai",
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function defaultScheduleDate(): string {
  const dubai = new Date(Date.now() + 60 * 60 * 1000);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Dubai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(dubai);
  const y = parts.find((p) => p.type === "year")?.value ?? "2026";
  const m = parts.find((p) => p.type === "month")?.value ?? "01";
  const d = parts.find((p) => p.type === "day")?.value ?? "01";
  return `${y}-${m}-${d}`;
}

function defaultScheduleTime(): string {
  const dubai = new Date(Date.now() + 60 * 60 * 1000);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Dubai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(dubai);
  const hh = parts.find((p) => p.type === "hour")?.value ?? "12";
  const mm = parts.find((p) => p.type === "minute")?.value ?? "00";
  return `${hh}:${mm}`;
}

type AudienceSelection =
  | { mode: "rfm"; key: string }
  | { mode: "segment"; segmentId: number };

const SEGMENT_EXAMPLES = [
  "customers who spent over AED 200",
  "customers who ordered in the last 30 days",
  "VIP customers",
  "customers who ordered 3 or more times",
  "customers who spent over AED 100 and ordered in the last 14 days",
];

function audienceSendLabel(
  sel: AudienceSelection,
  rfm: AudienceSegment[],
  saved: SegmentResponse[],
): string {
  if (sel.mode === "segment") {
    const seg = saved.find((x) => x.id === sel.segmentId);
    const count = seg?.last_preview_count ?? 0;
    return `${seg?.name ?? "Segment"} (${count})`;
  }
  return rfm.find((a) => a.key === sel.key)?.label ?? "All Customers";
}

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
  const [generatingImage, setGeneratingImage] = useState(false);
  const [showImagePrompt, setShowImagePrompt] = useState(false);
  const [imagePrompt, setImagePrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createEphemeral, setCreateEphemeral] = useState(false);
  const [fixingId, setFixingId] = useState<number | null>(null);
  const [resubmittingId, setResubmittingId] = useState<number | null>(null);
  const [approvedFlashId, setApprovedFlashId] = useState<number | null>(null);
  const prevTplStatusRef = useRef<Map<number, string>>(new Map());
  const fileRef = useRef<HTMLInputElement>(null);

  // Selected template — drives the left live-preview panel, the contextual
  // actions and the bottom Send bar (broadcast-composer style layout).
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Top tab: WhatsApp broadcast vs the one-day promotion (Today's Special) view.
  const [tab, setTab] = useState<
    "whatsapp" | "promotion" | "segments" | "campaigns" | "automation"
  >("whatsapp");

  // Audience — RFM buckets OR saved custom segment (mutually exclusive).
  const [audience, setAudience] = useState<AudienceSegment[]>([]);
  const [audienceLoaded, setAudienceLoaded] = useState(false);
  const [savedSegments, setSavedSegments] = useState<SegmentResponse[]>([]);
  const [segmentsLoaded, setSegmentsLoaded] = useState(false);
  const [audienceSelection, setAudienceSelection] = useState<AudienceSelection>({
    mode: "rfm",
    key: "all",
  });
  const [couponValue, setCouponValue] = useState("");
  const [sendMode, setSendMode] = useState<"now" | "schedule">("now");
  const [scheduleDate, setScheduleDate] = useState(defaultScheduleDate);
  const [scheduleTime, setScheduleTime] = useState(defaultScheduleTime);

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
    fallback_template_id: null,
    lead_minutes: 15,
    default_time: "11:45",
    window_start: null,
    window_end: null,
  });
  const [savingSpecial, setSavingSpecial] = useState(false);
  // Today's Special pill UI: reveal the custom time / custom lead-minutes inputs.
  const [customTime, setCustomTime] = useState(false);
  const [leadCustom, setLeadCustom] = useState(false);

  const applyTemplateRows = useCallback((rows: TemplateResponse[]) => {
    const prev = prevTplStatusRef.current;
    for (const t of rows) {
      const was = prev.get(t.id);
      if (was === "pending_meta" && t.status === "approved") {
        setApprovedFlashId(t.id);
        toast("Template approved — ready to send ✅", "success");
        window.setTimeout(
          () => setApprovedFlashId((cur) => (cur === t.id ? null : cur)),
          400,
        );
      }
      prev.set(t.id, t.status);
    }
    setTemplates(rows);
    setLoaded(true);
  }, []);

  async function reload() {
    const rows = await fetchTemplates().catch(() => []);
    applyTemplateRows(rows);
    // Pre-select a template (prefer an approved one) so the preview + Send are
    // ready on load. Keep the manager's current pick if it still exists.
    setSelectedId((cur) => {
      if (cur != null && rows.some((t) => t.id === cur)) return cur;
      const pick =
        rows.find((t) => t.status === "approved") ?? rows.find((t) => t.status !== "draft");
      return pick ? pick.id : null;
    });
    const [aud, segs] = await Promise.all([
      fetchAudience().catch(() => [] as AudienceSegment[]),
      fetchSegments().catch(() => [] as SegmentResponse[]),
    ]);
    setAudience(aud);
    setAudienceLoaded(true);
    setSavedSegments(segs);
    setSegmentsLoaded(true);
    const me = await apiClient.get<RestaurantOut>("/api/v1/me").catch(() => null);
    const cfg = (me?.settings as Record<string, unknown> | undefined)?.todays_special as
      | Partial<TodaysSpecial>
      | undefined;
    if (cfg) {
      const lead = cfg.lead_minutes ?? 15;
      const tid = cfg.template_id ?? null;
      const fid = cfg.fallback_template_id ?? null;
      if (tid != null && !rows.some((t) => t.id === tid)) {
        toast("Today's template was removed (end of day). Pick a new one.");
      }
      setSpecial({
        enabled: !!cfg.enabled,
        template_id: tid != null && rows.some((t) => t.id === tid) ? tid : null,
        fallback_template_id:
          fid != null && rows.some((t) => t.id === fid) ? fid : null,
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only bootstrap
  }, []);

  const hasPending = templates.some((t) => t.status === "pending_meta");
  const pollTemplates = useCallback(async () => {
    const rows = await fetchTemplates();
    applyTemplateRows(rows);
    return rows;
  }, [applyTemplateRows]);
  usePoll(pollTemplates, hasPending ? 30_000 : null);

  const approvedTemplates = templates.filter((t) => t.status === "approved");
  // Hide draft noise unless the manager is actively working on that template.
  const visibleTemplates = templates.filter(
    (t) =>
      t.status !== "draft" ||
      t.id === selectedId ||
      t.id === special.template_id ||
      t.id === special.fallback_template_id,
  );
  // Resolve from the live list so a status change (refresh) reflects instantly.
  const selectedTpl = templates.find((t) => t.id === selectedId) ?? null;
  // The template chosen for the Today's Special automation (drives its preview).
  const specialTpl = templates.find((t) => t.id === special.template_id) ?? null;
  const fallbackTpl =
    templates.find((t) => t.id === special.fallback_template_id) ?? null;
  const hasApprovedPrimary = specialTpl?.status === "approved";
  const hasApprovedFallback = fallbackTpl?.status === "approved";
  const specialSaveBlocked =
    special.enabled &&
    special.template_id != null &&
    !hasApprovedPrimary &&
    !(special.fallback_template_id != null && hasApprovedFallback);
  const showSpecialRejectionBanner =
    special.template_id != null &&
    specialTpl?.status === "rejected" &&
    !(special.fallback_template_id != null && hasApprovedFallback);

  function openCreateModal(ephemeral: boolean) {
    setCreateEphemeral(ephemeral);
    setShowCreate(true);
  }

  async function onFixTemplate(id: number) {
    setFixingId(id);
    try {
      const fixed = await fixTemplate(id);
      setTemplates((rows) => rows.map((r) => (r.id === id ? fixed : r)));
      setSelectedId(id);
      toast("Template revised. Submit again for approval.", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not fix the template.", "error");
    } finally {
      setFixingId(null);
    }
  }

  async function onResubmitTemplate(id: number) {
    setResubmittingId(id);
    try {
      const submitted = await submitTemplate(id);
      setTemplates((rows) => rows.map((r) => (r.id === id ? submitted : r)));
      if (submitted.status === "approved") {
        toast("Template approved. Ready to send! 🎉", "success");
      } else if (submitted.status === "rejected") {
        toast(`Rejected: ${submitted.rejection_reason ?? "see Meta"}`, "error");
      } else {
        toast("Submitted to Meta. Awaiting approval.", "success");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Submit failed.", "error");
    } finally {
      setResubmittingId(null);
    }
  }

  function onEditTemplateManually(t: TemplateResponse) {
    setDescribe("");
    setName(t.meta_template_name);
    setBody(t.body ?? "");
    setImageUrl(
      t.header?.type === "IMAGE" ? (t.header.image_url ?? null) : null,
    );
    const btn = t.buttons?.[0];
    setWithButton(!!btn);
    setButtonLabel(btn?.label ?? "");
    setButtonUrl(btn?.url ?? "");
    setCreateEphemeral(false);
    setShowCreate(true);
  }

  async function onDeleteTemplate(t: TemplateResponse) {
    setDeletingId(t.id);
    try {
      await deleteTemplate(t.id);
      setTemplates((prev) => prev.filter((x) => x.id !== t.id));
      // Drop the deleted template from selection + the auto-special slot.
      setSelectedId((cur) => (cur === t.id ? null : cur));
      setSpecial((p) => ({
        ...p,
        template_id: p.template_id === t.id ? null : p.template_id,
        fallback_template_id:
          p.fallback_template_id === t.id ? null : p.fallback_template_id,
      }));
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

  async function onGenerateImage() {
    const prompt = imagePrompt.trim() || describe.trim();
    if (prompt.length < 3) {
      toast("Describe your offer first, or edit the image prompt.", "error");
      return;
    }
    setGeneratingImage(true);
    try {
      const { url } = await generateTemplateImage({
        prompt: imagePrompt.trim(),
        describe: describe.trim() || null,
      });
      setImageUrl(url);
      toast("Header image generated.", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Image generation failed.", "error");
    } finally {
      setGeneratingImage(false);
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
        ephemeral: createEphemeral,
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
      setCreateEphemeral(false);
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
      const payload: Parameters<typeof broadcast>[0] = {
        template_id: id,
        type: "promotional",
      };
      if (audienceSelection.mode === "segment") {
        payload.segment_id = audienceSelection.segmentId;
      } else if (audienceSelection.key !== "all") {
        payload.rfm_segment = audienceSelection.key;
      }
      const coupon = couponValue.trim();
      if (coupon) {
        const n = Number(coupon);
        if (!Number.isFinite(n) || n <= 0) {
          toast("Enter a positive coupon amount in AED.", "error");
          return;
        }
        payload.coupon_value = n.toFixed(2);
      }
      if (sendMode === "schedule") {
        payload.scheduled_at = dubaiLocalToUtcIso(scheduleDate, scheduleTime);
      }
      const res = await broadcast(payload);
      if ("status" in res && res.status === "scheduled") {
        toast(
          `Scheduled for ${formatScheduledLocal(res.scheduled_at)} — cancel from Campaigns.` +
            (res.window_warning ? ` ${res.window_warning}` : ""),
          "success",
        );
      } else if ("queued" in res) {
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
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Broadcast failed.", "error");
    } finally {
      setSendingId(null);
    }
  }

  const segLabel = audienceSendLabel(audienceSelection, audience, savedSegments);
  const sendDisabled =
    !selectedTpl || selectedTpl.status !== "approved" || sendingId === selectedId;
  const sendLabel = !selectedTpl
    ? sendMode === "schedule"
      ? "Select a template to schedule"
      : "Select a template to send"
    : selectedTpl.status !== "approved"
      ? "Template must be approved to send"
      : sendingId === selectedId
        ? sendMode === "schedule"
          ? "Scheduling…"
          : "Sending…"
        : armedId === selectedId
          ? "Tap again to confirm"
          : sendMode === "schedule"
            ? `📅 Schedule broadcast · ${segLabel} · ${scheduleDate} ${scheduleTime} Dubai`
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
          <button
            type="button"
            className={`${s.tab} ${tab === "segments" ? s.tabActive : ""}`}
            onClick={() => setTab("segments")}
          >
            Segments
          </button>
          <button
            type="button"
            className={`${s.tab} ${tab === "campaigns" ? s.tabActive : ""}`}
            onClick={() => setTab("campaigns")}
          >
            Campaigns
          </button>
          <button
            type="button"
            className={`${s.tab} ${tab === "automation" ? s.tabActive : ""}`}
            onClick={() => setTab("automation")}
          >
            Automation
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
                status={selectedTpl.status}
                approvedFlash={approvedFlashId === selectedTpl.id}
              />
              <ApprovalTimeline
                status={selectedTpl.status}
                rejectionReason={selectedTpl.rejection_reason}
                onFixWithAI={() => onFixTemplate(selectedTpl.id)}
                onEditManually={() => onEditTemplateManually(selectedTpl)}
                onSubmit={() => onResubmitTemplate(selectedTpl.id)}
                fixing={fixingId === selectedTpl.id}
                submitting={resubmittingId === selectedTpl.id}
              />
            </div>
          ) : (
            <div className={s.previewEmpty}>Select a template to preview</div>
          )}
        </div>

        {/* RIGHT — segment, template pills, and the Send bar */}
        <div className={s.rightCol}>
          {/* AUDIENCE — RFM buckets OR saved custom segments (mutually exclusive) */}
          <div className={s.card}>
            <div className={s.cardTitle}>Select Audience</div>
            <p className={s.note}>
              Choose one group. RFM buckets and saved segments cannot be combined.
            </p>
            <div className={s.audienceGroupLabel}>RFM (behaviour buckets)</div>
            {!audienceLoaded ? (
              <div className={s.pillRow} aria-busy="true" aria-label="Loading audience">
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
                    className={`${s.pill} ${
                      audienceSelection.mode === "rfm" && audienceSelection.key === a.key
                        ? s.pillActive
                        : ""
                    }`}
                    onClick={() => setAudienceSelection({ mode: "rfm", key: a.key })}
                  >
                    {a.label}
                    <span className={s.pillTag}>{a.count}</span>
                  </button>
                ))}
              </div>
            )}
            {segmentsLoaded && savedSegments.length > 0 && (
              <>
                <div className={s.audienceGroupLabel}>Saved segments</div>
                <div className={s.pillRow}>
                  {savedSegments.map((seg) => (
                    <button
                      key={seg.id}
                      type="button"
                      className={`${s.pill} ${
                        audienceSelection.mode === "segment" &&
                        audienceSelection.segmentId === seg.id
                          ? s.pillActive
                          : ""
                      }`}
                      onClick={() =>
                        setAudienceSelection({ mode: "segment", segmentId: seg.id })
                      }
                    >
                      {seg.name}
                      <span className={s.pillTag}>{seg.last_preview_count ?? 0}</span>
                    </button>
                  ))}
                </div>
              </>
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
                <button
                  type="button"
                  className={s.createPill}
                  onClick={() => openCreateModal(false)}
                >
                  ＋ New template
                </button>
              </div>
            )}

            {loaded && visibleTemplates.length === 0 && (
              <div className={s.empty}>No submitted templates yet.</div>
            )}

          </div>

          {/* Optional coupon (broadcast only) */}
          <div className={s.couponRow}>
            <label className={s.couponLabel} htmlFor="broadcast-coupon">
              Optional coupon (AED)
            </label>
            <input
              id="broadcast-coupon"
              className={s.couponInput}
              type="number"
              min={0}
              max={500}
              step={0.01}
              placeholder="e.g. 10.00"
              value={couponValue}
              onChange={(e) => setCouponValue(e.target.value)}
            />
            <span className={s.couponHint}>
              Unique code per customer; needs a prior order
            </span>
          </div>

          <div className={s.sendModeRow}>
            <button
              type="button"
              className={`${s.sendModePill} ${sendMode === "now" ? s.sendModePillActive : ""}`}
              onClick={() => setSendMode("now")}
            >
              Send now
            </button>
            <button
              type="button"
              className={`${s.sendModePill} ${sendMode === "schedule" ? s.sendModePillActive : ""}`}
              onClick={() => setSendMode("schedule")}
            >
              Schedule
            </button>
          </div>

          {sendMode === "schedule" && (
            <div className={s.scheduleRow}>
              <label className={s.scheduleField}>
                <span>Date (Dubai)</span>
                <input
                  type="date"
                  value={scheduleDate}
                  onChange={(e) => setScheduleDate(e.target.value)}
                />
              </label>
              <label className={s.scheduleField}>
                <span>Time (Dubai)</span>
                <input
                  type="time"
                  value={scheduleTime}
                  onChange={(e) => setScheduleTime(e.target.value)}
                />
              </label>
              <p className={s.scheduleHint}>
                Sends only during 9am–6pm UAE if window enforcement is on.
              </p>
            </div>
          )}

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
                  status={specialTpl.status}
                  approvedFlash={approvedFlashId === specialTpl.id}
                />
                <ApprovalTimeline
                  status={specialTpl.status}
                  rejectionReason={specialTpl.rejection_reason}
                  onFixWithAI={() => onFixTemplate(specialTpl.id)}
                  onEditManually={() => onEditTemplateManually(specialTpl)}
                  onSubmit={() => onResubmitTemplate(specialTpl.id)}
                  fixing={fixingId === specialTpl.id}
                  submitting={resubmittingId === specialTpl.id}
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
                <button
                  type="button"
                  className={s.createPill}
                  onClick={() => openCreateModal(true)}
                >
                  ＋ New template
                </button>
              </div>
              {approvedTemplates.length === 0 && (
                <span className={s.hint}>
                  No approved templates yet. Select one once Meta approves it (use Refresh to check).
                </span>
              )}
              {showSpecialRejectionBanner && (
                <div className={s.specialRejectBanner}>
                  Today's template was rejected. Add a fallback or fix and resubmit before
                  enabling.
                </div>
              )}
            </div>

            <div className={s.card}>
              <div className={s.cardTitle}>Fallback template (optional)</div>
              <p className={s.note}>
                If today's template isn't approved in time, we'll send this one instead.
              </p>
              <div className={s.pillRow}>
                <button
                  type="button"
                  className={`${s.pill} ${
                    special.fallback_template_id === null ? s.pillActive : ""
                  }`}
                  onClick={() =>
                    setSpecial((p) => ({ ...p, fallback_template_id: null }))
                  }
                >
                  None
                </button>
                {approvedTemplates.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`${s.pill} ${
                      special.fallback_template_id === t.id ? s.pillActive : ""
                    }`}
                    onClick={() =>
                      setSpecial((p) => ({ ...p, fallback_template_id: t.id }))
                    }
                    title={t.meta_template_name}
                  >
                    {prettyTemplateName(t.meta_template_name)}
                  </button>
                ))}
              </div>
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

      {/* SEGMENTS TAB — plain-English audience builder */}
      {tab === "segments" && (
        <SegmentsTab
          onSaved={(segs) => {
            setSavedSegments(segs);
            setSegmentsLoaded(true);
          }}
        />
      )}

      {/* CAMPAIGNS TAB — history + ROI detail */}
      {tab === "campaigns" && <CampaignsTab templates={templates} />}

      {/* AUTOMATION TAB — preset behaviour triggers */}
      {tab === "automation" && (
        <AutomationsTab
          templates={templates}
          segments={savedSegments}
          approvedTemplates={approvedTemplates}
        />
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
            {createEphemeral && (
              <p className={s.ephemeralHint}>
                This template is for today only — removed automatically tonight.
              </p>
            )}

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
                  <Button
                    variant="ghost"
                    onClick={() => {
                      if (!showImagePrompt) {
                        setImagePrompt(describe.trim());
                        setShowImagePrompt(true);
                      } else {
                        void onGenerateImage();
                      }
                    }}
                    disabled={generatingImage || uploading}
                  >
                    {generatingImage
                      ? "Generating…"
                      : imageUrl
                        ? "Regenerate image"
                        : "🖼️ Generate image"}
                  </Button>
                  <span className={s.soonWrap}>
                    <Button
                      variant="ghost"
                      disabled
                      title="Video promos coming later — use image or text header for now."
                    >
                      🎬 Generate video
                    </Button>
                    <span className={s.soonBadge}>Later</span>
                  </span>
                </div>
                {showImagePrompt && (
                  <div className={s.imagePromptBox}>
                    <label className={s.label}>Image prompt (optional edit)</label>
                    <textarea
                      className={s.textarea}
                      rows={2}
                      value={imagePrompt}
                      onChange={(e) => setImagePrompt(e.target.value)}
                      placeholder="Appetizing biryani platter, warm lighting…"
                    />
                  </div>
                )}

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

/** Four preset automations — welcome, recurring, win-back, reorder. */
function AutomationsTab({
  templates,
  segments,
  approvedTemplates,
}: {
  templates: TemplateResponse[];
  segments: SegmentResponse[];
  approvedTemplates: TemplateResponse[];
}) {
  const [rows, setRows] = useState<AutomationResponse[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  async function reload() {
    const data = await fetchAutomations().catch(() => []);
    setRows(data);
    setLoaded(true);
  }

  useEffect(() => {
    reload();
  }, []);

  async function save(
    presetKey: string,
    patch: Parameters<typeof patchAutomation>[1],
  ) {
    setSavingKey(presetKey);
    try {
      const updated = await patchAutomation(presetKey, patch);
      setRows((prev) =>
        prev.map((r) => (r.preset_key === presetKey ? updated : r)),
      );
      toast("Automation saved.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save automation.", "error");
      await reload();
    } finally {
      setSavingKey(null);
    }
  }

  const tplOptions =
    approvedTemplates.length > 0
      ? approvedTemplates
      : templates.filter((t) => t.status === "approved");

  return (
    <div className={s.automationRoot}>
      <p className={s.note}>
        Hands-off messages triggered by customer behaviour. Each card saves automatically
        when you toggle or pick a template.
      </p>
      {!loaded ? (
        <div className={s.automationLoading}>Loading automations…</div>
      ) : (
        rows.map((auto) => (
          <div key={auto.preset_key} className={s.automationCard}>
            <div className={s.automationHead}>
              <div>
                <div className={s.automationTitle}>{auto.title}</div>
                <p className={s.automationDesc}>{auto.description}</p>
              </div>
              <label className={s.automationToggle}>
                <input
                  type="checkbox"
                  checked={auto.enabled}
                  disabled={savingKey === auto.preset_key}
                  onChange={(e) => {
                    const enabled = e.target.checked;
                    if (enabled && !auto.template_id) {
                      toast("Select an approved template first.", "error");
                      return;
                    }
                    void save(auto.preset_key, { enabled });
                  }}
                />
                <span>{auto.enabled ? "On" : "Off"}</span>
              </label>
            </div>

            {auto.save_blocked && auto.save_blocked_reason && (
              <div className={s.specialRejectBanner}>{auto.save_blocked_reason}</div>
            )}

            <div className={s.automationField}>
              <span className={s.label}>Template</span>
              <div className={s.pillRow}>
                {tplOptions.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`${s.pill} ${
                      auto.template_id === t.id ? s.pillActive : ""
                    }`}
                    onClick={() => void save(auto.preset_key, { template_id: t.id })}
                    title={t.meta_template_name}
                  >
                    {prettyTemplateName(t.meta_template_name)}
                  </button>
                ))}
                {tplOptions.length === 0 && (
                  <span className={s.hint}>No approved templates yet.</span>
                )}
              </div>
            </div>

            <div className={s.automationField}>
              <span className={s.label}>Audience</span>
              <div className={s.pillRow}>
                <button
                  type="button"
                  className={`${s.pill} ${auto.segment_id == null ? s.pillActive : ""}`}
                  onClick={() => void save(auto.preset_key, { segment_id: null })}
                >
                  All customers
                </button>
                {segments.map((seg) => (
                  <button
                    key={seg.id}
                    type="button"
                    className={`${s.pill} ${
                      auto.segment_id === seg.id ? s.pillActive : ""
                    }`}
                    onClick={() => void save(auto.preset_key, { segment_id: seg.id })}
                  >
                    {seg.name}
                  </button>
                ))}
              </div>
            </div>

            {(auto.preset_key === "recurring" || auto.preset_key === "reorder") && (
              <div className={s.automationField}>
                <span className={s.label}>Lead time</span>
                <div className={s.pillRow}>
                  {[15, 30, 45].map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={`${s.pill} ${
                        auto.config.lead_minutes === n ? s.pillActive : ""
                      }`}
                      onClick={() =>
                        void save(auto.preset_key, {
                          config: { ...auto.config, lead_minutes: n },
                        })
                      }
                    >
                      {n} min
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className={s.automationStats}>
              <span>
                Sent: <strong>{Number(auto.stats.sent ?? auto.stats.last_queued ?? 0)}</strong>
              </span>
              <span>
                Converted: <strong>{Number(auto.stats.converted ?? 0)}</strong>
              </span>
              {auto.last_run_at && (
                <span>
                  Last run: {new Date(auto.last_run_at).toLocaleString()}
                </span>
              )}
            </div>
          </div>
        ))
      )}

      <details className={s.automationAdvanced}>
        <summary>Advanced: custom automations (coming soon)</summary>
        <p className={s.note}>
          Build custom trigger / condition / action rules in plain English — Phase 4b.
        </p>
      </details>
    </div>
  );
}

/** Build and save custom audience segments from plain English. */
function SegmentsTab({
  onSaved,
}: {
  onSaved: (segments: SegmentResponse[]) => void;
}) {
  const [plainEnglish, setPlainEnglish] = useState("");
  const [segmentName, setSegmentName] = useState("");
  const [compiling, setCompiling] = useState(false);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [compiled, setCompiled] = useState<SegmentCompileResponse | null>(null);
  const [showDsl, setShowDsl] = useState(false);
  const [saving, setSaving] = useState(false);
  const [segments, setSegments] = useState<SegmentResponse[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<SegmentResponse | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  async function reloadSegments() {
    const rows = await fetchSegments().catch(() => []);
    setSegments(rows);
    setLoaded(true);
    onSaved(rows);
  }

  useEffect(() => {
    reloadSegments();
  }, []);

  async function onCompile() {
    if (plainEnglish.trim().length < 10) return;
    setCompiling(true);
    setCompileError(null);
    try {
      const result = await compileSegment(plainEnglish.trim());
      setCompiled(result);
      if (!segmentName.trim()) {
        setSegmentName(result.plain_english.slice(0, 64));
      }
    } catch (e) {
      setCompiled(null);
      setCompileError(e instanceof Error ? e.message : "Compile failed.");
    } finally {
      setCompiling(false);
    }
  }

  async function onSave() {
    if (!compiled || segmentName.trim().length < 3) return;
    setSaving(true);
    try {
      await createSegment({
        name: segmentName.trim(),
        dsl: compiled.dsl,
        plain_english: compiled.plain_english,
      });
      toast("Segment saved.");
      setPlainEnglish("");
      setSegmentName("");
      setCompiled(null);
      setShowDsl(false);
      await reloadSegments();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save segment.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function onDeleteSegment(seg: SegmentResponse) {
    setDeletingId(seg.id);
    try {
      await deleteSegment(seg.id);
      setConfirmDelete(null);
      toast("Segment deleted.");
      await reloadSegments();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete segment.", "error");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className={s.segmentsCard}>
      <div className={s.segmentsBuilder}>
        <div className={s.cardTitle}>Build a segment</div>
        <div className={s.exampleChips}>
          <span className={s.exampleChipsLabel}>Try an example:</span>
          {SEGMENT_EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              className={s.exampleChip}
              onClick={() => setPlainEnglish(ex)}
            >
              {ex.replace("customers who ", "").replace(/^./, (c) => c.toUpperCase())}
            </button>
          ))}
        </div>
        <label className={s.label} htmlFor="segment-plain">
          Plain English
        </label>
        <textarea
          id="segment-plain"
          className={s.textarea}
          rows={3}
          value={plainEnglish}
          onChange={(e) => setPlainEnglish(e.target.value)}
          placeholder="customers who spent over AED 200 in the last 60 days"
          disabled={compiling}
        />
        <Button
          onClick={onCompile}
          disabled={compiling || plainEnglish.trim().length < 10}
        >
          {compiling ? "Compiling…" : "✨ Compile segment"}
        </Button>
        {compileError && <p className={s.compileError}>{compileError}</p>}
        {compiled && (
          <div className={s.compileResult}>
            <span className={s.compileCount}>
              ✓ {compiled.preview_count} customer
              {compiled.preview_count === 1 ? "" : "s"} match
            </span>
            <button
              type="button"
              className={s.dslToggle}
              onClick={() => setShowDsl((v) => !v)}
            >
              {showDsl ? "▾ Hide compiled rules" : "▸ View compiled rules"}
            </button>
            {showDsl && (
              <pre className={s.dslPre}>{JSON.stringify(compiled.dsl, null, 2)}</pre>
            )}
          </div>
        )}
        <label className={s.label} htmlFor="segment-name">
          Segment name
        </label>
        <input
          id="segment-name"
          className={s.input}
          value={segmentName}
          onChange={(e) => setSegmentName(e.target.value)}
          placeholder="High spenders · last 60 days"
        />
        <Button
          onClick={onSave}
          disabled={saving || !compiled || segmentName.trim().length < 3}
        >
          {saving ? "Saving…" : "💾 Save segment"}
        </Button>
      </div>

      <div className={s.segmentsSaved}>
        <div className={s.cardTitle}>Saved segments</div>
        {!loaded ? (
          <p className={s.note}>Loading…</p>
        ) : segments.length === 0 ? (
          <p className={s.segmentsEmpty}>No saved segments yet — build one above.</p>
        ) : (
          <div className={s.segmentsTableWrap}>
            <table className={s.segmentsTable}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Customers</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {segments.map((seg) => (
                  <tr key={seg.id}>
                    <td>{seg.name}</td>
                    <td>{seg.last_preview_count ?? 0}</td>
                    <td>
                      {seg.updated_at
                        ? new Date(seg.updated_at).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={s.segDeleteBtn}
                        onClick={() => setConfirmDelete(seg)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title="Delete segment"
          message={`Delete segment «${confirmDelete.name}»? Past campaigns that used it keep their history.`}
          confirmLabel="Delete"
          danger
          busy={deletingId === confirmDelete.id}
          onConfirm={() => onDeleteSegment(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  );
}

/** Past sends — summary strip, table, and per-campaign stats drawer. */
function CampaignsTab({ templates }: { templates: TemplateResponse[] }) {
  const { data: campaigns, error } = usePoll(fetchCampaigns, 60_000);
  const [rows, setRows] = useState<CampaignResponse[] | null>(null);
  const [selected, setSelected] = useState<CampaignResponse | null>(null);
  const [detailStats, setDetailStats] = useState<CampaignStatsResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [rescheduleId, setRescheduleId] = useState<number | null>(null);
  const [rescheduleDate, setRescheduleDate] = useState(defaultScheduleDate);
  const [rescheduleTime, setRescheduleTime] = useState(defaultScheduleTime);

  useEffect(() => {
    if (campaigns) setRows(campaigns);
  }, [campaigns]);

  useEffect(() => {
    if (!selected) {
      setDetailStats(null);
      return;
    }
    setDetailLoading(true);
    getCampaignStats(selected.id)
      .then(setDetailStats)
      .catch(() => setDetailStats(null))
      .finally(() => setDetailLoading(false));
  }, [selected]);

  const summary = useMemo(
    () => (rows && rows.length > 0 ? computeCampaignSummary(rows) : null),
    [rows],
  );

  async function onCancelCampaign(c: CampaignResponse, e: React.MouseEvent) {
    e.stopPropagation();
    if (!window.confirm(`Cancel scheduled broadcast #${c.id}?`)) return;
    setCancellingId(c.id);
    try {
      await cancelCampaign(c.id);
      setRows((prev) =>
        prev?.map((row) => (row.id === c.id ? { ...row, status: "cancelled" } : row)) ?? null,
      );
      if (selected?.id === c.id) setSelected((cur) => (cur ? { ...cur, status: "cancelled" } : cur));
      toast("Scheduled broadcast cancelled.");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not cancel.", "error");
    } finally {
      setCancellingId(null);
    }
  }

  async function onRescheduleCampaign(c: CampaignResponse) {
    setRescheduleId(c.id);
    try {
      const res = await rescheduleCampaign(
        c.id,
        dubaiLocalToUtcIso(rescheduleDate, rescheduleTime),
      );
      const patch = { status: "scheduled", scheduled_at: res.scheduled_at };
      setRows((prev) => prev?.map((row) => (row.id === c.id ? { ...row, ...patch } : row)) ?? null);
      if (selected?.id === c.id) setSelected((cur) => (cur ? { ...cur, ...patch } : cur));
      toast(`Rescheduled for ${formatScheduledLocal(res.scheduled_at)}.`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not reschedule.", "error");
    } finally {
      setRescheduleId(null);
    }
  }

  const selectedTpl =
    selected?.template_id != null
      ? templates.find((t) => t.id === selected.template_id) ?? null
      : null;

  const drawerSent = detailStats ? statNum(detailStats, "sent") : 0;
  const drawerConverted = detailStats ? statNum(detailStats, "converted") : 0;
  const convRate =
    drawerSent > 0 ? Math.round((drawerConverted / drawerSent) * 100) : 0;

  return (
    <div className={s.campaignsCard}>
      {error != null && (
        <p className={s.campaignsWarn}>Could not refresh campaigns — retrying…</p>
      )}

      {rows === null ? (
        <CampaignSummarySkeleton />
      ) : summary ? (
        <CampaignSummaryStrip summary={summary} />
      ) : null}

      {rows !== null && rows.length === 0 ? (
        <div className={s.campaignsEmpty}>
          <div className={s.campaignsEmptyIcon}>📣</div>
          <div className={s.campaignsEmptyTitle}>No campaigns yet</div>
          <p className={s.campaignsEmptyDesc}>
            Send your first promotion from the WhatsApp tab — it will show up here with
            delivery and conversion stats.
          </p>
        </div>
      ) : rows !== null && rows.length > 0 ? (
        <div className={s.campaignTableWrap}>
          <table className={s.campaignTable}>
            <thead>
              <tr>
                <th>Date</th>
                <th>Template</th>
                <th>Audience</th>
                <th>Type</th>
                <th>Status</th>
                <th>Sent</th>
                <th>Delivered</th>
                <th>Converted</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr
                  key={c.id}
                  className={`${s.campaignRow} ${c.status === "cancelled" ? s.campaignRowCancelled : ""}`}
                  onClick={() => setSelected(c)}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setSelected(c);
                  }}
                >
                  <td>{formatCampaignDate(c)}</td>
                  <td title={c.template_name ?? undefined}>
                    {c.template_name ? prettyTemplateName(c.template_name) : "—"}
                  </td>
                  <td>{c.audience_label ?? "All Customers"}</td>
                  <td>{CAMPAIGN_TYPE_LABEL[c.type] ?? c.type}</td>
                  <td>
                    <span
                      className={`${s.campaignStatus} ${
                        c.status === "scheduled" ? s.campaignStatusScheduled : ""
                      }`}
                    >
                      {CAMPAIGN_STATUS_LABEL[c.status] ?? c.status}
                      {c.status === "scheduled" && c.scheduled_at
                        ? ` · ${formatScheduledLocal(c.scheduled_at)}`
                        : ""}
                    </span>
                  </td>
                  <td>{statNum(c.stats, "sent")}</td>
                  <td>{statNum(c.stats, "delivered")}</td>
                  <td>{statNum(c.stats, "converted")}</td>
                  <td className={s.campaignActions}>
                    {c.status === "scheduled" && (
                      <button
                        type="button"
                        className={s.campaignActionBtn}
                        disabled={cancellingId === c.id}
                        onClick={(e) => void onCancelCampaign(c, e)}
                      >
                        {cancellingId === c.id ? "…" : "Cancel"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <SideDrawer
        open={selected != null}
        title={selected ? `Campaign #${selected.id}` : "Campaign"}
        onClose={() => setSelected(null)}
        wide
      >
        {selected && (
          <div className={s.campaignDrawer}>
            <div className={s.campaignDrawerMeta}>
              <span>{CAMPAIGN_TYPE_LABEL[selected.type] ?? selected.type}</span>
              <span>{selected.audience_label ?? "All Customers"}</span>
              <span>{formatCampaignDate(selected)}</span>
              {selected.status === "scheduled" && selected.scheduled_at && (
                <span>Fire {formatScheduledLocal(selected.scheduled_at)}</span>
              )}
            </div>

            {selected.status === "scheduled" && (
              <div className={s.scheduleRow}>
                <label className={s.scheduleField}>
                  <span>Reschedule date (Dubai)</span>
                  <input
                    type="date"
                    value={rescheduleDate}
                    onChange={(e) => setRescheduleDate(e.target.value)}
                  />
                </label>
                <label className={s.scheduleField}>
                  <span>Time</span>
                  <input
                    type="time"
                    value={rescheduleTime}
                    onChange={(e) => setRescheduleTime(e.target.value)}
                  />
                </label>
                <Button
                  variant="ghost"
                  disabled={rescheduleId === selected.id}
                  onClick={() => void onRescheduleCampaign(selected)}
                >
                  {rescheduleId === selected.id ? "Saving…" : "Reschedule"}
                </Button>
              </div>
            )}

            {typeof selected.stats?.window_warning === "string" && (
              <p className={s.scheduleHint}>{String(selected.stats.window_warning)}</p>
            )}

            {selectedTpl && (
              <div className={s.campaignDrawerPreview}>
                <div className={s.previewLabel}>Template preview</div>
                <TemplatePreview
                  imageUrl={
                    selectedTpl.header?.type === "IMAGE"
                      ? (selectedTpl.header.image_url ?? null)
                      : null
                  }
                  body={selectedTpl.body ?? ""}
                  withButton={!!selectedTpl.buttons?.length}
                  buttonLabel={selectedTpl.buttons?.[0]?.label ?? ""}
                />
              </div>
            )}

            {detailLoading ? (
              <p className={s.campaignDrawerLoading}>Loading stats…</p>
            ) : detailStats ? (
              <>
                <div className={s.campaignDrawerGrid}>
                  <div><strong>{statNum(detailStats, "queued")}</strong><span>Queued</span></div>
                  <div><strong>{statNum(detailStats, "sent")}</strong><span>Sent</span></div>
                  <div><strong>{statNum(detailStats, "delivered")}</strong><span>Delivered</span></div>
                  <div><strong>{statNum(detailStats, "read")}</strong><span>Read</span></div>
                  <div><strong>{drawerConverted}</strong><span>Converted</span></div>
                  <div><strong>{convRate}%</strong><span>Conversion rate</span></div>
                </div>
                <div className={s.campaignSuppress}>
                  <div className={s.campaignSuppressTitle}>Suppressed</div>
                  <div className={s.campaignSuppressRow}>
                    <span>Opt-out</span>
                    <strong>
                      {statNum(detailStats, "suppressed_optout") ||
                        statNum(selected.stats, "suppressed_optout")}
                    </strong>
                  </div>
                  <div className={s.campaignSuppressRow}>
                    <span>24h cap</span>
                    <strong>
                      {statNum(detailStats, "suppressed_cap") ||
                        statNum(selected.stats, "suppressed_cap")}
                    </strong>
                  </div>
                  <div className={s.campaignSuppressRow}>
                    <span>Send window</span>
                    <strong>
                      {statNum(detailStats, "suppressed_window") ||
                        statNum(selected.stats, "suppressed_window")}
                    </strong>
                  </div>
                </div>
              </>
            ) : (
              <p className={s.campaignDrawerLoading}>No stats available.</p>
            )}
          </div>
        )}
      </SideDrawer>
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
  status,
  approvedFlash = false,
}: {
  imageUrl: string | null;
  body: string;
  withButton: boolean;
  buttonLabel: string;
  status?: string;
  approvedFlash?: boolean;
}) {
  const rendered = (body || "Your message will appear here…").replace(/\{\{1\}\}/g, "Ahmed");
  const shimmer = status === "pending_meta";
  return (
    <div className={s.previewWrap}>
      <div
        className={`${s.bubble} ${shimmer ? s.previewShimmer : ""} ${
          approvedFlash ? s.previewApprovedFlash : ""
        }`}
      >
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
