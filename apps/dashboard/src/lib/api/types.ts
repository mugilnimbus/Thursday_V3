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
  /** Every message in this chat goes straight to the main agent (set on the PC, so every device agrees). */
  direct?: boolean;
}

export interface ChatMessage {
  id: number;
  pos: number | null;
  role: 'user' | 'assistant';
  text: string;
  created_at: string;
  client_message_id: string | null;
  /** A user message that was sent straight to the main agent. */
  direct?: boolean;
}

export interface PendingMessage {
  client_message_id: string;
  text: string;
  status: 'queued' | 'delivered' | 'failed';
  error: string;
  direct?: boolean;
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
  | { kind: 'outgoing'; chat_id: string; client_message_id: string; status: string; text?: string; error?: string; direct?: boolean }
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

export interface StorageSample {
  name: string;
  bytes: number;
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
  /** How much disk each service's stored data uses; absent from samples made before this was measured. */
  storage?: StorageSample[];
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
  /** Built-in llama.cpp only: layers whose expert weights stay in system RAM. */
  moe_cpu_layers: number | null;
  /** Built-in llama.cpp only: 'all' or how many layers go on the graphics cards; null lets llama.cpp fit what it can. */
  gpu_layers: string | null;
  /** Built-in llama.cpp only: share of the model per card, like '3,1'; null splits by free memory. */
  gpu_split: string | null;
  /** Built-in llama.cpp only: the card filled first ('0', or an order like '1,0'); null spreads the model over the cards. */
  gpu_priority: string | null;
}

export interface InferenceParams {
  temperature: number | null;
  top_p: number | null;
  max_output_tokens: number | null;
  /** 'default', or for llama.cpp 'off' | 'on', or for Responses endpoints an effort (none … xhigh). */
  reasoning: string;
}

export interface ModelEntry {
  key: string;
  loaded: boolean;
  max_context_length: number | null;
  trained_for_tool_use: boolean | null;
  size_bytes: number | null;
  /** A multimodal projector found beside the model file (built-in llama.cpp). */
  projector: string | null;
}

export interface LlmSettings {
  provider: 'lmstudio' | 'openai_compatible' | 'llamacpp';
  base_url: string;
  model: string;
  load: LoadParams;
  inference: InferenceParams;
  /** Built-in llama.cpp: whether `thursday setup` has installed it, the models folder, and the GPU to use. */
  llamacpp: {
    installed: boolean;
    models_dir: string;
    gpu: number | null;
    /** The graphics cards llama.cpp sees, once it has been asked. */
    devices?: { index: number; name: string; total_mb: number }[];
    /** How the loaded model was placed on the cards when they are filled in order, in words. */
    placement?: string;
  };
  /** Tokens of conversation sent before the older part is shortened; null leaves it to the agent. */
  compact_at_tokens: number | null;
  /** The model and address each other provider used last, brought back when the agent switches to it. */
  remembered?: Partial<Record<LlmSettings['provider'], { model?: string; base_url?: string }>>;
  /** A loaded model unused for this many minutes is unloaded; 0 keeps it loaded. */
  idle_unload_minutes: number;
  /** Seconds since the loaded model was last used; null when nothing is loaded. */
  idle_seconds: number | null;
  hears_audio: boolean;
  api_key_set: boolean;
  /** A key is stored, but for another address: it is not sent until it is typed again. */
  api_key_held_back?: boolean;
  sends_data_off_pc: boolean;
  supports_lifecycle: boolean;
  loaded: { context_length: number | null; adopted: boolean; load_seconds: number | null } | null;
  reachable?: boolean;
}

/** The settings an agent card can change; a null clears the saved value, so the .env value applies again. */
export interface LlmChange {
  provider?: LlmSettings['provider'];
  base_url?: string;
  model?: string;
  load?: Partial<LoadParams>;
  inference?: Partial<InferenceParams>;
  models_dir?: string | null;
  gpu?: number | null;
  compact_at_tokens?: number | null;
  idle_unload_minutes?: number | null;
}

export interface PromptVersion {
  version: number;
  created_at: string;
  text: string;
}

export interface GeneralSettings {
  compaction_threshold_percent?: number;
  keep_awake_paused_minutes?: number;
  /** Days that working data is kept; 0 keeps it until it is deleted by hand. */
  data_retention_days: number;
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
