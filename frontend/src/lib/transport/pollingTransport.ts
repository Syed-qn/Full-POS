import type { ErrorListener, Listener, Transport } from "./index";

function isDocumentHidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

export class PollingTransport<T> implements Transport<T> {
  private timer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<{ onValue: Listener<T>; onError?: ErrorListener }>();
  private inFlight = false;
  private onVisibility = () => {
    if (!isDocumentHidden()) void this.tick();
  };

  constructor(
    private fetcher: () => Promise<T>,
    private intervalMs: number,
  ) {}

  private async tick(): Promise<void> {
    if (this.inFlight || isDocumentHidden()) return;
    this.inFlight = true;
    try {
      const value = await this.fetcher();
      for (const l of this.listeners) l.onValue(value);
    } catch (err) {
      for (const l of this.listeners) l.onError?.(err);
    } finally {
      this.inFlight = false;
    }
  }

  subscribe(onValue: Listener<T>, onError?: ErrorListener): () => void {
    const entry = { onValue, onError };
    this.listeners.add(entry);
    if (this.timer === null) {
      if (typeof document !== "undefined") {
        document.addEventListener("visibilitychange", this.onVisibility);
      }
      void this.tick();
      this.timer = setInterval(() => void this.tick(), this.intervalMs);
    }
    return () => {
      this.listeners.delete(entry);
      if (this.listeners.size === 0 && this.timer !== null) {
        clearInterval(this.timer);
        this.timer = null;
        if (typeof document !== "undefined") {
          document.removeEventListener("visibilitychange", this.onVisibility);
        }
      }
    };
  }
}