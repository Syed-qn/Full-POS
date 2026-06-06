import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { ConversationRow } from "../components/ConversationRow";
import { MessageBubble } from "../components/MessageBubble";
import { SectionBanner } from "../components/SectionBanner";
import { fetchConversations, fetchMessages, sendMessage, setTakeover } from "../lib/conversationsApi";
import type { ConversationOut, MessageOut } from "../lib/types";
import s from "./ConversationsScreen.module.css";

export function ConversationsScreen() {
  const [convs, setConvs] = useState<ConversationOut[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [takeover, setTakeoverState] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    fetchConversations().then(setConvs);
  }, []);

  useEffect(() => {
    if (activeId === null) return;
    fetchMessages(activeId).then(setMessages);
    const c = convs.find((x) => x.id === activeId);
    setTakeoverState(c?.manual_takeover ?? false);
  }, [activeId, convs]);

  async function toggleTakeover() {
    if (activeId === null) return;
    const next = !takeover;
    setTakeoverState(next);
    await setTakeover(activeId, next);
  }

  async function send() {
    if (activeId === null || !draft.trim()) return;
    await sendMessage(activeId, draft.trim());
    setMessages((m) => [
      ...m,
      { id: Date.now(), direction: "outbound", type: "text", payload: { text: draft.trim() }, ts: Math.floor(Date.now() / 1000) },
    ]);
    setDraft("");
  }

  return (
    <div className={s.layout}>
      <aside className={s.list}>
        {convs.map((c) => (
          <ConversationRow key={c.id} conversation={c} selected={c.id === activeId} onClick={() => setActiveId(c.id)} />
        ))}
        {convs.length === 0 && <div className={s.empty}>Conversations will appear here.</div>}
      </aside>
      <section className={s.viewer}>
        {activeId === null ? (
          <div className={s.empty}>Select a conversation.</div>
        ) : (
          <>
            <div className={s.viewerHead}>
              <Button variant={takeover ? "danger" : "ghost"} onClick={toggleTakeover}>
                {takeover ? "Return to bot" : "Take over"}
              </Button>
            </div>
            {takeover && (
              <SectionBanner tone="warning">You are controlling this conversation.</SectionBanner>
            )}
            <div className={s.thread}>
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </div>
            <div className={s.composer}>
              <input
                className={s.input}
                placeholder="Type message"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={!takeover}
              />
              <Button onClick={send} disabled={!takeover}>Send</Button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
