/* The live event stream (/v1/stream). One socket for the whole app.

   - Replays from the last position seen, so nothing is missed across reconnects.
   - Reconnects with jittered exponential backoff (1 s doubling to 30 s).
   - While the tab is hidden for a while the socket is closed; on return it reconnects and catches up.
   The WebSocket factory and clock are injectable for tests. */

import type { StreamMessage } from '../api/types';

export type Listener = (message: StreamMessage) => void;
export type ConnectionState = 'connecting' | 'live' | 'offline';
type SocketLike = Pick<WebSocket, 'close'> & {
  onopen: ((ev: Event) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  onerror: ((ev: Event) => void) | null;
};

export interface StreamOptions {
  url?: (after: number) => string;
  socket?: (url: string) => SocketLike;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
  random?: () => number;
  hiddenCloseMs?: number;
}

export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 1000 * 2 ** Math.max(0, attempt - 1));
  return Math.round(base * (0.75 + random() * 0.5));
}

export class StreamClient {
  private socket: SocketLike | null = null;
  private listeners = new Set<Listener>();
  private stateListeners = new Set<(state: ConnectionState) => void>();
  private attempt = 0;
  private retryTimer: unknown = null;
  private hiddenTimer: unknown = null;
  private stopped = true;
  private opts: Required<StreamOptions>;
  lastPos = 0;
  state: ConnectionState = 'offline';

  constructor(options: StreamOptions = {}) {
    this.opts = {
      url: (after) => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/v1/stream?after=${after}`,
      socket: (url) => new WebSocket(url),
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
      random: Math.random,
      hiddenCloseMs: 5 * 60_000,
      ...options,
    };
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onState(listener: (state: ConnectionState) => void): () => void {
    this.stateListeners.add(listener);
    listener(this.state);
    return () => this.stateListeners.delete(listener);
  }

  start(after = 0): void {
    this.lastPos = Math.max(this.lastPos, after);
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.opts.clearTimer(this.retryTimer);
    this.socket?.close();
    this.socket = null;
    this.setState('offline');
  }

  /** Call from a visibilitychange listener. */
  visibility(hidden: boolean): void {
    this.opts.clearTimer(this.hiddenTimer);
    if (hidden) {
      this.hiddenTimer = this.opts.setTimer(() => {
        this.socket?.close();
        this.socket = null;
      }, this.opts.hiddenCloseMs);
    } else if (!this.stopped && !this.socket) {
      this.attempt = 0;
      this.connect();
    }
  }

  private setState(state: ConnectionState): void {
    if (state === this.state) return;
    this.state = state;
    this.stateListeners.forEach((l) => l(state));
  }

  private connect(): void {
    if (this.stopped || this.socket) return;
    this.setState('connecting');
    const socket = this.opts.socket(this.opts.url(this.lastPos));
    this.socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.setState('live');
    };
    socket.onmessage = (event) => {
      let message: StreamMessage;
      try {
        message = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if ('pos' in message) {
        if (message.pos <= this.lastPos) return; // duplicate after a replay
        this.lastPos = message.pos;
      }
      this.listeners.forEach((l) => l(message));
    };
    socket.onerror = () => undefined;
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (this.stopped) return;
      this.setState('offline');
      this.attempt += 1;
      this.retryTimer = this.opts.setTimer(() => this.connect(), backoffDelay(this.attempt, this.opts.random));
    };
  }
}
