/* Turn raw events into what the screens show: task cards, trace steps, and agent stats.
   Pure functions, no I/O, so they are unit tested directly. */

import type { EventEnvelope } from '../api/types';

export type Tone = 'ok' | 'warn' | 'run' | 'bad' | 'info';

export interface TaskLine {
  text: string;
  tone: Tone;
  seconds: number;
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
        const status = String(p.status);
        if (status === 'requested' || status === 'running') break;
        const tone: Tone = status === 'ok' ? 'ok' : status === 'unknown' ? 'warn' : 'bad';
        const result = status === 'unknown' ? 'outcome unknown after a restart' : summarize(String(p.tool), p.result);
        task.lines.push({ text: `${p.tool} ${shortArgs(p.arguments)} → ${result}`.trim(), tone, seconds });
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
  return tasks;
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
  contextPercent: number | null;
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
      contextPercent: length && input ? Math.min(100, Math.round((input / length) * 100)) : null,
    };
  }
  return { tokensPerSecond: null, contextPercent: null, contextLength: null };
}

export function formatContext(length: number | null): string {
  if (!length) return 'unknown';
  return length >= 1000 ? `${Math.round(length / 1000)}k` : String(length);
}
