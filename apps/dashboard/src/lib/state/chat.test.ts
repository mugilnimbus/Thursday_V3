import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatMessage, EventEnvelope, StreamMessage, TimelineMessage } from '../api/types';
import type { StreamClient } from '../live/stream';

const api = vi.hoisted(() => ({ messages: vi.fn(), timeline: vi.fn(), messagesBefore: vi.fn(), send: vi.fn() }));
vi.mock('../api/gateway', () => ({ api }));

import { ChatSession } from './chat.svelte';

function event(pos: number, type: string, payload: Record<string, unknown> = {}): TimelineMessage {
  const envelope = { event_id: `e${pos}`, source: 'voice', seq: pos, ts: '2026-01-01T00:00:00Z', type, chat_id: 'c1', project_id: 'p1', task_id: null, payload };
  return { kind: 'timeline_event', pos, event: envelope as unknown as EventEnvelope } as TimelineMessage;
}

function stream() {
  let listener: ((m: StreamMessage) => void) | null = null;
  const client = { subscribe: (l: (m: StreamMessage) => void) => ((listener = l), () => undefined) } as unknown as StreamClient;
  return { client, deliver: (m: StreamMessage) => listener?.(m) };
}

const history = (messages: ChatMessage[] = []) => ({ messages, pending: [] });

describe('loading a chat', () => {
  beforeEach(() => vi.resetAllMocks());

  it('shows a message that was stored while the chat was loading', async () => {
    const said = event(7, 'user_message', { text: 'one more thing', client_message_id: 'm7' });
    api.messages.mockResolvedValue(history()); // read a moment before the message was stored
    api.timeline.mockResolvedValue({ events: [said] });
    const { client, deliver } = stream();
    const session = new ChatSession('c1', client);
    deliver(said as StreamMessage); // and it also arrived live during the load
    await session.load();
    expect(session.messages.map((m) => m.text)).toEqual(['one more thing']);
  });

  it('does not show a message twice when both lists have it', async () => {
    const stored: ChatMessage = { id: 1, pos: 7, role: 'user', text: 'hello', created_at: '2026-01-01T00:00:00Z', client_message_id: 'm7', direct: false };
    api.messages.mockResolvedValue(history([stored]));
    api.timeline.mockResolvedValue({ events: [event(3, 'assistant_message', { text: 'an older page' }), event(7, 'user_message', { text: 'hello' })] });
    const session = new ChatSession('c1', stream().client);
    await session.load();
    expect(session.messages.map((m) => m.text)).toEqual(['hello']);
  });

  it('keeps everything when a load that failed half-way is tried again', async () => {
    const page = Array.from({ length: 1000 }, (_, i) => event(i + 1, 'task_status'));
    api.messages.mockResolvedValue(history());
    api.timeline.mockResolvedValueOnce({ events: page }).mockRejectedValueOnce(new Error('network'));
    const session = new ChatSession('c1', stream().client);
    await session.load();
    expect(session.error).not.toBeNull();
    api.timeline.mockResolvedValueOnce({ events: page }).mockResolvedValueOnce({ events: [event(1001, 'task_status')] });
    await session.load();
    expect(session.error).toBeNull();
    expect(session.events.length).toBe(1001);
    expect(api.timeline.mock.calls.map((c) => c[1])).toEqual([0, 1000, 0, 1000]);
  });
});
