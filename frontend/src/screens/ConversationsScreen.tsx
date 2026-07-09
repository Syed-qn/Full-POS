import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button, TouchButton } from "../components/Button";
import { ConversationRow } from "../components/ConversationRow";
import { MessageBubble } from "../components/MessageBubble";
import { SectionBanner } from "../components/SectionBanner";
import { sendMessage, setTakeover } from "../lib/conversationsApi";
import { ChatCustomerPanel } from "../components/ChatCustomerPanel";
import {
  useConversationMessagesQuery,
  useConversationsQuery,
} from "../lib/queries/dashboard";
import type { ConversationOut, MessageOut } from "../lib/types";
import s from "./ConversationsScreen.module.css";

type Tab = "customer" | "rider";
type ListFilter = "all" | "ai" | "staff";

export function ConversationsScreen() {
  const queryClient = useQueryClient();
  const { data: convs = [], isPending: convsLoading } = useConversationsQuery();
  const [tab, setTab] = useState<Tab>("customer");
  const [listFilter, setListFilter] = useState<ListFilter>("all");
  const [activeId, setActiveId] = useState<number | null>(null);
  const [takeover, setTakeoverState] = useState(false);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);

  const { data: messages = [] } = useConversationMessagesQuery(activeId);

  const customerCount = convs.filter((c) => c.counterpart === "customer").length;
  const riderCount = convs.filter((c) => c.counterpart === "rider").length;
  const isRiderTab = tab === "rider";
  const canCompose = isRiderTab || takeover;
  const digits = query.replace(/\D/g, "");

  const tabConvs = useMemo(
    () =>
      convs.filter(
        (c) =>
          c.counterpart === tab &&
          (digits === "" || c.phone.replace(/\D/g, "").includes(digits)),
      ),
    [convs, tab, digits],
  );

  const visible = useMemo(() => {
    if (isRiderTab || listFilter === "all") return tabConvs;
    if (listFilter === "ai") return tabConvs.filter((c) => !c.manual_takeover);
    return tabConvs.filter((c) => c.manual_takeover);
  }, [tabConvs, listFilter, isRiderTab]);

  const aiCount = tabConvs.filter((c) => !c.manual_takeover).length;
  const staffCount = tabConvs.filter((c) => c.manual_takeover).length;

  function selectTab(next: Tab) {
    if (next === tab) return;
    setTab(next);
    setActiveId(null);
    setListFilter("all");
  }

  useEffect(() => {
    if (activeId === null && visible.length > 0) {
      setActiveId(visible[0].id);
    }
  }, [activeId, visible]);

  useEffect(() => {
    if (activeId === null) return;
    const c = convs.find((x) => x.id === activeId);
    setTakeoverState(c?.manual_takeover ?? false);
  }, [activeId, convs]);

  const lastLenRef = useRef(0);
  const scrollNextRef = useRef(false);
  useEffect(() => {
    scrollNextRef.current = true;
  }, [activeId]);
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

  function patchConversation(id: number, patch: Partial<ConversationOut>) {
    queryClient.setQueryData<ConversationOut[]>(["conversations", "list"], (prev) =>
      (prev ?? []).map((x) => (x.id === id ? { ...x, ...patch } : x)),
    );
  }

  async function toggleTakeover() {
    if (activeId === null) return;
    const next = !takeover;
    setTakeoverState(next);
    patchConversation(activeId, { manual_takeover: next });
    try {
      await setTakeover(activeId, next);
    } catch {
      setTakeoverState(!next);
      patchConversation(activeId, { manual_takeover: !next });
    }
  }

  async function toggleConvTakeover(c: ConversationOut) {
    const next = !c.manual_takeover;
    patchConversation(c.id, { manual_takeover: next });
    if (c.id === activeId) setTakeoverState(next);
    try {
      await setTakeover(c.id, next);
    } catch {
      patchConversation(c.id, { manual_takeover: !next });
      if (c.id === activeId) setTakeoverState(!next);
    }
  }

  async function send() {
    if (activeId === null || !draft.trim()) return;
    const text = draft.trim();
    await sendMessage(activeId, text);
    const optimistic: MessageOut = {
      id: Date.now(),
      direction: "outbound",
      type: "text",
      payload: { text },
      ts: Math.floor(Date.now() / 1000),
    };
    queryClient.setQueryData<MessageOut[]>(
      ["conversations", "messages", activeId],
      (prev) => [...(prev ?? []), optimistic],
    );
    setDraft("");
  }

  return (
    <div className={s.root} data-testid="conversations-screen">
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

          {!isRiderTab && (
            <div className={s.filters} role="toolbar" aria-label="Conversation filters">
              <button
                type="button"
                className={`${s.filterChip} ${listFilter === "all" ? s.filterChipActive : ""}`}
                onClick={() => setListFilter("all")}
              >
                Active ({tabConvs.length})
              </button>
              <button
                type="button"
                className={`${s.filterChip} ${s.filterChipAi} ${
                  listFilter === "ai" ? s.filterChipActive : ""
                }`}
                onClick={() => setListFilter("ai")}
              >
                AI Handling ({aiCount})
              </button>
              <button
                type="button"
                className={`${s.filterChip} ${s.filterChipStaff} ${
                  listFilter === "staff" ? s.filterChipActive : ""
                }`}
                onClick={() => setListFilter("staff")}
              >
                Needs Staff ({staffCount})
              </button>
            </div>
          )}

          <div className={s.searchRow}>
            <span className={s.searchIcon} aria-hidden="true">
              🔍
            </span>
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
            {convsLoading ? (
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
                      : listFilter === "ai"
                        ? "No AI-handled conversations."
                        : listFilter === "staff"
                          ? "No conversations needing staff."
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
                {!isRiderTab && (
                  <>
                    <span
                      className={`${s.aiState} ${takeover ? s.aiStateHuman : s.aiStateBot}`}
                      data-testid="conversation-ai-state"
                    >
                      {takeover ? "🙋 Human takeover" : "🤖 AI handling"}
                    </span>
                    <Button
                      variant={takeover ? "danger" : "primary"}
                      size="touch"
                      onClick={toggleTakeover}
                    >
                      {takeover ? "Switch to AI Reply" : "Switch to Human Reply"}
                    </Button>
                  </>
                )}
                {isRiderTab && (
                  <span className={s.riderHint}>
                    Driver WhatsApp — replies send to their phone.
                  </span>
                )}
              </div>
              {takeover && !isRiderTab && (
                <SectionBanner tone="warning">You are controlling this conversation.</SectionBanner>
              )}
              {isRiderTab && takeover && (
                <SectionBanner tone="info">Driver sent a message — reply below.</SectionBanner>
              )}
              <div className={s.thread} ref={threadRef}>
                {messages.map((m) => (
                  <MessageBubble key={m.id} message={m} conversationId={activeId ?? undefined} />
                ))}
              </div>
              <div className={s.composer}>
                <input
                  className={s.input}
                  placeholder={
                    canCompose
                      ? "Type message"
                      : "Take over (Human Reply) to send a message"
                  }
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  disabled={!canCompose}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                />
                <TouchButton onClick={send} disabled={!canCompose || !draft.trim()}>
                  Send
                </TouchButton>
              </div>
            </>
          )}
        </section>

        <aside className={s.contextPane} aria-label="Customer context">
          <div className={s.contextHead}>Customer context</div>
          <div className={s.contextBody}>
            {activeId === null || isRiderTab ? (
              <div className={s.contextEmpty}>
                {isRiderTab
                  ? "Driver chats have no customer CRM panel."
                  : "Select a customer conversation."}
              </div>
            ) : (
              <ChatCustomerPanel conversationId={activeId} alwaysOpen />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
