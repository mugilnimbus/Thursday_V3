/* One open chat: its messages, its task events, messages being sent, replies streaming in, and
   what the voice agent is doing. Stored history comes over REST; everything newer comes from the
   live stream and is merged by event position, so nothing shows twice. */

import { api } from '../api/gateway';
import { ApiError } from '../api/http';
import type { ChatMessage, EventEnvelope, StreamMessage } from '../api/types';

interface Positioned {
  pos: number;
  event: EventEnvelope;
}
import type { StreamClient } from '../live/stream';
import { buildTasks, type TaskView } from './timeline';

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

export interface Outgoing {
  clientMessageId: string;
  text: string;
  /** sending: posting to the gateway; unsent: the gateway could not be reached (retry keeps the same id). */
  status: 'sending' | 'queued' | 'delivered' | 'failed' | 'unsent';
  error: string;
}

export type ThreadItem =
  | { kind: 'message'; key: string; pos: number; message: ChatMessage }
  | { kind: 'task'; key: string; pos: number; task: TaskView };

const PAGE = 1000;
const SPEAKING_TAIL_MS = 1200;

export class ChatSession {
  messages = $state.raw<ChatMessage[]>([]);
  events = $state.raw<Positioned[]>([]);
  outgoing = $state<Outgoing[]>([]);
  replies = $state<Record<string, string>>({});
  loading = $state(true);
  error = $state<string | null>(null);
  hasEarlier = $state(false);
  voice = $state<VoiceState>('idle');

  tasks = $derived(buildTasks(this.events.map((e) => e.event)));
  items = $derived(this.buildItems());

  /** Called for each new reply from the voice agent as it arrives (used to read it aloud). */
  onReply: ((text: string) => void) | null = null;

  private seenPos = new Set<number>();
  private lastEventPos = 0;
  private unsubscribe: () => void;
  private buffered: StreamMessage[] | null = [];
  private speakingTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    readonly chatId: string,
    stream: StreamClient,
  ) {
    // Subscribe before loading so nothing that happens during the load is missed.
    this.unsubscribe = stream.subscribe((message) => (this.buffered ? this.buffered.push(message) : this.onStream(message)));
  }

  dispose(): void {
    this.unsubscribe();
    if (this.speakingTimer) clearTimeout(this.speakingTimer);
  }

  async load(): Promise<void> {
    this.loading = true;
    this.error = null;
    try {
      const [history, events] = await Promise.all([api.messages(this.chatId), this.loadEvents()]);
      this.messages = history.messages;
      history.messages.forEach((m) => m.pos !== null && this.seenPos.add(m.pos));
      this.hasEarlier = history.messages.length >= 50;
      this.outgoing = history.pending
        .filter((p) => p.status !== 'delivered')
        .map((p) => ({ clientMessageId: p.client_message_id, text: p.text, status: p.status, error: p.error }));
      this.events = events;
      const buffered = this.buffered ?? [];
      this.buffered = null;
      buffered.forEach((m) => this.onStream(m));
    } catch (error) {
      this.error = error instanceof ApiError ? error.message : 'Could not load this chat.';
    } finally {
      this.loading = false;
    }
  }

  private async loadEvents(): Promise<Positioned[]> {
    const all: Positioned[] = [];
    for (;;) {
      const { events } = await api.timeline(this.chatId, this.lastEventPos);
      for (const m of events) {
        all.push({ pos: m.pos, event: m.event });
        this.lastEventPos = Math.max(this.lastEventPos, m.pos);
      }
      if (events.length < PAGE) return all;
    }
  }

  async loadEarlier(): Promise<void> {
    const first = this.messages[0];
    if (!first) return;
    const { messages } = await api.messagesBefore(this.chatId, first.id);
    messages.forEach((m) => m.pos !== null && this.seenPos.add(m.pos));
    this.messages = [...messages, ...this.messages];
    this.hasEarlier = messages.length >= 50;
  }

  /* ---------- sending ---------- */

  async send(text: string): Promise<void> {
    const entry: Outgoing = { clientMessageId: crypto.randomUUID(), text, status: 'sending', error: '' };
    this.outgoing = [...this.outgoing, entry];
    await this.post(entry.clientMessageId);
  }

  /** Re-send with the same id; the gateway treats a repeat as the same message. */
  async retry(clientMessageId: string): Promise<void> {
    await this.post(clientMessageId);
  }

  retryUnsent(): void {
    this.outgoing.filter((o) => o.status === 'unsent').forEach((o) => void this.post(o.clientMessageId));
  }

  private async post(clientMessageId: string): Promise<void> {
    const entry = this.outgoing.find((o) => o.clientMessageId === clientMessageId);
    if (!entry) return;
    entry.status = 'sending';
    entry.error = '';
    try {
      const result = await api.send(this.chatId, clientMessageId, entry.text);
      if (entry.status === 'sending') entry.status = result.status as Outgoing['status'];
      if (entry.status !== 'failed') this.setVoice('thinking');
    } catch (error) {
      entry.status = error instanceof ApiError && !error.offline && error.status < 500 ? 'failed' : 'unsent';
      entry.error = error instanceof ApiError ? error.message : 'Could not send.';
    }
  }

  /* ---------- live updates ---------- */

  private onStream(message: StreamMessage): void {
    if (message.kind === 'chat_delta' || message.kind === 'outgoing') {
      if (message.chat_id !== this.chatId) return;
      if (message.kind === 'chat_delta') {
        this.replies[message.client_message_id] = (this.replies[message.client_message_id] ?? '') + message.text;
        this.setVoice('speaking');
        this.settleSoon();
      } else {
        this.onOutgoing(message);
      }
      return;
    }
    if (message.kind === 'status_banner' || message.kind === 'catalog_changed') return;
    const event = message.event;
    if (event.chat_id !== this.chatId || message.pos <= this.lastEventPos) return;
    this.lastEventPos = message.pos;
    this.events = [...this.events, { pos: message.pos, event }];
    if (event.type === 'user_message' || event.type === 'assistant_message') this.addMessage(message.pos, event);
  }

  private onOutgoing(message: Extract<StreamMessage, { kind: 'outgoing' }>): void {
    const entry = this.outgoing.find((o) => o.clientMessageId === message.client_message_id);
    if (!entry) {
      // Sent from another device: show it until the stored message arrives.
      if (message.status === 'queued' && message.text)
        this.outgoing = [...this.outgoing, { clientMessageId: message.client_message_id, text: message.text, status: 'queued', error: '' }];
      return;
    }
    entry.status = message.status as Outgoing['status'];
    entry.error = message.error ?? '';
    if (message.status === 'failed') {
      delete this.replies[message.client_message_id];
      this.setVoice('idle');
    }
    if (message.status === 'delivered') this.settleSoon();
  }

  private addMessage(pos: number, event: EventEnvelope): void {
    if (this.seenPos.has(pos)) return;
    this.seenPos.add(pos);
    const clientId: string | null = event.payload.client_message_id ?? null;
    const message: ChatMessage = {
      id: pos,
      pos,
      role: event.type === 'user_message' ? 'user' : 'assistant',
      text: String(event.payload.text ?? ''),
      created_at: event.ts,
      client_message_id: clientId,
    };
    this.messages = [...this.messages, message];
    if (message.role === 'assistant' && Date.now() - Date.parse(event.ts) < 60_000) this.onReply?.(message.text);
    if (!clientId) return;
    if (message.role === 'user') this.outgoing = this.outgoing.filter((o) => o.clientMessageId !== clientId);
    else {
      delete this.replies[clientId];
      this.settleSoon();
    }
  }

  /* ---------- voice agent presence ---------- */

  setVoice(state: VoiceState): void {
    this.voice = state;
  }

  /** Back to idle once replies stop arriving for a moment. */
  private settleSoon(): void {
    if (this.speakingTimer) clearTimeout(this.speakingTimer);
    this.speakingTimer = setTimeout(() => {
      const stillSending = this.outgoing.some((o) => o.status === 'sending' || o.status === 'queued');
      if (this.voice !== 'listening') this.voice = stillSending && !Object.keys(this.replies).length ? 'thinking' : 'idle';
    }, SPEAKING_TAIL_MS);
  }

  /* ---------- thread ---------- */

  private buildItems(): ThreadItem[] {
    const items: ThreadItem[] = this.messages.map((m) => ({ kind: 'message', key: `m${m.id}`, pos: m.pos ?? 0, message: m }));
    const byPos = [...this.messages].sort((a, b) => (a.pos ?? 0) - (b.pos ?? 0));
    const start = new Map<string, number>();
    for (const { pos, event } of this.events) if (event.task_id && !start.has(event.task_id)) start.set(event.task_id, pos);
    for (const task of this.tasks.values()) {
      // A task card sits under the reply that announced it ("On it…"), else where the task began.
      const first = start.get(task.taskId) ?? Infinity;
      const next = byPos.find((m) => (m.pos ?? 0) > first);
      const pos = next?.role === 'assistant' ? (next.pos ?? 0) + 0.5 : first;
      items.push({ kind: 'task', key: `t${task.taskId}`, pos, task });
    }
    return items.sort((a, b) => a.pos - b.pos);
  }
}
