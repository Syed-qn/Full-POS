import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stopLiveEvents, subscribeLive } from "./liveEvents";

/** Serve an SSE body we can push frames into mid-test. */
function streamingResponse() {
  let push!: (chunk: string) => void;
  let close!: () => void;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      const enc = new TextEncoder();
      push = (chunk: string) => c.enqueue(enc.encode(chunk));
      close = () => c.close();
    },
  });
  return {
    response: new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
    push: (chunk: string) => push(chunk),
    close: () => close(),
  };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("liveEvents", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "tok");
  });
  afterEach(() => {
    stopLiveEvents();
    vi.restoreAllMocks();
  });

  it("delivers pushed changes to subscribers", async () => {
    const s = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(s.response));

    const seen: unknown[] = [];
    subscribeLive((e) => seen.push(e));
    await flush();

    s.push('event: change\ndata: {"topic":"tables","restaurant_id":1}\n\n');
    await flush();

    expect(seen).toEqual([{ topic: "tables", restaurant_id: 1 }]);
  });

  it("sends the bearer token in a header, never in the URL", async () => {
    // EventSource cannot set headers, and the usual workaround puts the token
    // in the query string where it lands in access logs and history.
    const s = streamingResponse();
    const fetchMock = vi.fn().mockResolvedValue(s.response);
    vi.stubGlobal("fetch", fetchMock);

    subscribeLive(() => {});
    await flush();

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain("tok");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok",
    });
  });

  it("reassembles a frame split across two chunks", async () => {
    const s = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(s.response));

    const seen: unknown[] = [];
    subscribeLive((e) => seen.push(e));
    await flush();

    // A network read can land mid-frame; parsing half of one drops the event.
    s.push('event: change\ndata: {"topic":"or');
    await flush();
    expect(seen).toEqual([]);

    s.push('ders","restaurant_id":2}\n\n');
    await flush();
    expect(seen).toEqual([{ topic: "orders", restaurant_id: 2 }]);
  });

  it("ignores keepalive comments", async () => {
    const s = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(s.response));

    const seen: unknown[] = [];
    subscribeLive((e) => seen.push(e));
    await flush();

    s.push(": keepalive\n\n");
    await flush();

    expect(seen).toEqual([]);
  });

  it("opens one connection for many subscribers", async () => {
    const s = streamingResponse();
    const fetchMock = vi.fn().mockResolvedValue(s.response);
    vi.stubGlobal("fetch", fetchMock);

    // Screens mount and unmount as the user navigates; one stream per screen
    // would open and close a connection on every route change.
    const offA = subscribeLive(() => {});
    const offB = subscribeLive(() => {});
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    offA();
    offB();
  });

  it("does not retry when the server says this session may not stream", async () => {
    // 403 will not fix itself; retrying would hammer the server forever.
    const fetchMock = vi.fn().mockResolvedValue(new Response("no", { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);

    subscribeLive(() => {});
    await flush();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not connect at all when signed out", async () => {
    localStorage.clear();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    subscribeLive(() => {});
    await flush();

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
