/* A model call's request and response as labelled parts a person can read: who said what, the model's thinking,
   its answer, its tool calls and the token counts. Newer traces store the response as an object; older ones hold
   the raw token stream (cut at 20,000 characters), which is put together here from the pieces that survived. */

export interface Part {
  label: string;
  text: string;
  /** Shown in a fixed-width box (arguments, results); otherwise as running text. */
  code?: boolean;
}

type Json = Record<string, unknown>;
const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v);
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const ROLES: Record<string, string> = { system: 'System', developer: 'System', user: 'User', assistant: 'Assistant', tool: 'Tool result' };

/** Arguments arrive as a JSON string; show them indented, or as they are when they are not valid JSON (a cut call). */
function indented(value: unknown): string {
  if (typeof value !== 'string') return JSON.stringify(value ?? {}, null, 2);
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

/** Text of a message's content: a string, or a list of typed pieces of which the text ones are kept. */
function contentText(content: unknown): string {
  if (typeof content === 'string') return content;
  return list(content)
    .map((piece) => (isObject(piece) ? (typeof piece.text === 'string' ? piece.text : piece.type === 'input_audio' ? '[audio]' : piece.type === 'input_image' || piece.type === 'image_url' ? '[image]' : '') : ''))
    .filter(Boolean)
    .join('\n');
}

function itemParts(item: unknown): Part[] {
  if (!isObject(item)) return [];
  if (item.type === 'function_call') return [{ label: `Tool call · ${item.name ?? ''}`, text: indented(item.arguments), code: true }];
  if (item.type === 'function_call_output') return [{ label: 'Tool result', text: typeof item.output === 'string' ? item.output : indented(item.output), code: true }];
  if (item.type === 'reasoning') {
    const text = contentText(item.content) || contentText(item.summary);
    return text ? [{ label: 'Thinking', text }] : [];
  }
  const parts: Part[] = [];
  const role = String(item.role ?? 'assistant');
  if (typeof item.reasoning_content === 'string' && item.reasoning_content) parts.push({ label: 'Thinking', text: item.reasoning_content });
  const text = contentText(item.content);
  if (text) parts.push({ label: ROLES[role] ?? role, text, code: role === 'tool' });
  for (const call of list(item.tool_calls)) {
    const fn = isObject(call) && isObject(call.function) ? call.function : {};
    parts.push({ label: `Tool call · ${fn.name ?? ''}`, text: indented(fn.arguments), code: true });
  }
  return parts;
}

/** What was sent: the conversation in order, then the model, settings and tool names. Null when it is not a chat request. */
export function requestParts(body: unknown): Part[] | null {
  if (!isObject(body)) return null;
  const turns = Array.isArray(body.input) ? body.input : Array.isArray(body.messages) ? body.messages : typeof body.input === 'string' ? [{ role: 'user', content: body.input }] : null;
  if (!turns) return null;
  const parts: Part[] = [];
  if (typeof body.instructions === 'string' && body.instructions) parts.push({ label: 'System', text: body.instructions });
  for (const turn of turns) parts.push(...itemParts(turn));
  const settings = Object.entries(body)
    .filter(([key, value]) => !['input', 'messages', 'instructions', 'tools'].includes(key) && value !== null && typeof value !== 'object')
    .map(([key, value]) => `${key}: ${value}`);
  const tools = list(body.tools).map((tool) => (isObject(tool) ? String(tool.name ?? (isObject(tool.function) ? tool.function.name : '') ?? '') : '')).filter(Boolean);
  if (tools.length) settings.push(`tools: ${tools.join(', ')}`);
  if (settings.length) parts.push({ label: 'Settings', text: settings.join('\n') });
  return parts;
}

function usageText(usage: unknown): string {
  if (!isObject(usage)) return '';
  const input = usage.input_tokens ?? usage.prompt_tokens;
  const output = usage.output_tokens ?? usage.completion_tokens;
  return input == null && output == null ? '' : `${input ?? 0} in / ${output ?? 0} out`;
}

function objectParts(body: Json): Part[] | null {
  let parts: Part[];
  if (Array.isArray(body.output)) parts = body.output.flatMap(itemParts);
  else if (Array.isArray(body.choices)) parts = body.choices.flatMap((choice) => (isObject(choice) ? itemParts(choice.message) : []));
  else if (isObject(body.error) || typeof body.error === 'string') return [{ label: 'Error', text: isObject(body.error) ? String(body.error.message ?? JSON.stringify(body.error)) : String(body.error) }];
  else return null;
  if (isObject(body.error)) parts.push({ label: 'Error', text: String(body.error.message ?? JSON.stringify(body.error)) });
  if (body.status === 'incomplete') parts.push({ label: 'Cut short', text: 'The response ended before it was complete; this is what arrived.' });
  const usage = usageText(body.usage);
  if (usage) parts.push({ label: 'Tokens', text: usage });
  return parts;
}

/** The JSON objects of a server-sent-event stream. Lines that are not whole JSON (a cut line, `[DONE]`) are skipped. */
function streamEvents(text: string): Json[] {
  const found: Json[] = [];
  for (const line of text.split('\n')) {
    if (!line.startsWith('data:')) continue;
    try {
      const value: unknown = JSON.parse(line.slice(5).trim());
      if (isObject(value)) found.push(value);
    } catch {
      /* a cut or non-JSON line */
    }
  }
  return found;
}

function streamParts(text: string): Part[] | null {
  const events = streamEvents(text);
  if (!events.length) return null;
  const final = [...events].reverse().find((e) => ['response.completed', 'response.incomplete', 'response.failed'].includes(String(e.type)) && isObject(e.response));
  if (final) return objectParts(final.response as Json);
  // No final event survived: join the pieces of each output item, in order.
  const items = new Map<number, { label: string; text: string; code: boolean }>();
  const at = (index: number) => items.get(index) ?? items.set(index, { label: 'Assistant', text: '', code: false }).get(index)!;
  for (const event of events) {
    const type = String(event.type ?? '');
    for (const choice of list(event.choices)) {
      const delta = isObject(choice) && isObject(choice.delta) ? choice.delta : {};
      if (typeof delta.reasoning_content === 'string') (at(-1).label = 'Thinking'), (at(-1).text += delta.reasoning_content);
      if (typeof delta.content === 'string') at(0).text += delta.content;
      for (const piece of list(delta.tool_calls)) {
        if (!isObject(piece)) continue;
        const call = at(1 + Number(piece.index ?? 0));
        const fn = isObject(piece.function) ? piece.function : {};
        if (fn.name) call.label = `Tool call · ${fn.name}`;
        call.code = true;
        call.text += typeof fn.arguments === 'string' ? fn.arguments : '';
      }
    }
    const index = typeof event.output_index === 'number' ? event.output_index : null;
    if (index === null) continue;
    if (type === 'response.output_item.added' && isObject(event.item)) {
      const item = at(index);
      if (event.item.type === 'reasoning') item.label = 'Thinking';
      if (event.item.type === 'function_call') (item.label = `Tool call · ${event.item.name ?? ''}`), (item.code = true);
    } else if (type.endsWith('.delta') && typeof event.delta === 'string') {
      at(index).text += event.delta;
    }
  }
  const parts: Part[] = [...items.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, item]) => ({ label: item.label, text: item.code ? indented(item.text) : item.text, code: item.code }))
    .filter((part) => part.text);
  parts.push({ label: 'Cut short', text: 'Only the start of this response was kept; the rest of the stream was not stored.' });
  return parts;
}

/** What came back. Null when the body is not a model response this screen understands (then the raw text is shown). */
export function responseParts(body: unknown): Part[] | null {
  if (isObject(body)) return objectParts(body);
  if (typeof body !== 'string') return null;
  if (body.includes('data:')) return streamParts(body);
  try {
    const parsed: unknown = JSON.parse(body);
    return isObject(parsed) ? objectParts(parsed) : null;
  } catch {
    return null;
  }
}

/** The body exactly as stored, indented when it is JSON. */
export function rawText(value: unknown): string {
  if (value == null) return 'Not captured.';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  const text = String(value);
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}
