export type Listener<T> = (value: T) => void;
export type ErrorListener = (err: unknown) => void;

/** Real-time transport contract. PollingTransport is the default impl;
 * a WebSocketTransport can be dropped in later with the same surface. */
export interface Transport<T> {
  subscribe(onValue: Listener<T>, onError?: ErrorListener): () => void;
}
