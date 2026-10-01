import { describe, expect, it } from 'vitest';
import type { EventEnvelope, EventType } from '../api/types';
import { agentStats, buildTasks, buildTrace, liveLine, shortArgs } from './timeline';

let seq = 0;
function ev(type: EventType, payload: Record<string, any>, over: Partial<EventEnvelope> = {}): EventEnvelope {
  seq += 1;
  return {
    event_id: `e${seq}`, source: 'main', seq, ts: new Date(Date.UTC(2026, 9, 1, 12, 0, seq)).toISOString(),
    project_id: 'p', chat_id: 'c', task_id: 't1', type, payload, ...over,
  };
}

const flow = [
  ev('delegation', { instruction: 'Delete old.log' }),
  ev('task_state', { state: 'working', pause_state: 'none' }),
  ev('llm_call', { agent: 'main', step: 1, status: 'ok', usage: { input_tokens: 900 }, context_length: 32000, tokens_per_second: 61.7 }),
  ev('tool_call', { call_key: 't1:1:0', tool: 'fs.list', arguments: { path: 'logs' }, status: 'requested' }),
  ev('tool_call', { call_key: 't1:1:0', tool: 'fs.list', arguments: { path: 'logs' }, status: 'ok', result: 'a.log\nold.log', seconds: 0.01 }),
  ev('llm_call', { agent: 'main', step: 2, status: 'ok', usage: { input_tokens: 950 }, context_length: 32000 }),
  ev('tool_call', { call_key: 't1:2:0', tool: 'fs.delete', arguments: { path: 'old.log' }, status: 'requested' }),
  ev('approval_requested', { approval_id: 'ap1', tool: 'fs.delete', summary: 'Delete file: old.log' }),
  ev('approval_resolved', { approval_id: 'ap1', call_key: 't1:2:0', outcome: 'allowed', by: 'gateway' }),
  ev('tool_call', { call_key: 't1:2:0', tool: 'fs.delete', arguments: { path: 'old.log' }, status: 'running' }),
  ev('tool_call', { call_key: 't1:2:0', tool: 'fs.delete', arguments: { path: 'old.log' }, status: 'ok', result: 'deleted file old.log' }),
  ev('task_state', { state: 'completed', pause_state: 'none', summary: 'Deleted old.log.' }),
];

describe('task cards', () => {
  it('reads as a short story of what happened', () => {
    const task = buildTasks(flow).get('t1')!;
    expect(task.instruction).toBe('Delete old.log');
    expect(task.state).toBe('completed');
    expect(task.summary).toBe('Deleted old.log.');
    expect(task.lines.map((l) => l.text)).toEqual([
      'Delegated “Delete old.log”',
      'fs.list logs → 2 entries',
      'Asked: Delete file: old.log',
      'Approval: you allowed it',
      'fs.delete old.log → deleted file old.log',
      'Done',
    ]);
    expect(liveLine(task)).toBeNull();
  });

  it('shows a live line while working or waiting', () => {
    const waiting = buildTasks(flow.slice(0, 8).concat(ev('task_state', { state: 'input_required' }))).get('t1')!;
    expect(liveLine(waiting)?.text).toBe('Waiting for your approval…');
    const pausing = buildTasks([...flow.slice(0, 3), ev('task_state', { state: 'working', pause_state: 'pausing' })]).get('t1')!;
    expect(liveLine(pausing)?.text).toContain('then pausing');
  });

  it('keeps long arguments short and hides file contents', () => {
    expect(shortArgs({ path: 'a.txt', content: 'x'.repeat(500) })).toBe('a.txt');
    expect(shortArgs({ command: 'y'.repeat(100) }).length).toBe(60);
  });
});

describe('trace', () => {
  it('nests tool calls and approvals under their step', () => {
    const steps = buildTrace(flow);
    expect(steps.map((s) => s.no)).toEqual([1, 2]);
    expect(steps[0].tools[0]).toMatchObject({ tool: 'fs.list', status: 'ok', seconds: 0.01 });
    expect(steps[1].tools[0].approval).toMatchObject({ summary: 'Delete file: old.log', outcome: 'allowed', by: 'gateway' });
  });

  it('shows a tool allowed by an always rule', () => {
    const steps = buildTrace([
      ev('tool_call', { call_key: 't1:1:0', tool: 'shell', arguments: { command: 'dir' }, status: 'requested' }),
      ev('approval_resolved', { call_key: 't1:1:0', tool: 'shell', outcome: 'allowed', by: 'allow_always_rule' }),
      ev('tool_call', { call_key: 't1:1:0', tool: 'shell', arguments: { command: 'dir' }, status: 'ok', result: 'x' }),
    ]);
    expect(steps[0].tools[0].approval).toMatchObject({ outcome: 'allowed', by: 'allow_always_rule', answeredAt: null });
  });

  it('marks where compaction happened', () => {
    const steps = buildTrace([...flow.slice(0, 5), ev('compaction', { estimated_tokens_before: 9880, estimated_tokens_after: 1998 }), ...flow.slice(5)]);
    expect(steps[1].compactedBefore?.estimated_tokens_after).toBe(1998);
  });
});

describe('agent stats', () => {
  it('uses the latest successful call', () => {
    expect(agentStats(flow, 'main')).toEqual({ tokensPerSecond: null, contextLength: 32000, contextPercent: 3 });
    expect(agentStats(flow.slice(0, 3), 'main').tokensPerSecond).toBe(62);
    expect(agentStats(flow, 'voice').contextPercent).toBeNull();
  });
});
