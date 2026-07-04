import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { fetchMessageMedia } from "../lib/conversationsApi";
import type { MessageOut } from "../lib/types";
import s from "./MessageBubble.module.css";

const TOKEN = /(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g;
const MENU_LINE = /^(\s*)\d+\.\s+(.+(?:AED|aed|Rs\.?|₹|\$)\s*\d)/;

function formatWhatsApp(text: string): ReactNode[] {
  const bulleted = text
    .split("\n")
    .map((line) => (MENU_LINE.test(line) ? line.replace(MENU_LINE, "$1• $2") : line))
    .join("\n");
  const normalized = bulleted.replace(/\*\*([^*\n]+)\*\*/g, "*$1*");
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN.exec(normalized)) !== null) {
    if (m.index > last) out.push(normalized.slice(last, m.index));
    const tok = m[0];
    const inner = tok.slice(1, -1);
    if (tok[0] === "*") out.push(<strong key={key++}>{inner}</strong>);
    else if (tok[0] === "_") out.push(<em key={key++}>{inner}</em>);
    else out.push(<s key={key++}>{inner}</s>);
    last = m.index + tok.length;
  }
  if (last < normalized.length) out.push(normalized.slice(last));
  return out;
}

function MessageMedia({
  conversationId,
  message,
}: {
  conversationId: number;
  message: MessageOut;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [error, setError] = useState(false);
  const kind = typeof message.payload.media_kind === "string" ? message.payload.media_kind : message.type;
  const filename =
    typeof message.payload.filename === "string" ? message.payload.filename : undefined;

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchMessageMedia(conversationId, message.id)
      .then((mediaBlob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(mediaBlob);
        setBlob(mediaBlob);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [conversationId, message.id]);

  if (error) {
    return <span className={s.mediaUnavailable}>Attachment unavailable</span>;
  }
  if (!src || !blob) {
    return <span className={s.mediaLoading}>Loading attachment…</span>;
  }

  if (kind === "audio") {
    return (
      <audio className={s.mediaAudio} controls preload="metadata" src={src}>
        <track kind="captions" />
      </audio>
    );
  }

  if (kind === "image" || kind === "sticker") {
    return <img className={s.mediaImage} src={src} alt={kind === "sticker" ? "Sticker" : "Photo"} />;
  }

  if (kind === "video") {
    return (
      <video className={s.mediaVideo} controls preload="metadata" src={src}>
        <track kind="captions" />
      </video>
    );
  }

  const isPdf = blob.type.includes("pdf") || filename?.toLowerCase().endsWith(".pdf");
  if (kind === "document" && isPdf) {
    return (
      <div className={s.mediaDoc}>
        <iframe className={s.mediaPdf} src={src} title={filename ?? "Document"} />
        <a className={s.mediaDownload} href={src} download={filename ?? "document.pdf"}>
          Download PDF
        </a>
      </div>
    );
  }

  return (
    <a className={s.mediaDownload} href={src} download={filename ?? "attachment"}>
      📎 Download {filename ?? "attachment"}
    </a>
  );
}

export function MessageBubble({
  message,
  conversationId,
}: {
  message: MessageOut;
  conversationId?: number;
}) {
  const text = typeof message.payload.text === "string" ? message.payload.text : "";
  const showText = text.length > 0;
  // Compaction digest — internal LLM context, never sent to the customer.
  // Render as a centered system note (expandable), not an outbound bubble.
  if (message.type === "system_summary") {
    const summary =
      typeof message.payload.summary === "string" ? message.payload.summary : "";
    return (
      <div className={s.systemRow}>
        <details className={s.systemNote}>
          <summary className={s.systemLabel}>
            📋 Conversation summarized — older messages archived (internal, not
            sent to customer)
          </summary>
          {summary && <pre className={s.systemBody}>{summary}</pre>}
        </details>
      </div>
    );
  }
  const time = message.ts
    ? new Date(message.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "";
  const hasMedia = message.payload.has_media === true;
  const canShowMedia =
    hasMedia && conversationId !== undefined && message.id > 0;
  const isVoice = message.type === "audio";
  const kindLabel =
    message.type === "image"
      ? "📷 Photo"
      : message.type === "document"
        ? "📎 Document"
        : message.type === "video"
          ? "🎬 Video"
          : message.type === "sticker"
            ? "🙂 Sticker"
            : isVoice
              ? "🎙️ Voice"
              : null;

  return (
    <div className={`${s.row} ${s[message.direction]}`}>
      <div className={s.bubble}>
        {canShowMedia && (
          <MessageMedia conversationId={conversationId} message={message} />
        )}
        {(showText || kindLabel) && (
          <span className={s.text}>
            {!showText && kindLabel && <span className={s.mediaTag}>{kindLabel}</span>}
            {isVoice && showText && (
              <span className={s.voiceTag} title="Voice note (transcribed)">
                🎙️ Voice
              </span>
            )}
            {showText ? formatWhatsApp(text) : null}
          </span>
        )}
        {/* Last resort: a stored type with no text/media/label. NEVER dump the
            raw payload here — internal rows (system_summary, cart orders) would
            leak as JSON into the timeline. Show a neutral placeholder instead. */}
        {!showText && !kindLabel && !canShowMedia && (
          <span className={`${s.text} ${s.placeholder}`}>—</span>
        )}
        {time && <span className={s.time}>{time}</span>}
      </div>
    </div>
  );
}