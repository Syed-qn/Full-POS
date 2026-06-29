import { useEffect, useRef, useState } from "react";
import { Button } from "../components/Button";
import { ConversationRow } from "../components/ConversationRow";
import { MessageBubble } from "../components/MessageBubble";
import { SectionBanner } from "../components/SectionBanner";
import { fetchConversations, fetchMessages, sendMessage, setTakeover } from "../lib/conversationsApi";
import { ChatCustomerPanel } from "../components/ChatCustomerPanel";
import { usePollingRefresh } from "../lib/usePollingRefresh";
import type { ConversationOut, MessageOut } from "../lib/types";
import s from "./ConversationsScreen.module.css";

type Tab = "customer" | "rider";

export function ConversationsScreen() {
  const [convs, setConvs] = useState<ConversationOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState<Tab>("customer");
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [takeover, setTakeoverState] = useState(false);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);

  const customerCount = convs.filter((c) => c.counterpart === "customer").length;
  const riderCount = convs.filter((c) => c.counterpart === "rider").length;
  // Filter by number: compare digits only, so "+971 50" and "97150" both match.
  const digits = query.replace(/\D/g, "");
  const visible = convs.filter(
    (c) => c.counterpart === tab && (digits === "" || c.phone.replace(/\D/g, "").includes(digits)),
  );

  function selectTab(next: Tab) {
    if (next === tab) return;
    setTab(next);
    setActiveId(null); // clear selection — it belongs to the other tab
  }

  useEffect(() => {
    fetchConversations().then(setConvs).finally(() => setLoaded(true));
  }, []);

  // Live updates: refresh the thread list in the background. The effect below
  // depends on `convs`, so a poll also refreshes the open thread's messages —
  // new incoming WhatsApp messages appear without a manual refresh.
  usePollingRefresh(() => {
    fetchConversations().then(setConvs).catch(() => {});
  });

  // Auto-select the first conversation in the visible list when nothing is
  // selected (initial load, tab switch, or after filtering by number).
  useEffect(() => {
    if (activeId === null && visible.length > 0) {
      setActiveId(visible[0].id);
    }
  }, [activeId, visible]);

  useEffect(() => {
    if (activeId === null) return;
    fetchMessages(activeId).then(setMessages);
    const c = convs.find((x) => x.id === activeId);
    setTakeoverState(c?.manual_takeover ?? false);
  }, [activeId, convs]);

  // Auto-scroll to the newest message ONLY when the thread is opened/switched or
  // a new message actually arrives — never on a routine poll that returns the
  // same messages, so reading back through history isn't yanked to the bottom.
  const lastLenRef = useRef(0);
  const scrollNextRef = useRef(false);
  useEffect(() => { scrollNextRef.current = true; }, [activeId]);
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    const grew = messages.length > lastLenRef.current;
    if (scrollNextRef.current || grew) {
      el.scrollTop = el.scrollHeight;
      scrollNextRef.current = false;
    }
    lastLenRef.current = messages.length;
  }, [messages]);

  async function toggleTakeover() {
    if (activeId === null) return;
    const next = !takeover;
    setTakeoverState(next);
    await setTakeover(activeId, next);
  }

  // Toggle AI/Human directly from a conversation's pill in the list (works on
  // any row, selected or not). Optimistic update + revert on failure.
  async function toggleConvTakeover(c: ConversationOut) {
    const next = !c.manual_takeover;
    setConvs((prev) => prev.map((x) => (x.id === c.id ? { ...x, manual_takeover: next } : x)));
    if (c.id === activeId) setTakeoverState(next);
    try {
      await setTakeover(c.id, next);
    } catch {
      setConvs((prev) => prev.map((x) => (x.id === c.id ? { ...x, manual_takeover: !next } : x)));
      if (c.id === activeId) setTakeoverState(!next);
    }
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
      <aside className={s.sidebar}>
        <div className={s.tabs} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "customer"}
            className={`${s.tab} ${tab === "customer" ? s.tabActive : ""}`}
            onClick={() => selectTab("customer")}
          >
            Customers{customerCount > 0 ? ` (${customerCount})` : ""}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "rider"}
            className={`${s.tab} ${tab === "rider" ? s.tabActive : ""}`}
            onClick={() => selectTab("rider")}
          >
            Drivers{riderCount > 0 ? ` (${riderCount})` : ""}
          </button>
        </div>
        <div className={s.searchRow}>
          <span className={s.searchIcon} aria-hidden="true">🔍</span>
          <input
            className={s.search}
            type="search"
            inputMode="tel"
            placeholder="Filter by number"
            aria-label="Filter conversations by phone number"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className={s.list}>
          {!loaded ? (
            <div aria-busy="true" aria-label="Loading conversations">
              {Array.from({ length: 7 }).map((_, i) => (
                <div key={i} className={s.skRow}>
                  <span className={`${s.sk} ${s.skRowTop}`} />
                  <span className={`${s.sk} ${s.skRowPreview}`} />
                </div>
              ))}
            </div>
          ) : (
            <>
              {visible.map((c) => (
                <ConversationRow
                  key={c.id}
                  conversation={c}
                  selected={c.id === activeId}
                  onClick={() => setActiveId(c.id)}
                  onTogglePill={() => toggleConvTakeover(c)}
                />
              ))}
              {visible.length === 0 && (
                <div className={s.empty}>
                  {digits
                    ? `No ${tab === "customer" ? "customer" : "driver"} matches that number.`
                    : `No ${tab === "customer" ? "customer" : "driver"} conversations yet.`}
                </div>
              )}
            </>
          )}
        </div>
      </aside>
      <section className={s.viewer}>
        {activeId === null ? (
          <div className={s.empty}>Select a conversation.</div>
        ) : (
          <>
            <div className={s.viewerHead}>
              <Button variant={takeover ? "danger" : "ghost"} onClick={toggleTakeover}>
                {takeover ? "Switch to AI Reply" : "Switch to Human Reply"}
              </Button>
            </div>
            {tab === "customer" && (
              <ChatCustomerPanel
                conversationId={activeId}
                onSendToCustomer={(text) => {
                  if (activeId !== null) sendMessage(activeId, text).then(() => {
                    fetchMessages(activeId).then(setMessages);
                  });
                }}
              />
            )}
            {takeover && (
              <SectionBanner tone="warning">You are controlling this conversation.</SectionBanner>
            )}
            <div className={s.thread} ref={threadRef}>
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
