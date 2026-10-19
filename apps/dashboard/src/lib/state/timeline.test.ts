import { describe, expect, it } from 'vitest';
import type { EventEnvelope, EventType } from '../api/types';
import { agentStats, buildTasks, buildTrace, cardPosition, contextText, liveLine, shortArgs, taskStarts } from './timeline';

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
      'fs.delete old.log → deleted file old.log',
      'Asked: Delete file: old.log',
      'Approval: you allowed it',
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

  it('shows a tool call the moment it is requested, purple, and settles it green or red when it ends', () => {
    const request = ev('tool_call', { call_key: 'k1', tool: 'fs.read', arguments: { path: 'a.txt' }, status: 'requested' });
    const lines = (...events: EventEnvelope[]) => buildTasks([ev('task_state', { state: 'working' }), ...events]).get('t1')!.lines;
    expect(lines(request)).toMatchObject([{ text: 'fs.read a.txt', tone: 'run' }]);
    const worked = ev('tool_call', { call_key: 'k1', tool: 'fs.read', arguments: { path: 'a.txt' }, status: 'ok', result: 'hello' });
    expect(lines(request, worked)).toMatchObject([{ text: 'fs.read a.txt → hello', tone: 'ok' }]);
    const failed = ev('tool_call', { call_key: 'k1', tool: 'fs.read', arguments: { path: 'a.txt' }, status: 'error', result: 'no such file' });
    expect(lines(request, failed)).toMatchObject([{ text: 'fs.read a.txt → no such file', tone: 'bad' }]);
    const unknown = ev('tool_call', { call_key: 'k1', tool: 'fs.read', arguments: { path: 'a.txt' }, status: 'unknown' });
    expect(lines(request, unknown)).toMatchObject([{ tone: 'warn' }]);
  });

  it('keeps one line per call, in the order the calls were requested', () => {
    const call = (key: string, status: string, extra = {}) => ev('tool_call', { call_key: key, tool: 'fs.read', arguments: { path: key }, status, ...extra });
    const task = buildTasks([
      ev('task_state', { state: 'working' }),
      call('a', 'requested'), call('b', 'requested'),
      call('a', 'running'), call('b', 'ok', { result: 'B' }), call('a', 'ok', { result: 'A' }),
    ]).get('t1')!;
    expect(task.lines.map((l) => l.text)).toEqual(['fs.read a → A', 'fs.read b → B']);
  });

  it('still shows a result that arrives without its request (an older trace)', () => {
    const task = buildTasks([ev('tool_call', { call_key: 'z', tool: 'fs.read', arguments: { path: 'z' }, status: 'ok', result: 'Z' })]).get('t1')!;
    expect(task.lines).toMatchObject([{ text: 'fs.read z → Z', tone: 'ok' }]);
  });

  it('does not leave a call pulsing once the task has ended', () => {
    const task = buildTasks([
      ev('tool_call', { call_key: 'k', tool: 'shell', arguments: { command: 'sleep' }, status: 'requested' }),
      ev('task_state', { state: 'canceled' }),
    ]).get('t1')!;
    expect(task.lines[0]).toMatchObject({ text: 'shell sleep → did not finish', tone: 'warn' });
  });

  it('keeps long arguments short and hides file contents', () => {
    expect(shortArgs({ path: 'a.txt', content: 'x'.repeat(500) })).toBe('a.txt');
    expect(shortArgs({ command: 'y'.repeat(100) }).length).toBe(60);
  });
});

describe('where a task card sits', () => {
  const at = (pos: number, type: EventType, payload: Record<string, any>, over: Partial<EventEnvelope> = {}) => ({ pos, event: ev(type, payload, over) });
  const messages = [{ pos: 1, role: 'user' }, { pos: 9, role: 'assistant' }];

  it('goes under the reply that announced it when you talked to the voice agent', () => {
    const events = [at(2, 'delegation', { instruction: 'x' }), at(3, 'task_state', { state: 'working' })];
    const { first, direct } = taskStarts(events);
    expect(cardPosition(first.get('t1')!, direct.get('t1'), messages)).toBe(9.5);
  });

  it('goes right after your message when you sent it straight to the main agent, even though the main agent announced it first', () => {
    // The main agent's events arrive before the voice agent publishes your message and its own delegation.
    const events = [
      at(2, 'delegation', { instruction: 'hii' }),
      at(3, 'task_state', { state: 'working' }),
      at(5, 'delegation', { instruction: 'hii', by: 'direct' }, { source: 'voice' }),
    ];
    const { first, direct } = taskStarts(events);
    expect(first.get('t1')).toBe(2);
    const direct_messages = [{ pos: 4, role: 'user' }]; // your message, stored just before the voice agent's delegation
    expect(cardPosition(first.get('t1')!, direct.get('t1'), direct_messages)).toBe(5);
    expect(cardPosition(first.get('t1')!, direct.get('t1'), direct_messages)).toBeGreaterThan(4);
  });

  it('stays under your message when the voice agent reports the result later', () => {
    const events = [at(2, 'delegation', {}), at(5, 'delegation', { by: 'direct' }, { source: 'voice' })];
    const { first, direct } = taskStarts(events);
    const thread = [{ pos: 4, role: 'user' }, { pos: 40, role: 'assistant' }];
    expect(cardPosition(first.get('t1')!, direct.get('t1'), thread)).toBe(5);
  });
});

describe('trace', () => {
  it('keeps each reasoning phase before its tool calls and leaves the final answer last', () => {
    const events = [
      ev('llm_call', { agent: 'main', step: 1, status: 'ok', text: 'First I will inspect the folder.' }),
      ev('tool_call', { call_key: 't1:1:0', tool: 'fs.list', arguments: { path: 'logs' }, status: 'requested' }),
      ev('tool_call', { call_key: 't1:1:0', tool: 'fs.list', arguments: { path: 'logs' }, status: 'ok', result: 'old.log' }),
      ev('llm_call', { agent: 'main', step: 2, status: 'ok', text: 'I found the old file, so I will remove it.' }),
      ev('tool_call', { call_key: 't1:2:0', tool: 'fs.delete', arguments: { path: 'old.log' }, status: 'ok', result: 'deleted' }),
      ev('llm_call', { agent: 'main', step: 3, status: 'ok', text: 'The old file was deleted.' }),
    ];

    expect(buildTrace(events).map((step) => ({ text: step.llm?.text, tools: step.tools.map((tool) => tool.tool) }))).toEqual([
      { text: 'First I will inspect the folder.', tools: ['fs.list'] },
      { text: 'I found the old file, so I will remove it.', tools: ['fs.delete'] },
      { text: 'The old file was deleted.', tools: [] },
    ]);
  });

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
    expect(agentStats(flow, 'main')).toMatchObject({ tokensPerSecond: null, contextLength: 32000 });
    expect(agentStats(flow, 'main').contextTokens).toBeGreaterThan(0);
    expect(agentStats(flow.slice(0, 3), 'main').tokensPerSecond).toBe(62);
    expect(agentStats(flow, 'voice').contextTokens).toBeNull();
  });

  it('words the context as tokens in use and the window', () => {
    expect(contextText(4412, 16384)).toBe('4412/16384');
    expect(contextText(null, 16384), 'loaded, not asked anything in this chat yet').toBe('–/16384');
    expect(contextText(900, null), 'an endpoint that does not report its window').toBe('900 tokens');
    expect(contextText(null, null)).toBe('');
  });
});
