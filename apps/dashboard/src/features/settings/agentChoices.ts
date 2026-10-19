/* What each LLM setting can be set to, per provider, and how the screen words it.
   Every setting is a list of the values the provider accepts, and the first entry says what its default is. */

import type { LlmSettings } from '../../lib/api/types';

export type Provider = LlmSettings['provider'];

/** What each provider can do, from its own documentation. The screen shows only what applies. */
export const PROVIDERS = {
  lmstudio: { label: 'LM Studio', lifecycle: true, endpoint: true, folders: false },
  llamacpp: { label: 'Built-in llama.cpp', lifecycle: true, endpoint: false, folders: true },
  openai_compatible: { label: 'OpenAI-compatible', lifecycle: false, endpoint: true, folders: false },
} as const;

export interface Choice {
  value: string;
  label: string;
}

export type ChoiceField =
  | 'context_length'
  | 'eval_batch_size'
  | 'moe_cpu_layers'
  | 'gpu_layers'
  | 'gpu_split'
  | 'gpu_priority'
  | 'idle_unload_minutes'
  | 'flash_attention'
  | 'offload_kv_cache_to_gpu'
  | 'gpu'
  | 'temperature'
  | 'top_p'
  | 'max_output_tokens'
  | 'reasoning';

const CONTEXT_SIZES = [2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576];
const BATCH_SIZES = [64, 128, 256, 512, 1024, 2048, 4096];
const MOE_LAYERS = [1, 2, 4, 8, 12, 16, 24, 32, 48, 64];
const GPU_LAYERS = [8, 16, 24, 32, 48, 64];
const GPU_SPLITS: [string, string][] = [['1,1', 'Even (1 : 1)'], ['2,1', '2 : 1'], ['1,2', '1 : 2'], ['3,1', '3 : 1'], ['1,3', '1 : 3']];
const IDLE_MINUTES = [1, 2, 5, 10, 15, 30, 60];
const TEMPERATURES = Array.from({ length: 21 }, (_, i) => (i / 10).toFixed(1).replace(/\.0$/, ''));
const TOP_PS = ['0.1', '0.2', '0.3', '0.4', '0.5', '0.6', '0.7', '0.8', '0.9', '0.95', '1'];
const TOKEN_LIMITS = [256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536];
const EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'];

/** What the engine does when nothing is chosen. LM Studio keeps its own per-model settings, which it does not report. */
const DEFAULTS: Record<Provider, Partial<Record<ChoiceField, string>>> = {
  llamacpp: {
    context_length: '8,192 tokens',
    eval_batch_size: '2048',
    moe_cpu_layers: 'None',
    gpu_layers: 'As many as fit',
    gpu_split: 'By free memory',
    gpu_priority: 'Spread over cards',
    flash_attention: 'Automatic',
    offload_kv_cache_to_gpu: 'On the GPU',
    gpu: 'All cards',
    temperature: '0.8',
    top_p: '0.95',
    max_output_tokens: 'No limit',
    reasoning: "Model's own",
  },
  lmstudio: {
    context_length: "LM Studio's",
    eval_batch_size: "LM Studio's",
    flash_attention: "LM Studio's",
    offload_kv_cache_to_gpu: "LM Studio's",
    temperature: "LM Studio's",
    top_p: "LM Studio's",
    max_output_tokens: 'No limit',
    reasoning: "Model's own",
  },
  openai_compatible: { temperature: '1', top_p: '1', max_output_tokens: "Model's maximum", reasoning: "Model's own" },
};

const sizeLabel = (tokens: number) => `${tokens.toLocaleString('en-US')} tokens`;

export interface Card {
  index: number;
  name: string;
}

/** A card's number with its name, shortened: "card 0 (RTX 3080 Ti)". */
const cardLabel = (card: Card) => `card ${card.index}${card.name ? ` (${card.name.replace(/^(NVIDIA|AMD|Intel)(\(R\))?\s+(GeForce\s+|Radeon\s+)?/i, '')})` : ''}`;
const FOUR_CARDS: Card[] = [0, 1, 2, 3].map((index) => ({ index, name: '' }));

/**
 * The values a setting can take for this provider, default first. `current` is kept in the list even when it is
 * not one of the usual values (it may come from .env). `known.maxContext` is the chosen model's limit and
 * `known.cards` the PC's graphics cards, when known.
 */
export function choices(field: ChoiceField, provider: Provider, current: string, known: { maxContext?: number | null; cards?: Card[] } = {}): Choice[] {
  const { maxContext } = known;
  const cards = known.cards?.length ? known.cards : FOUR_CARDS;
  const empty = field === 'flash_attention' || field === 'offload_kv_cache_to_gpu' || field === 'reasoning' ? 'default' : '';
  // The value comes first, so a narrow box cuts off "(default)" and never the value itself.
  const first: Choice = { value: empty, label: `${DEFAULTS[provider][field] ?? 'Not set'} (default)` };
  if (field === 'idle_unload_minutes') {
    // No "default" entry: the box always shows the time in force. 0 keeps the model loaded.
    const times = [{ value: '0', label: 'Never' }, ...IDLE_MINUTES.map((v) => ({ value: String(v), label: v === 1 ? '1 minute' : `${v} minutes` }))];
    return times.some((c) => c.value === current) ? times : [...times, { value: current, label: `${current} minutes (saved)` }];
  }
  let rest: Choice[];
  switch (field) {
    case 'context_length':
      rest = CONTEXT_SIZES.filter((v) => !maxContext || v <= maxContext).map((v) => ({ value: String(v), label: sizeLabel(v) }));
      break;
    case 'eval_batch_size':
      rest = BATCH_SIZES.map((v) => ({ value: String(v), label: String(v) }));
      break;
    case 'moe_cpu_layers':
      rest = MOE_LAYERS.map((v) => ({ value: String(v), label: `${v} layer${v === 1 ? '' : 's'}` }));
      break;
    case 'flash_attention':
      rest = [{ value: 'on', label: 'On' }, { value: 'off', label: 'Off' }];
      break;
    case 'offload_kv_cache_to_gpu':
      rest = [{ value: 'on', label: 'On the GPU' }, { value: 'off', label: 'In system memory' }];
      break;
    case 'gpu':
      rest = cards.map((card) => ({ value: String(card.index), label: `Only ${cardLabel(card)}` }));
      break;
    case 'gpu_priority':
      rest = cards.map((card) => ({ value: String(card.index), label: `Fill ${cardLabel(card)} first` }));
      break;
    case 'gpu_layers':
      rest = [{ value: 'all', label: 'All layers' }, ...GPU_LAYERS.map((v) => ({ value: String(v), label: `${v} layers` })), { value: '0', label: 'None (CPU only)' }];
      break;
    case 'gpu_split':
      rest = GPU_SPLITS.map(([value, label]) => ({ value, label }));
      break;
    case 'temperature':
      rest = TEMPERATURES.map((v) => ({ value: v, label: v }));
      break;
    case 'top_p':
      rest = TOP_PS.map((v) => ({ value: v, label: v }));
      break;
    case 'max_output_tokens':
      rest = TOKEN_LIMITS.map((v) => ({ value: String(v), label: sizeLabel(v) }));
      break;
    case 'reasoning':
      // llama.cpp switches thinking on or off through the chat template; Responses endpoints take an effort.
      rest = provider === 'llamacpp' ? [{ value: 'off', label: 'Off (faster)' }, { value: 'on', label: 'On' }] : EFFORTS.map((v) => ({ value: v, label: v }));
      break;
  }
  const all = [first, ...rest];
  if (current !== empty && !all.some((c) => c.value === current)) all.push({ value: current, label: `${current} (saved)` });
  return all;
}

export const TOKEN_STEP = 1024;

export function sizeText(bytes: number | null): string {
  if (!bytes) return '';
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`;
}

/**
 * What the agent does when no context limit is chosen, in words. The main agent summarises older turns at 90% of
 * the loaded window; a cloud endpoint reports no window, so nothing happens there until a limit is chosen.
 */
export function contextDefault(agent: 'main' | 'voice', provider: Provider, loadedContext: number | null | undefined): string {
  if (agent === 'voice') return 'the last 60 messages';
  if (loadedContext) return String(Math.floor((loadedContext * 0.9) / TOKEN_STEP) * TOKEN_STEP);
  return provider === 'openai_compatible' ? 'no limit' : '90% of the window';
}
