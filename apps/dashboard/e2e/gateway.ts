/* A fake gateway for browser tests: REST routes and the live stream, with a record of writes. */

import type { Page, WebSocketRoute } from '@playwright/test';

const now = Date.now();
const iso = (secondsAgo: number) => new Date(now - secondsAgo * 1000).toISOString();

let pos = 0;
export function event(type: string, payload: Record<string, unknown>, over: Record<string, unknown> = {}) {
  pos += 1;
  return {
    kind: ['task_state', 'approval_requested', 'approval_resolved', 'notification'].includes(type) ? type : 'timeline_event',
    pos,
    event: { event_id: `e${pos}`, source: 'main', seq: pos, ts: iso(60 - pos), project_id: 'p1', chat_id: 'c1', task_id: 't1', type, payload, ...over },
  };
}

export const timeline = [
  event('user_message', { text: 'Please delete old.log', client_message_id: 'm1' }, { source: 'voice', task_id: null }),
  event('delegation', { instruction: 'Delete old.log' }),
  event('assistant_message', { text: 'On it.', client_message_id: 'm1' }, { source: 'voice', task_id: null }),
  event('task_state', { state: 'working', pause_state: 'none' }),
  event('llm_call', { agent: 'main', step: 1, status: 'ok', usage: { input_tokens: 900, output_tokens: 30 }, context_length: 32000, tokens_per_second: 80, request_body: { model: 'google/gemma' }, response_body: 'data: {}' }),
  event('tool_call', { call_key: 't1:1:0', tool: 'fs.delete', arguments: { path: 'old.log' }, status: 'requested' }),
  event('approval_requested', { approval_id: 'ap1', tool: 'fs.delete', summary: 'Delete file: old.log' }),
  event('task_state', { state: 'input_required', pause_state: 'none' }),
];

const approval = {
  approval_id: 'ap1', task_id: 't1', chat_id: 'c1', tool: 'fs.delete', summary: 'Delete file: old.log',
  arguments: { path: 'old.log' }, expires_at: new Date(now + 290_000).toISOString(), status: 'pending', requested_at: iso(30),
};

const llm = (model: string) => ({
  provider: 'lmstudio', base_url: 'http://127.0.0.1:1234', model, api_key_set: true, api_key_source: 'LMSTUDIO_API_TOKEN',
  sends_data_off_pc: false, supports_lifecycle: true, reachable: true, loaded: { context_length: 32000, adopted: true, load_seconds: null },
  load: { context_length: 32000, flash_attention: true, offload_kv_cache_to_gpu: null, eval_batch_size: null, num_experts: null },
});

const sample = {
  ts: new Date(now).toISOString(), cpu_percent: 12, ram_used_mb: 20_000, ram_total_mb: 32_768, net_rx_bytes_per_s: 2048, net_tx_bytes_per_s: 512,
  gpus: [{ index: 0, name: 'NVIDIA GeForce RTX 3080 Ti', vram_used_mb: 9000, vram_total_mb: 12_288, util_percent: 30 }],
  services: [
    { name: 'gateway', up: true, latency_ms: 1.2, metrics: { queued_messages: 0 } },
    { name: 'voice_agent', up: true, latency_ms: 2.5, metrics: { llm_tokens_per_second: 70, context_length: 64000, llm_input_tokens: 500 } },
    { name: 'main_agent', up: true, latency_ms: 3.1, metrics: { llm_tokens_per_second: 80, keeping_awake: true, outbox_backlog: 0 } },
  ],
};

/** One second of a 440 Hz tone as 16-bit mono WAV, standing in for a spoken reply. */
function toneWav(): Uint8Array {
  const rate = 8000;
  const bytes = new Uint8Array(44 + rate * 2);
  const view = new DataView(bytes.buffer);
  const ascii = (at: number, text: string) => [...text].forEach((ch, k) => view.setUint8(at + k, ch.charCodeAt(0)));
  ascii(0, 'RIFF');
  view.setUint32(4, 36 + rate * 2, true);
  ascii(8, 'WAVEfmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, 'data');
  view.setUint32(40, rate * 2, true);
  for (let i = 0; i < rate; i++) view.setInt16(44 + i * 2, Math.round(Math.sin((i / rate) * 2 * Math.PI * 440) * 12000), true);
  return bytes;
}

/** Playwright wants a Node Buffer for binary bodies; this project has no Node typings, so reach it at run time. */
const nodeBuffer = (bytes: Uint8Array) => (globalThis as unknown as { Buffer: { from(b: Uint8Array): never } }).Buffer.from(bytes);

export interface Fake {
  /** Sizes of recordings sent for transcription. */
  recordings: number[];
  /** Texts sent to be read aloud. */
  spoken: string[];
  writes: { method: string; path: string; body: unknown }[];
  stream: () => WebSocketRoute | null;
  resolved: boolean;
  /** Chats deleted during the test: the gateway stops listing them. */
  deleted: string[];
}

export async function fakeGateway(page: Page): Promise<Fake> {
  const fake: Fake = { recordings: [], spoken: [], writes: [], stream: () => socket, resolved: false, deleted: [] };
  let socket: WebSocketRoute | null = null;

  const routes: Record<string, () => unknown> = {
    'GET /v1/status': () => ({ main_agent: true, voice_agent: true, llm_endpoint: true, queued_messages: 0, banners: [], stream_pos: pos }),
    'GET /v1/projects': () => ({ projects: [{ project_id: 'p1', name: 'Demo', folder: 'C:\\Demo', created_at: iso(86_400) }] }),
    'GET /v1/projects/p1/chats': () => ({
      chats: [{ chat_id: 'c1', title: 'Clean up logs', created_at: iso(3600), last_activity: iso(30) }].filter((chat) => !fake.deleted.includes(chat.chat_id)),
    }),
    'GET /v1/chats/c1/messages': () => ({
      messages: [
        { id: 1, pos: 1, role: 'user', text: 'Please delete old.log', created_at: iso(59), client_message_id: 'm1' },
        { id: 2, pos: 3, role: 'assistant', text: 'On it.', created_at: iso(57), client_message_id: 'm1' },
      ],
      pending: [],
    }),
    'GET /v1/chats/c1/timeline': () => ({ events: timeline }),
    'GET /v1/chats/c1/tasks': () => ({ tasks: [task()] }),
    'GET /v1/tasks': () => ({ tasks: [{ ...task(), chat_title: 'Clean up logs', project_name: 'Demo' }] }),
    'GET /v1/tasks/t1': () => ({ task: task(), trace: timeline }),
    'GET /v1/approvals': () => ({ approvals: fake.resolved ? [] : [approval] }),
    'GET /v1/notifications': () => ({ notifications: [] }),
    'GET /v1/agents/main/llm': () => llm('google/gemma-4-26b'),
    'GET /v1/agents/voice/llm': () => llm('google/gemma-4-e2b'),
    'GET /v1/agents/main/prompt': () => ({ version: 2, text: 'You are Thursday.' }),
    'GET /v1/agents/voice/prompt': () => ({ version: 0, text: 'Default voice prompt.' }),
    'GET /v1/agents/main/prompt/versions': () => ({ versions: [{ version: 2, created_at: iso(600), text: 'You are Thursday.' }, { version: 1, created_at: iso(86_400), text: 'Old.' }], default: 'Default.' }),
    'GET /v1/agents/voice/prompt/versions': () => ({ versions: [], default: 'Default voice prompt.' }),
    'GET /v1/settings/general': () => ({ compaction_threshold_percent: 90, keep_awake_paused_minutes: 30, trace_retention_days: 30, metrics_retention_days: 7, main_agent_reachable: true }),
    'GET /v1/settings/backup': () => ({ folder: 'C:\\Backup', daily: true, keep_copies: 7, last_run: { folder: 'C:\\Backup\\thursday-backup-1', complete: true, created_at: iso(3600), services: { gateway: true, main_agent: true, voice_agent: true } } }),
    'GET /v1/devices': () => ({ devices: [{ device_id: 'dev-1', name: 'Pixel 9', created_at: iso(86_400), last_seen: iso(60) }] }),
    'GET /v1/tools': () => ({
      main_agent_reachable: true,
      rules: [{ chat_id: 'c1', chat_title: 'Clean up logs', tool: 'shell', created_at: iso(600) }],
      servers: [{ project_id: 'p1', project_name: 'Demo', alive: true, open_sessions: 1, idle_seconds: 120 }],
      catalog: [{ name: 'fs.delete', description: 'Delete', asks_first: true }, { name: 'fs.read', description: 'Read', asks_first: false }],
    }),
    'GET /v1/speech': () => ({ available: true, voices: ['af_heart'] }),
    'GET /v1/monitor': () => ({ latest: sample, history: [sample, sample], llm_calls: [{ ts: sample.ts, agent: 'main', tokens_per_second: 80, ttft_seconds: 0.4, input_tokens: 900, output_tokens: 30, context_length: 32000 }] }),
  };

  function task() {
    return {
      task_id: 't1', chat_id: 'c1', project_id: 'p1', state: fake.resolved ? 'completed' : 'input_required', pause_state: 'none',
      instruction: 'Delete old.log', summary: fake.resolved ? 'Deleted old.log.' : '', created_at: iso(58), updated_at: iso(1),
    };
  }

  await page.route('**/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    if (key === 'POST /v1/speech/transcribe') {
      fake.recordings.push(request.postDataBuffer()?.length ?? 0);
      return route.fulfill({ json: { text: 'List the files in logs', language: 'en', audio_seconds: 1, seconds: 0.1 } });
    }
    if (key === 'POST /v1/speech/speak') {
      fake.spoken.push(request.postDataJSON().text);
      return route.fulfill({ contentType: 'audio/wav', body: nodeBuffer(toneWav()) });
    }
    if (request.method() !== 'GET') {
      fake.writes.push({ method: request.method(), path: url.pathname, body: request.postDataJSON?.() ?? null });
      if (request.headers()['x-thursday-client'] !== 'dashboard') return route.fulfill({ status: 403 });
      if (key === 'POST /v1/approvals/ap1') fake.resolved = true;
      if (request.method() === 'DELETE' && url.pathname.startsWith('/v1/chats/')) fake.deleted.push(url.pathname.split('/').pop()!);
      return route.fulfill({ status: request.method() === 'DELETE' ? 202 : 200, json: { status: 'ok' } });
    }
    const handler = routes[key];
    return handler ? route.fulfill({ json: handler() }) : route.fulfill({ status: 404, json: { code: 'not_found', detail: key } });
  });

  await page.routeWebSocket(/\/v1\/stream/, (ws) => {
    socket = ws;
  });
  await page.routeWebSocket(/\/v1\/metrics\/stream/, (ws) => {
    ws.send(JSON.stringify({ kind: 'metrics', sample }));
  });
  return fake;
}
