import { describe, expect, it } from 'vitest';
import { StreamClient, backoffDelay } from './stream';

class FakeSocket {
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {}
  close() {
    this.closed = true;
    this.onclose?.({} as CloseEvent);
  }
  open() {
    this.onopen?.({} as Event);
  }
  deliver(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
  drop() {
    this.onclose?.({} as CloseEvent);
  }
}

function harness() {
  const sockets: FakeSocket[] = [];
  const timers: { fn: () => void; ms: number }[] = [];
  const client = new StreamClient({
    url: (after) => `ws://gw/v1/stream?after=${after}`,
    socket: (url) => {
      const s = new FakeSocket(url);
      sockets.push(s);
      return s;
    },
    setTimer: (fn, ms) => timers.push({ fn, ms }),
    clearTimer: () => undefined,
    random: () => 0.5,
    hiddenCloseMs: 1000,
  });
  return { client, sockets, timers };
}

const event = (pos: number) => ({ kind: 'timeline_event', pos, event: { type: 'tool_call' } });

describe('stream client', () => {
  it('reconnects from the last position and drops replayed duplicates', () => {
    const { client, sockets, timers } = harness();
    const seen: number[] = [];
    client.subscribe((m) => 'pos' in m && seen.push(m.pos));
    client.start(0);
    sockets[0].open();
    sockets[0].deliver(event(1));
    sockets[0].deliver(event(2));
    sockets[0].drop();
    expect(client.state).toBe('offline');
    timers.at(-1)!.fn();
    expect(sockets[1].url).toBe('ws://gw/v1/stream?after=2');
    sockets[1].open();
    sockets[1].deliver(event(2));
    sockets[1].deliver(event(3));
    expect(seen).toEqual([1, 2, 3]);
    expect(client.state).toBe('live');
  });

  it('backs off exponentially up to 30 seconds', () => {
    expect([1, 2, 3, 6, 10].map((a) => backoffDelay(a, () => 0.5))).toEqual([1000, 2000, 4000, 30000, 30000]);
  });

  it('closes while hidden for long and catches up when visible again', () => {
    const { client, sockets, timers } = harness();
    client.start(5);
    sockets[0].open();
    client.visibility(true);
    timers.at(-1)!.fn();
    expect(sockets[0].closed).toBe(true);
    client.visibility(false);
    expect(sockets[1].url).toBe('ws://gw/v1/stream?after=5');
  });

  it('passes ephemeral messages through without moving the cursor', () => {
    const { client, sockets } = harness();
    const kinds: string[] = [];
    client.subscribe((m) => kinds.push(m.kind));
    client.start(3);
    sockets[0].open();
    sockets[0].deliver({ kind: 'chat_delta', chat_id: 'c', client_message_id: 'm', text: 'Hi' });
    expect(kinds).toEqual(['chat_delta']);
    expect(client.lastPos).toBe(3);
  });
});
