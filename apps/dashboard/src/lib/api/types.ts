/* Shapes returned by the gateway (/v1). They mirror docs/CONTRACTS.md and the gateway's routes. */

export interface Project {
  project_id: string;
  name: string;
  folder: string;
  created_at: string;
}

export interface Chat {
  chat_id: string;
  title: string;
  created_at: string;
  last_activity: string;
  project_id?: string;
}

export interface ChatMessage {
  id: number;
  pos: number | null;
  role: 'user' | 'assistant';
  text: string;
  created_at: string;
  client_message_id: string | null;
}

export interface PendingMessage {
  client_message_id: string;
  text: string;
  status: 'queued' | 'delivered' | 'failed';
  error: string;
}

export type EventType =
  | 'user_message'
  | 'assistant_message'
  | 'delegation'
  | 'llm_call'
  | 'tool_call'
  | 'approval_requested'
  | 'approval_resolved'
  | 'task_state'
  | 'compaction'
  | 'model_load'
  | 'notification'
  | 'error';

export interface EventEnvelope {
  event_id: string;
  source: 'voice' | 'main' | 'collector' | 'tool';
  seq: number;
  ts: string;
  project_id: string | null;
  chat_id: string | null;
  task_id: string | null;
  type: EventType;
  payload: Record<string, any>;
}

export interface TimelineMessage {
  kind: 'timeline_event' | 'task_state' | 'approval_requested' | 'approval_resolved' | 'notification';
  pos: number;
  event: EventEnvelope;
}

export type StreamMessage =
  | TimelineMessage
  | { kind: 'chat_delta'; chat_id: string; client_message_id: string; text: string }
  | { kind: 'outgoing'; chat_id: string; client_message_id: string; status: string; text?: string; error?: string }
  | { kind: 'status_banner'; banners: Banner[] }
  | { kind: 'catalog_changed' };

export interface Banner {
  code: string;
  text: string;
}

export interface TaskRow {
  task_id: string;
  chat_id: string | null;
  project_id: string | null;
  state: string;
  pause_state: 'none' | 'pausing' | 'paused';
  instruction: string;
  summary: string;
  created_at: string;
  updated_at: string;
  chat_title?: string | null;
  project_name?: string | null;
}

export interface Approval {
  approval_id: string;
  task_id: string;
  chat_id: string;
  tool: string;
  summary: string;
  arguments: Record<string, unknown>;
  expires_at: string;
  status: string;
  requested_at: string;
}

export interface Notification {
  id: number;
  kind: string;
  title: string;
  body: string;
  chat_id: string | null;
  task_id: string | null;
  created_at: string;
  read: number;
}

export interface Status {
  main_agent: boolean;
  voice_agent: boolean;
  llm_endpoint: boolean;
  queued_messages: number;
  banners: Banner[];
  stream_pos: number;
}

export interface GpuSample {
  index: number;
  name: string;
  vram_used_mb: number;
  vram_total_mb: number;
  util_percent: number | null;
}

export interface ServiceSample {
  name: string;
  up: boolean;
  latency_ms: number | null;
  metrics: Record<string, number | string | boolean | null>;
}

export interface MetricsSample {
  ts: string;
  cpu_percent: number;
  ram_used_mb: number;
  ram_total_mb: number;
  net_rx_bytes_per_s: number;
  net_tx_bytes_per_s: number;
  gpus: GpuSample[];
  services: ServiceSample[];
}

/** One successful model call, from the gateway's event history. */
export interface LlmCall {
  ts: string;
  agent: 'main' | 'voice';
  tokens_per_second: number | null;
  ttft_seconds: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  context_length: number | null;
}

export interface LoadParams {
  context_length: number | null;
  flash_attention: boolean | null;
  offload_kv_cache_to_gpu: boolean | null;
  eval_batch_size: number | null;
  num_experts: number | null;
}

export interface LlmSettings {
  provider: 'lmstudio' | 'openai_compatible';
  base_url: string;
  model: string;
  load: LoadParams;
  api_key_set: boolean;
  api_key_source: string | null;
  sends_data_off_pc: boolean;
  supports_lifecycle: boolean;
  loaded: { context_length: number | null; adopted: boolean; load_seconds: number | null } | null;
  reachable?: boolean;
}

export interface PromptVersion {
  version: number;
  created_at: string;
  text: string;
}

export interface GeneralSettings {
  compaction_threshold_percent?: number;
  keep_awake_paused_minutes?: number;
  trace_retention_days: number;
  metrics_retention_days: number;
  main_agent_reachable: boolean;
}

export interface BackupSettings {
  folder: string;
  daily: boolean;
  keep_copies: number;
  last_run?: { folder: string; complete: boolean; created_at: string; services: Record<string, boolean> } | null;
}

export interface ToolsOverview {
  main_agent_reachable: boolean;
  rules: { chat_id: string; chat_title: string; tool: string; created_at: string }[];
  servers: { project_id: string; project_name: string; alive: boolean; open_sessions?: number; idle_seconds?: number; tools?: number }[];
  catalog: { name: string; description: string; asks_first: boolean }[];
}

export type Agent = 'main' | 'voice';

export interface Device {
  device_id: string;
  name: string;
  created_at: string;
  last_seen: string | null;
}

export interface PairingCode {
  code: string;
  expires_at: string;
  address: string | null;
  pairing_uri: string | null;
}
