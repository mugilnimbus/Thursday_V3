import { describe, expect, it } from 'vitest';
import { rawText, requestParts, responseParts } from './traceBody';

const sse = (...events: object[]) => events.map((e) => `event: ${(e as { type?: string }).type ?? 'message'}\ndata: ${JSON.stringify(e)}\n\n`).join('');

describe('a model call as readable parts', () => {
  it('lays a request out as the conversation, then the settings and tool names', () => {
    const parts = requestParts({
      model: 'google/gemma',
      stream: true,
      input: [
        { role: 'system', content: 'You are the main agent.\nWork step by step.' },
        { role: 'user', content: 'Clean up the logs' },
        { type: 'reasoning', content: [{ type: 'reasoning_text', text: 'List first.' }] },
        { type: 'function_call', name: 'fs_list', arguments: '{"path":"."}', call_id: 'c1' },
        { type: 'function_call_output', call_id: 'c1', output: 'a.log\nb.log' },
        { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Two logs found.' }] },
      ],
      tools: [{ type: 'function', name: 'fs_list' }, { type: 'function', name: 'fs_delete' }],
    });
    expect(parts?.map((p) => p.label)).toEqual(['System', 'User', 'Thinking', 'Tool call · fs_list', 'Tool result', 'Assistant', 'Settings']);
    expect(parts?.[0].text).toBe('You are the main agent.\nWork step by step.');
    expect(parts?.[3]).toEqual({ label: 'Tool call · fs_list', text: '{\n  "path": "."\n}', code: true });
    expect(parts?.[4].text).toBe('a.log\nb.log');
    expect(parts?.at(-1)?.text).toBe('model: google/gemma\nstream: true\ntools: fs_list, fs_delete');
  });

  it('reads a chat-completions request too, and gives up on anything that is not a chat', () => {
    const parts = requestParts({
      model: 'gemma.gguf',
      messages: [
        { role: 'user', content: [{ type: 'text', text: 'What is this?' }, { type: 'input_audio', input_audio: {} }] },
        { role: 'assistant', content: '', tool_calls: [{ function: { name: 'fs_read', arguments: '{"path":"a"}' } }] },
        { role: 'tool', content: 'hello' },
      ],
    });
    expect(parts?.map((p) => p.label)).toEqual(['User', 'Tool call · fs_read', 'Tool result', 'Settings']);
    expect(parts?.[0].text).toBe('What is this?\n[audio]');
    expect(requestParts({ anything: 1 })).toBeNull();
    expect(requestParts('text')).toBeNull();
  });

  it('shows a stored response as thinking, answer, tool calls and tokens', () => {
    const parts = responseParts({
      status: 'completed',
      output: [
        { type: 'reasoning', content: [{ type: 'reasoning_text', text: 'Read the file.' }] },
        { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Reading it now.' }] },
        { type: 'function_call', name: 'fs_read', arguments: '{"path":"main.py"}' },
      ],
      usage: { input_tokens: 3000, output_tokens: 240 },
    });
    expect(parts).toEqual([
      { label: 'Thinking', text: 'Read the file.' },
      { label: 'Assistant', text: 'Reading it now.', code: false },
      { label: 'Tool call · fs_read', text: '{\n  "path": "main.py"\n}', code: true },
      { label: 'Tokens', text: '3000 in / 240 out' },
    ]);
  });

  it('reads a chat completion, and names a response that ended early', () => {
    const parts = responseParts({
      choices: [{ message: { role: 'assistant', reasoning_content: 'hm', content: 'Hello', tool_calls: [{ function: { name: 'fs_read', arguments: '{"path":"a"}' } }] } }],
      usage: { prompt_tokens: 5, completion_tokens: 3 },
    });
    expect(parts?.map((p) => p.label)).toEqual(['Thinking', 'Assistant', 'Tool call · fs_read', 'Tokens']);
    expect(parts?.at(-1)?.text).toBe('5 in / 3 out');
    const cut = responseParts({ status: 'incomplete', output: [{ type: 'reasoning', content: [{ text: 'So' }] }], usage: null });
    expect(cut?.map((p) => p.label)).toEqual(['Thinking', 'Cut short']);
  });

  it('puts an old raw token stream back together, using the final event when it survived', () => {
    const response = { status: 'completed', output: [{ type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Hi there' }] }], usage: { input_tokens: 9, output_tokens: 2 } };
    const whole = sse(
      { type: 'response.created', response: { output: [] } },
      { type: 'response.output_text.delta', output_index: 0, delta: 'Hi ' },
      { type: 'response.completed', response },
    );
    expect(responseParts(whole)?.map((p) => `${p.label}: ${p.text}`)).toEqual(['Assistant: Hi there', 'Tokens: 9 in / 2 out']);
  });

  it('keeps what survived of a stream that was cut before its end', () => {
    const cut =
      sse(
        { type: 'response.created', response: { output: [], tools: [{ name: 'fs_read' }] } },
        { type: 'response.output_item.added', output_index: 0, item: { type: 'reasoning' } },
        { type: 'response.reasoning_text.delta', output_index: 0, delta: 'The user wants ' },
        { type: 'response.reasoning_text.delta', output_index: 0, delta: 'a change.' },
        { type: 'response.output_item.added', output_index: 1, item: { type: 'function_call', name: 'fs_read' } },
        { type: 'response.function_call_arguments.delta', output_index: 1, delta: '{"path":"a.py"}' },
      ) + 'event: response.reasoning_text.delta\ndata: {...[truncated 69043 characters]';
    expect(responseParts(cut)).toEqual([
      { label: 'Thinking', text: 'The user wants a change.', code: false },
      { label: 'Tool call · fs_read', text: '{\n  "path": "a.py"\n}', code: true },
      { label: 'Cut short', text: 'Only the start of this response was kept; the rest of the stream was not stored.' },
    ]);
  });

  it('joins chat-completion chunks, and leaves other bodies to the raw view', () => {
    const chunks =
      sse(
        { choices: [{ delta: { reasoning_content: 'hm ' } }] },
        { choices: [{ delta: { content: 'Hel' } }] },
        { choices: [{ delta: { content: 'lo' } }] },
        { choices: [{ delta: { tool_calls: [{ index: 0, function: { name: 'fs_read', arguments: '{"pa' } }] } }] },
        { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: 'th":"a"}' } }] } }] },
      ) + 'data: [DONE]\n\n';
    expect(responseParts(chunks)?.slice(0, 3)).toEqual([
      { label: 'Thinking', text: 'hm ', code: false },
      { label: 'Assistant', text: 'Hello', code: false },
      { label: 'Tool call · fs_read', text: '{\n  "path": "a"\n}', code: true },
    ]);
    expect(responseParts('Bad gateway')).toBeNull();
    expect(responseParts('{"error":{"message":"model not loaded"}}')).toEqual([{ label: 'Error', text: 'model not loaded' }]);
    expect(rawText(null)).toBe('Not captured.');
    expect(rawText('{"a":1}')).toBe('{\n  "a": 1\n}');
  });
});
