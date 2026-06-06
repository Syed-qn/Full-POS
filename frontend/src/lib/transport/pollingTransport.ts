import type { ErrorListener, Listener, Transport } from "./index";

export class PollingTransport<T> implements Transport<T> {
  private timer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<{ onValue: Listener<T>; onError?: ErrorListener }>();

  constructor(
    private fetcher: () => Promise<T>,
    private intervalMs: number,
  ) {}

  private async tick(): Promise<void> {
    try {
      const value = await this.fetcher();
      for (const l of this.listeners) l.onValue(value);
    } catch (err) {
      for (const l of this.listeners) l.onError?.(err);
    }
  }

  subscribe(onValue: Listener<T>, onError?: ErrorListener): () => void {
    const entry = { onValue, onError };
    this.listeners.add(entry);
    if (this.timer === null) {
      void this.tick(); // fire immediately
      this.timer = setInterval(() => void this.tick(), this.intervalMs);
    }
    return () => {
      this.listeners.delete(entry);
      if (this.listeners.size === 0 && this.timer !== null) {
        clearInterval(this.timer);
        this.timer = null;
      }
    };
  }
}
