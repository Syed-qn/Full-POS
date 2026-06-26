import type { ReactNode } from "react";
import type { MessageOut } from "../lib/types";
import s from "./MessageBubble.module.css";

// Render text the way WhatsApp shows it to the customer: *bold*, _italic_,
// ~strikethrough~ (and Markdown's **bold** collapsed to bold) so the dashboard
// doesn't show raw asterisks. Newlines are preserved via CSS (white-space).
const TOKEN = /(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g;
// A priced menu line — "2. Mutton Biryani — AED 35" (any currency).
const MENU_LINE = /^(\s*)\d+\.\s+(.+(?:AED|aed|Rs\.?|₹|\$)\s*\d)/;

function formatWhatsApp(text: string): ReactNode[] {
  // Show the customer-facing bullet style for older numbered menu messages:
  // drop the leading dish number on priced lines so the dashboard matches WhatsApp.
  const bulleted = text
    .split("\n")
    .map((line) => (MENU_LINE.test(line) ? line.replace(MENU_LINE, "$1• $2") : line))
    .join("\n");
  const normalized = bulleted.replace(/\*\*([^*\n]+)\*\*/g, "*$1*"); // **x** -> *x*
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

export function MessageBubble({ message }: { message: MessageOut }) {
  const text = typeof message.payload.text === "string" ? message.payload.text : JSON.stringify(message.payload);
  const time = message.ts
    ? new Date(message.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "";
  // A voice note arrives as type "audio" with the transcript in payload.text. Tag it
  // with a mic so ops can tell a spoken order apart from a typed one — the text shown
  // is the transcription the bot acted on.
  const isVoice = message.type === "audio";
  return (
    <div className={`${s.row} ${s[message.direction]}`}>
      <div className={s.bubble}>
        <span className={s.text}>
          {isVoice && (
            <span className={s.voiceTag} title="Voice note (transcribed)">
              🎙️ Voice
            </span>
          )}
          {formatWhatsApp(text)}
        </span>
        {time && <span className={s.time}>{time}</span>}
      </div>
    </div>
  );
}
