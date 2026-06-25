import type { ConversationOut } from "../lib/types";
import s from "./ConversationRow.module.css";

export function ConversationRow({
  conversation,
  selected,
  onClick,
  onTogglePill,
}: {
  conversation: ConversationOut;
  selected: boolean;
  onClick: () => void;
  /** Toggle AI/Human for this conversation (click on the pill). */
  onTogglePill?: () => void;
}) {
  return (
    <div
      className={`${s.row} ${selected ? s.selected : ""}`}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      role="button"
      tabIndex={0}
    >
      <div className={s.top}>
        {conversation.unread && <span className={s.dot} />}
        <span className={s.phone}>{conversation.phone}</span>
        <button
          type="button"
          className={`${s.pill} ${conversation.manual_takeover ? s.pillHuman : s.pillBot}`}
          title={
            conversation.manual_takeover
              ? "A human is handling this chat — click to hand back to the AI"
              : "The AI is handling this chat — click to take over"
          }
          onClick={(e) => {
            e.stopPropagation();
            onTogglePill?.();
          }}
        >
          {conversation.manual_takeover ? "🙋 Human Reply" : "🤖 AI Reply"}
        </button>
      </div>
      <span className={s.preview}>{conversation.last_message_preview ?? "—"}</span>
    </div>
  );
}
