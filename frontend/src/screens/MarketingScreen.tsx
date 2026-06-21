import { useEffect, useRef, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/Button";
import { toast } from "../components/Toaster";
import {
  broadcast,
  createTemplate,
  draftTemplate,
  fetchTemplates,
  refreshTemplate,
  submitTemplate,
  uploadTemplateImage,
  type TemplateResponse,
} from "../lib/marketingApi";
import s from "./MarketingScreen.module.css";

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
  pending_meta: "Pending Meta approval",
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
  const fileRef = useRef<HTMLInputElement>(null);

  // Broadcast — per-template, triggered from the list (after approval)
  const [armedId, setArmedId] = useState<number | null>(null);
  const [sendingId, setSendingId] = useState<number | null>(null);

  async function reload() {
    const rows = await fetchTemplates().catch(() => []);
    setTemplates(rows);
    setLoaded(true);
  }
  useEffect(() => {
    reload();
  }, []);

  async function onDraft() {
    if (describe.trim().length < 3) return;
    setDrafting(true);
    try {
      const d = await draftTemplate({ describe: describe.trim() });
      if (!name) setName(d.suggested_name);
      setBody(d.body);
      toast("Draft ready — review and edit, then submit.", "success");
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
        toast("Template approved — ready to broadcast! 🎉", "success");
      } else if (submitted.status === "rejected") {
        toast(`Rejected: ${submitted.rejection_reason ?? "see Meta"}`, "error");
      } else {
        toast("Submitted to Meta — awaiting approval (refresh to check).", "success");
      }
      // Reset the form for the next template.
      setDescribe("");
      setName("");
      setBody("");
      setImageUrl(null);
      setWithButton(false);
      setButtonLabel("");
      setButtonUrl("");
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
        res.suppressed_window ? `${res.suppressed_window} outside 9am–6pm window` : "",
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
      <PageHeader
        title="Marketing"
        subtitle="WhatsApp promotions — create a template, get it approved, broadcast"
      />

      {/* CREATE TEMPLATE — preview (left) + form (right) */}
      <div className={s.card}>
        <div className={s.cardTitle}>1 · Create WhatsApp template</div>
        <p className={s.note}>
          Describe your offer and we'll draft a Meta-compliant message. WhatsApp
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

      {/* TEMPLATE LIST — Send appears here once a template is approved */}
      <div className={s.card}>
        <div className={s.cardTitle}>2 · Your templates</div>
        <p className={s.note}>
          Once a template is <strong>approved</strong>, tap <strong>Send</strong> to
          broadcast it to all opted-in customers. Opted-out customers, anyone already
          messaged twice in 24h, and (per UAE rules) sends outside 9am–6pm are skipped.
        </p>
        {!loaded ? (
          <div className={s.empty}>Loading…</div>
        ) : templates.length === 0 ? (
          <div className={s.empty}>No templates yet.</div>
        ) : (
          <div className={s.tplList}>
            {templates.map((t) => (
              <div key={t.id} className={s.tplRow}>
                <span className={s.tplName}>{t.meta_template_name}</span>
                <span className={`${s.badge} ${s["badge_" + t.status] ?? ""}`}>
                  {STATUS_LABEL[t.status] ?? t.status}
                </span>
                {t.status === "rejected" && t.rejection_reason && (
                  <span className={s.reject}>{t.rejection_reason}</span>
                )}
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
              </div>
            ))}
          </div>
        )}
      </div>
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
