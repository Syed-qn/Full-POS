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
    <div className={`${s.row} ${selected ? s.selected : ""}`} onClick={onClick} role="button" tabIndex={0}>
      <div className={s.top}>
        {conversation.unread && <span className={s.dot} />}
        <span className={s.phone}>{conversation.phone}</span>
      </div>
      <span className={s.preview}>{conversation.last_message_preview ?? "—"}</span>
    </div>
  );
}
