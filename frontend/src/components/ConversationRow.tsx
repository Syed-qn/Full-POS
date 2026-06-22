import type { ConversationOut } from "../lib/types";
import s from "./ConversationRow.module.css";

export function ConversationRow({
  conversation,
  selected,
  onClick,
}: {
  conversation: ConversationOut;
  selected: boolean;
  onClick: () => void;
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
        <span
          className={`${s.pill} ${conversation.manual_takeover ? s.pillHuman : s.pillBot}`}
          title={
            conversation.manual_takeover
              ? "A human is handling this chat (bot paused)"
              : "The bot is handling this chat automatically"
          }
        >
          {conversation.manual_takeover ? "🙋 Human" : "🤖 Bot"}
        </span>
      </div>
      <span className={s.preview}>{conversation.last_message_preview ?? "—"}</span>
    </div>
  );
}
