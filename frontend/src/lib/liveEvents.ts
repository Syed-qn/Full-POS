import { TOKEN_KEY } from "./apiClient";

/**
 * One live stream per tab, shared by every screen that wants it.
 *
 * Terminals used to poll — the cashier floor every 15s, the waiter floor every
 * 20s — so a table seated on another till took that long to appear. This opens
 * a single parked connection instead and the server pushes when something
 * changes, which is both immediate and cheaper: an idle terminal now sends
 * nothing at all rather than a query every few seconds.
 *
 * Shared deliberately. Screens mount and unmount as the user navigates, and one
 * connection per screen would open and close sockets on every route change; the
 * stream is reference-counted and stays up while at least one listener wants it.
 *
 * Uses fetch + a stream reader rather than the browser's EventSource, because
 * EventSource cannot set an Authorization header and the usual workaround is
 * putting the token in the query string, where it lands in access logs and
 * browser history.
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

/** Coarse areas a screen can care about. Matches the server's TOPICS. */
export type LiveTopic = "orders" | "tables" | "kds" | "inventory";

export type LiveEvent = {
  topic: LiveTopic;
  restaurant_id: number;
  [k: string]: unknown;
};

type Listener = (event: LiveEvent) => void;

const listeners = new Set<Listener>();
let controller: AbortController | null = null;
let retries = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

/** Capped exponential backoff. A backend restart must not become a reconnect
 *  storm from every till in the restaurant at once. */
function backoffMs(attempt: number): number {
  const base = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
  // Jitter so tills that dropped together do not all return together.
  return base / 2 + Math.random() * (base / 2);
}

function emit(event: LiveEvent) {
  for (const fn of [...listeners]) {
    try {
      fn(event);
    } catch {
      // One screen's handler must not stop the others from being told.
    }
  }
}

/** Parse the SSE wire format: blank-line-separated records of `field: value`. */
function parseFrames(chunk: string): LiveEvent[] {
  const out: LiveEvent[] = [];
  for (const raw of chunk.split("\n\n")) {
    const block = raw.trim();
    // ":" prefixed lines are comments — the server's keepalive pings.
    if (!block || block.startsWith(":")) continue;
    const dataLine = block
      .split("\n")
      .find((l) => l.startsWith("data:"));
    if (!dataLine) continue;
    try {
      const parsed = JSON.parse(dataLine.slice(5).trim());
      if (parsed && typeof parsed.topic === "string") out.push(parsed as LiveEvent);
    } catch {
      // A truncated frame is not worth tearing the stream down for.
    }
  }
  return out;
}

async function connect(): Promise<void> {
  if (controller || listeners.size === 0) return;
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return; // signed out — nothing to stream

  controller = new AbortController();
  try {
    const res = await fetch(`${API_BASE}/api/v1/events/stream`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      // 401/403 here means this session may not stream. Retrying would hammer
      // the server for a condition that will not change on its own, so stop and
      // leave the screen's fallback poll to carry it.
      if (res.status === 401 || res.status === 403) {
        controller = null;
        return;
      }
      throw new Error(`stream failed: ${res.status}`);
    }
    retries = 0;
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Keep the trailing partial record for the next chunk — a frame can be
      // split across reads, and parsing half of one drops the event.
      const lastBreak = buffer.lastIndexOf("\n\n");
      if (lastBreak === -1) continue;
      const complete = buffer.slice(0, lastBreak);
      buffer = buffer.slice(lastBreak + 2);
      for (const ev of parseFrames(complete)) emit(ev);
    }
  } catch {
    // Network blip, server restart, or an aborted fetch on teardown.
  } finally {
    const wasAborted = controller?.signal.aborted ?? false;
    controller = null;
    if (!wasAborted && listeners.size > 0) {
      retryTimer = setTimeout(() => {
        retryTimer = null;
        void connect();
      }, backoffMs(retries++));
    }
  }
}

function disconnect() {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  controller?.abort();
  controller = null;
  retries = 0;
}

/**
 * Listen for live changes. Returns an unsubscribe function.
 *
 * The connection opens on the first listener and closes when the last one
 * leaves, so a screen simply subscribes and forgets.
 */
export function subscribeLive(fn: Listener): () => void {
  listeners.add(fn);
  void connect();
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) disconnect();
  };
}

/** Drop the stream on sign-out; the next session opens its own. */
export function stopLiveEvents(): void {
  listeners.clear();
  disconnect();
}
