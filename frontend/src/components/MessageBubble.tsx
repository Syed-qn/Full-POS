import type { MessageOut } from "../lib/types";
import s from "./MessageBubble.module.css";

export function MessageBubble({ message }: { message: MessageOut }) {
  const text = typeof message.payload.text === "string" ? message.payload.text : JSON.stringify(message.payload);
  return (
    <div className={`${s.row} ${s[message.direction]}`}>
      <div className={s.bubble}>{text}</div>
    </div>
  );
}
