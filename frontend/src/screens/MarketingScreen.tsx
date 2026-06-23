import { useEffect, useRef, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/Button";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
import {
  broadcast,
  createTemplate,
  deleteTemplate,
  draftTemplate,
  fetchTemplates,
  refreshTemplate,
  submitTemplate,
  uploadTemplateImage,
  type TemplateResponse,
} from "../lib/marketingApi";
import s from "./MarketingScreen.module.css";

/** Shape of settings.todays_special (mirrors the backend DEFAULT_SETTINGS block). */
type TodaysSpecial = {
  enabled: boolean;
  template_id: number | null;
  lead_minutes: number;
  default_time: string;
};

/** Auto-generate a Meta-safe template name from the offer text (the backend
 *  also datestamps + de-duplicates it, so collisions are handled). */
function autoName(describe: string): string {
  const words = describe.toLowerCase().match(/[a-z0-9]+/g)?.slice(0, 4) ?? [];
  return ("promo_" + words.join("_")).slice(0, 60) || "promo_offer";
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
  const [previewTpl, setPreviewTpl] = useState<TemplateResponse | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Broadcast — per-template, triggered from the list (after approval)
  const [armedId, setArmedId] = useState<number | null>(null);
  const [sendingId, setSendingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [tplPage, setTplPage] = useState(0);

  // Today's Special automation (settings.todays_special)
  const [special, setSpecial] = useState<TodaysSpecial>({
    enabled: false,
    template_id: null,
    lead_minutes: 15,
    default_time: "11:45",
  });
  const [savingSpecial, setSavingSpecial] = useState(false);

  async function reload() {
    const rows = await fetchTemplates().catch(() => []);
    setTemplates(rows);
    setLoaded(true);
    const me = await apiClient.get<RestaurantOut>("/api/v1/me").catch(() => null);
    const cfg = (me?.settings as Record<string, unknown> | undefined)?.todays_special as
      | Partial<TodaysSpecial>
      | undefined;
    if (cfg) {
      setSpecial({
        enabled: !!cfg.enabled,
        template_id: cfg.template_id ?? null,
        lead_minutes: cfg.lead_minutes ?? 15,
        default_time: cfg.default_time ?? "11:45",
      });
    }
  }
  useEffect(() => {
    reload();
  }, []);

  const approvedTemplates = templates.filter((t) => t.status === "approved");
  // The list shows only meaningful states — drafts (unsubmitted) are noise.
  const visibleTemplates = templates.filter((t) => t.status !== "draft");
  const TPL_PER_PAGE = 5;
  const tplPageCount = Math.max(1, Math.ceil(visibleTemplates.length / TPL_PER_PAGE));
  const tplPageSafe = Math.min(tplPage, tplPageCount - 1);
  const pagedTemplates = visibleTemplates.slice(
    tplPageSafe * TPL_PER_PAGE,
    tplPageSafe * TPL_PER_PAGE + TPL_PER_PAGE,
  );

  async function onDeleteTemplate(t: TemplateResponse) {
    if (!window.confirm(`Delete template "${t.meta_template_name}"? This can't be undone.`)) {
      return;
    }
    setDeletingId(t.id);
    try {
      await deleteTemplate(t.id);
      setTemplates((prev) => prev.filter((x) => x.id !== t.id));
      // If the deleted template was the auto-special one, clear that selection.
      setSpecial((p) => (p.template_id === t.id ? { ...p, template_id: null } : p));
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
      const res = await broadcast({ template_id: id, type: "promotional" });
      const extras = [
        res.suppressed_optout ? `${res.suppressed_optout} opted-out` : "",
        res.suppressed_cap ? `${res.suppressed_cap} over 24h cap` : "",
        res.suppressed_window ? `${res.suppressed_window} outside 9am to 6pm window` : "",
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

  return (
    <div className={s.root}>
      <div className={s.topbar}>
        <PageHeader
          title="Marketing"
          subtitle="WhatsApp promotions. Create a template, get it approved, broadcast."
        />
        <Button onClick={() => setShowCreate(true)}>＋ New template</Button>
      </div>

      {/* TEMPLATES (left) + TODAY'S SPECIAL (right), side by side */}
      <div className={s.columns}>

      {/* TEMPLATE LIST — Send appears here once a template is approved */}
      <div className={s.card}>
        <div className={s.cardTitle}>Your templates</div>
        <p className={s.note}>
          Once a template is <strong>approved</strong>, tap <strong>Send</strong> to
          broadcast it to all opted in customers. We skip anyone who opted out, anyone
          already messaged twice in 24h, and (per UAE rules) any send outside 9am to 6pm.
        </p>
        {!loaded ? (
          <div className={s.empty}>Loading…</div>
        ) : visibleTemplates.length === 0 ? (
          <div className={s.empty}>No submitted templates yet.</div>
        ) : (
          <div className={s.tplList}>
            {pagedTemplates.map((t) => (
              <div key={t.id} className={s.tplRow}>
                <span className={s.tplName}>{t.meta_template_name}</span>
                <span
                  className={`${s.badge} ${s["badge_" + t.status] ?? ""}`}
                  title={t.status === "pending_meta" ? "Awaiting Meta approval" : undefined}
                >
                  {STATUS_LABEL[t.status] ?? t.status}
                </span>
                {t.status === "rejected" && t.rejection_reason && (
                  <span className={s.reject}>{t.rejection_reason}</span>
                )}
                <div className={s.tplActions}>
                  {t.status === "pending_meta" && (
                    <button type="button" className={s.refresh} onClick={() => onRefresh(t.id)}>
                      ↻ Refresh
                    </button>
                  )}
                  {t.status === "approved" && (
                    <button
                      type="button"
                      className={`${s.sendBtn} ${armedId === t.id ? s.sendBtnArmed : ""}`}
                      onClick={() => onBroadcast(t.id)}
                      disabled={sendingId === t.id}
                    >
                      {sendingId === t.id
                        ? "Sending…"
                        : armedId === t.id
                          ? "Tap to confirm"
                          : "📣 Send"}
                    </button>
                  )}
                  <button
                    type="button"
                    className={s.previewBtn}
                    onClick={() => setPreviewTpl(t)}
                    title="Preview message"
                    aria-label={`Preview ${t.meta_template_name}`}
                  >
                    👁
                  </button>
                  <button
                    type="button"
                    className={s.deleteTpl}
                    onClick={() => onDeleteTemplate(t)}
                    disabled={deletingId === t.id}
                    title="Delete template"
                    aria-label={`Delete ${t.meta_template_name}`}
                  >
                    {deletingId === t.id ? "…" : "🗑"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {tplPageCount > 1 && (
          <div className={s.tplPager}>
            <button
              type="button"
              className={s.pagerBtn}
              onClick={() => setTplPage((p) => Math.max(0, p - 1))}
              disabled={tplPageSafe === 0}
            >
              ← Prev
            </button>
            <span className={s.pagerInfo}>
              Page {tplPageSafe + 1} of {tplPageCount}
            </span>
            <button
              type="button"
              className={s.pagerBtn}
              onClick={() => setTplPage((p) => Math.min(tplPageCount - 1, p + 1))}
              disabled={tplPageSafe >= tplPageCount - 1}
            >
              Next →
            </button>
          </div>
        )}
      </div>

      {/* TODAY'S SPECIAL — auto-timed daily send, per-customer */}
      <div className={s.card}>
        <div className={s.cardTitle}>Today's Special (auto timed) 🕒</div>
        <p className={s.note}>Pick an <strong>approved</strong> template and turn it on:</p>
        <ul className={s.noteList}>
          <li>
            🎯 Each customer gets it ~<strong>{special.lead_minutes} min</strong> before
            their usual order time
          </li>
          <li>🕒 No clear pattern yet? They get the <strong>default time</strong> below</li>
          <li>📈 Send times are learned from each customer's past orders</li>
          <li>🔁 Runs every day automatically while the toggle stays on</li>
          <li>✅ Opt out, the 24h cap and the 9am to 6pm window still apply</li>
        </ul>

        <label className={s.checkRow}>
          <input
            type="checkbox"
            checked={special.enabled}
            onChange={(e) => setSpecial((p) => ({ ...p, enabled: e.target.checked }))}
          />
          Enable Today's Special automation
        </label>

        <label className={s.label}>Template</label>
        <select
          className={s.input}
          value={special.template_id ?? ""}
          onChange={(e) =>
            setSpecial((p) => ({
              ...p,
              template_id: e.target.value ? Number(e.target.value) : null,
            }))
          }
        >
          <option value="">Select an approved template</option>
          {approvedTemplates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.meta_template_name}
            </option>
          ))}
        </select>
        {approvedTemplates.length === 0 && (
          <span className={s.hint}>
            No approved templates yet. Create one above and wait for Meta approval.
          </span>
        )}

        <div className={s.row}>
          <div>
            <label className={s.label}>Send this many minutes early</label>
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
          </div>
          <div>
            <label className={s.label}>Default time (new customers)</label>
            <input
              className={s.input}
              type="time"
              value={special.default_time}
              onChange={(e) =>
                setSpecial((p) => ({ ...p, default_time: e.target.value }))
              }
            />
          </div>
        </div>

        <div className={s.specialFooter}>
          <span className={`${s.statusPill} ${special.enabled ? s.statusOn : s.statusOff}`}>
            {special.enabled ? "● Active" : "○ Off"}
          </span>
          <Button onClick={onSaveSpecial} disabled={savingSpecial}>
            {savingSpecial ? "Saving…" : "Save automation"}
          </Button>
        </div>
      </div>

      </div>{/* /columns */}

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
                <div className={s.row}>
                  <textarea
                    className={s.textarea}
                    rows={2}
                    value={describe}
                    onChange={(e) => setDescribe(e.target.value)}
                    placeholder="e.g. 20% off all biryani this weekend, free delivery over AED 50"
                  />
                  <Button variant="ghost" onClick={onDraft} disabled={drafting || describe.trim().length < 3}>
                    {drafting ? "Drafting…" : "✨ Draft"}
                  </Button>
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

                <label className={s.label}>Header image (optional)</label>
                <div className={s.row}>
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
                  {imageUrl && <img src={imageUrl} alt="header" className={s.thumb} />}
                </div>

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

      {/* TEMPLATE PREVIEW — read-only WhatsApp-style render of a template */}
      {previewTpl && (
        <div className={s.overlay} onClick={() => setPreviewTpl(null)}>
          <div className={s.previewModal} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHead}>
              <div className={s.cardTitle}>{previewTpl.meta_template_name}</div>
              <button
                className={s.modalClose}
                onClick={() => setPreviewTpl(null)}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <TemplatePreview
              imageUrl={previewTpl.header?.image_url ?? null}
              body={previewTpl.body ?? ""}
              withButton={(previewTpl.buttons?.length ?? 0) > 0}
              buttonLabel={previewTpl.buttons?.[0]?.label ?? ""}
            />
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
