/* Turn raw events into what the screens show: task cards, trace steps, and agent stats.
   Pure functions, no I/O, so they are unit tested directly. */

import type { EventEnvelope } from '../api/types';

export type Tone = 'ok' | 'warn' | 'run' | 'bad' | 'info';

export interface TaskLine {
  text: string;
  tone: Tone;
  seconds: number;
  /** A tool call's key: its line is added when the call is requested and updated when it ends. */
  callKey?: string;
}

export interface TaskView {
  taskId: string;
  instruction: string;
  state: string;
  pauseState: string;
  startedAt: string;
  step: number;
  summary: string;
  lines: TaskLine[];
}

const TERMINAL = new Set(['completed', 'failed', 'canceled']);
export const isTerminal = (state: string) => TERMINAL.has(state);

const ARG_LIMIT = 60;

export function shortArgs(args: unknown): string {
  if (!args || typeof args !== 'object') return '';
  const values = Object.entries(args as Record<string, unknown>)
    .filter(([k]) => !['content', 'diff', 'new_string', 'old_string'].includes(k))
    .map(([, v]) => (typeof v === 'string' ? v : JSON.stringify(v)));
  const text = values.join(' ');
  return text.length > ARG_LIMIT ? text.slice(0, ARG_LIMIT - 1) + '…' : text;
}

function firstLine(text: unknown): string {
  const line = String(text ?? '').split('\n').find((l) => l.trim()) ?? '';
  return line.length > 80 ? line.slice(0, 79) + '…' : line.trim();
}

/** One line for a tool result: a count for listings, else the first line. */
export function summarize(tool: string, result: unknown): string {
  const lines = String(result ?? '').split('\n').filter((l) => l.trim());
  if (tool === 'fs.list' && lines.length > 1) return `${lines.length} entries`;
  return firstLine(result) + (lines.length > 1 ? ' …' : '');
}

const OUTCOME: Record<string, string> = {
  allowed: 'you allowed it',
  denied: 'you said no',
  timed_out: 'no answer in time',
  canceled: 'cancelled',
};

export function buildTasks(events: EventEnvelope[]): Map<string, TaskView> {
  const tasks = new Map<string, TaskView>();
  const startMs = new Map<string, number>();
  for (const e of events) {
    if (!e.task_id) continue;
    let task = tasks.get(e.task_id);
    if (!task) {
      task = { taskId: e.task_id, instruction: '', state: 'submitted', pauseState: 'none', startedAt: e.ts, step: 0, summary: '', lines: [] };
      tasks.set(e.task_id, task);
      startMs.set(e.task_id, Date.parse(e.ts));
    }
    const seconds = Math.max(0, (Date.parse(e.ts) - (startMs.get(e.task_id) ?? 0)) / 1000);
    const p = e.payload;
    switch (e.type) {
      case 'delegation':
        if (e.source === 'main' || !task.instruction) {
          task.instruction = String(p.instruction ?? task.instruction);
          if (e.source === 'main') task.lines.push({ text: `Delegated “${task.instruction}”`, tone: 'ok', seconds });
        }
        break;
      case 'task_state':
        task.state = String(p.state ?? task.state);
        task.pauseState = String(p.pause_state ?? task.pauseState);
        if (p.summary) task.summary = String(p.summary);
        if (task.state === 'completed') task.lines.push({ text: 'Done', tone: 'ok', seconds });
        if (task.state === 'failed') task.lines.push({ text: `Failed: ${firstLine(p.summary)}`, tone: 'bad', seconds });
        if (task.state === 'canceled') task.lines.push({ text: 'Stopped', tone: 'bad', seconds });
        if (p.pause_state === 'paused' && task.state === 'working') task.lines.push({ text: 'Paused', tone: 'warn', seconds });
        break;
      case 'llm_call':
        if (p.agent === 'main' && p.status === 'ok') task.step = Math.max(task.step, Number(p.step ?? 0));
        if (p.agent === 'main' && String(p.status).startsWith('error'))
          task.lines.push({ text: `Model call failed (${p.status}), retrying`, tone: 'bad', seconds });
        break;
      case 'tool_call': {
        // The line appears the moment the call is requested (purple, pulsing) and turns green or red when it ends.
        const status = String(p.status);
        const callKey = p.call_key ? String(p.call_key) : undefined;
        const open = callKey ? task.lines.find((l) => l.callKey === callKey) : undefined;
        const call = `${p.tool} ${shortArgs(p.arguments)}`.trim();
        if (status === 'requested' || status === 'running') {
          if (!open) task.lines.push({ text: call, tone: 'run', seconds, callKey });
          break;
        }
        const tone: Tone = status === 'ok' ? 'ok' : status === 'unknown' ? 'warn' : 'bad';
        const result = status === 'unknown' ? 'outcome unknown after a restart' : summarize(String(p.tool), p.result);
        if (open) Object.assign(open, { text: `${call} → ${result}`, tone, seconds }); // the time shown is when it ended
        else task.lines.push({ text: `${call} → ${result}`, tone, seconds, callKey });
        break;
      }
      case 'approval_requested':
        task.lines.push({ text: `Asked: ${p.summary}`, tone: 'warn', seconds });
        break;
      case 'approval_resolved':
        task.lines.push({ text: `Approval: ${OUTCOME[String(p.outcome)] ?? p.outcome}${p.by === 'allow_always_rule' ? ' (always allowed)' : ''}`, tone: p.outcome === 'allowed' ? 'ok' : 'warn', seconds });
        break;
      case 'compaction':
        task.lines.push({ text: 'Summarised earlier turns to fit the context', tone: 'info', seconds });
        break;
    }
  }
  for (const task of tasks.values()) {
    // A finished task has no call still running; one that never reported back is shown as unfinished.
    if (isTerminal(task.state))
      for (const line of task.lines)
        if (line.tone === 'run') Object.assign(line, { text: `${line.text} → did not finish`, tone: 'warn' });
  }
  return tasks;
}

/** Event positions per task: where it began, and, for a task sent straight to the main agent, where the voice agent
 *  announced it. */
export function taskStarts(events: { pos: number; event: EventEnvelope }[]): { first: Map<string, number>; direct: Map<string, number> } {
  const first = new Map<string, number>();
  const direct = new Map<string, number>();
  for (const { pos, event } of events) {
    if (!event.task_id) continue;
    if (!first.has(event.task_id)) first.set(event.task_id, pos);
    if (event.type === 'delegation' && event.source === 'voice' && event.payload.by === 'direct') direct.set(event.task_id, pos);
  }
  return { first, direct };
}

/** Where a task card sits among the messages (`messages` sorted by position). Normally under the reply that announced it
 *  ("On it…"), else where the task began. A task sent straight to the main agent has no such reply, and the main agent
 *  announces it before the voice agent publishes your message, so its card goes where the voice agent announced it,
 *  which is right after your message. */
export function cardPosition(first: number, direct: number | undefined, messages: { pos: number | null; role: string }[]): number {
  if (direct !== undefined) return direct;
  const next = messages.find((m) => (m.pos ?? 0) > first);
  return next?.role === 'assistant' ? (next.pos ?? 0) + 0.5 : first;
}

/** The line shown with a pulsing dot while a task is still working. */
export function liveLine(task: TaskView): TaskLine | null {
  if (isTerminal(task.state)) return null;
  if (task.state === 'input_required') return { text: 'Waiting for your approval…', tone: 'warn', seconds: 0 };
  if (task.pauseState === 'paused') return null;
  return { text: task.pauseState === 'pausing' ? 'Finishing this step, then pausing…' : 'Working…', tone: 'run', seconds: 0 };
}

/* ---------- trace ---------- */

export interface ToolStep {
  callKey: string;
  tool: string;
  args: Record<string, unknown>;
  status: string;
  result: string;
  seconds: number | null;
  approval: { summary: string; outcome: string | null; by: string | null; askedAt: string; answeredAt: string | null } | null;
}

export interface TraceStep {
  no: number;
  llm: Record<string, any> | null;
  attempts: number;
  tools: ToolStep[];
  compactedBefore: Record<string, any> | null;
}

export function buildTrace(events: EventEnvelope[]): TraceStep[] {
  const steps = new Map<number, TraceStep>();
  const byKey = new Map<string, ToolStep>();
  const approvals = new Map<string, NonNullable<ToolStep['approval']>>();
  let pendingCompaction: Record<string, any> | null = null;
  const step = (no: number) => {
    let s = steps.get(no);
    if (!s) {
      s = { no, llm: null, attempts: 0, tools: [], compactedBefore: null };
      steps.set(no, s);
    }
    return s;
  };
  for (const e of events) {
    const p = e.payload;
    if (e.type === 'compaction') pendingCompaction = p;
    if (e.type === 'llm_call' && p.agent === 'main') {
      const s = step(Number(p.step ?? 1));
      s.attempts += 1;
      if (p.status === 'ok' || !s.llm) s.llm = p;
      if (pendingCompaction) {
        s.compactedBefore = pendingCompaction;
        pendingCompaction = null;
      }
    }
    if (e.type === 'tool_call') {
      const key = String(p.call_key);
      const no = Number(key.split(':')[1] ?? 1);
      let tool = byKey.get(key);
      if (!tool) {
        tool = { callKey: key, tool: String(p.tool), args: p.arguments ?? {}, status: String(p.status), result: '', seconds: null, approval: approvals.get(key) ?? null };
        byKey.set(key, tool);
        step(no).tools.push(tool);
      }
      tool.status = String(p.status);
      if (p.result !== undefined) tool.result = String(p.result);
      if (p.seconds !== undefined) tool.seconds = Number(p.seconds);
    }
    if (e.type === 'approval_requested') {
      const key = String(p.call_key ?? '');
      const found = [...byKey.values()].find((t) => t.tool === p.tool && !t.approval && ['requested', 'running'].includes(t.status));
      const approval = { summary: String(p.summary), outcome: null, by: null, askedAt: e.ts, answeredAt: null };
      if (key) approvals.set(key, approval);
      if (found) found.approval = approval;
      approvals.set(String(p.approval_id), approval);
    }
    if (e.type === 'approval_resolved') {
      let approval = approvals.get(String(p.approval_id)) ?? approvals.get(String(p.call_key));
      if (!approval && p.call_key) {
        // Allowed by an allow-always rule: nothing was asked, the rule answered.
        approval = { summary: 'Allowed by an always rule', outcome: null, by: null, askedAt: e.ts, answeredAt: null };
        approvals.set(String(p.call_key), approval);
        const tool = byKey.get(String(p.call_key));
        if (tool && !tool.approval) tool.approval = approval;
      }
      if (approval) {
        approval.outcome = String(p.outcome);
        approval.by = p.by ?? null;
        approval.answeredAt = p.by === 'allow_always_rule' ? null : e.ts;
      }
    }
  }
  return [...steps.values()].sort((a, b) => a.no - b.no);
}

/* ---------- agent stats for the chat subtitle ---------- */

export interface AgentStats {
  tokensPerSecond: number | null;
  /** Tokens the agent sent in its last call: how much of the window is in use. */
  contextTokens: number | null;
  contextLength: number | null;
}

export function agentStats(events: EventEnvelope[], agent: 'main' | 'voice'): AgentStats {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type !== 'llm_call' || e.payload.agent !== agent || e.payload.status !== 'ok') continue;
    const p = e.payload;
    const length = p.context_length ?? null;
    const input = p.usage?.input_tokens ?? null;
    return {
      tokensPerSecond: p.tokens_per_second ? Math.round(p.tokens_per_second) : null,
      contextLength: length,
      contextTokens: input,
    };
  }
  return { tokensPerSecond: null, contextTokens: null, contextLength: null };
}

/** "4412/16384": tokens in use out of the window, as far as each is known. */
export function contextText(used: number | null, window: number | null): string {
  if (used && window) return `${used}/${window}`;
  if (used) return `${used} tokens`;
  return window ? `–/${window}` : '';
}

export function formatContext(length: number | null): string {
  if (!length) return 'unknown';
  return length >= 1000 ? `${Math.round(length / 1000)}k` : String(length);
}
