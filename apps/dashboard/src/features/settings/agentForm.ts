/* The editable part of an agent's LLM settings, and the minimal change to send.
   Only fields that differ are sent; choosing "Default" sends null, which returns the field to the engine's default.
   What each setting can be set to is in agentChoices.ts. */

import type { InferenceParams, LlmChange, LlmSettings, LoadParams } from '../../lib/api/types';
import { PROVIDERS, TOKEN_STEP, type Provider } from './agentChoices';

type Toggle = 'default' | 'on' | 'off';

export interface AgentForm {
  provider: Provider;
  base_url: string;
  model: string;
  context_length: string;
  eval_batch_size: string;
  num_experts: string;
  moe_cpu_layers: string;
  gpu_layers: string;
  gpu_split: string;
  gpu_priority: string;
  flash_attention: Toggle;
  offload_kv_cache_to_gpu: Toggle;
  temperature: string;
  top_p: string;
  max_output_tokens: string;
  reasoning: string;
  models_dir: string;
  gpu: string;
  compact_at_tokens: string;
  idle_unload_minutes: string;
}

const n = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v));
const toggle = (v: boolean | null | undefined): Toggle => (v === null || v === undefined ? 'default' : v ? 'on' : 'off');

export function toForm(s: LlmSettings): AgentForm {
  return {
    provider: s.provider,
    base_url: s.base_url,
    model: s.model,
    context_length: n(s.load.context_length),
    eval_batch_size: n(s.load.eval_batch_size),
    num_experts: n(s.load.num_experts),
    moe_cpu_layers: n(s.load.moe_cpu_layers),
    gpu_layers: s.load.gpu_layers ?? '',
    gpu_split: s.load.gpu_split ?? '',
    gpu_priority: s.load.gpu_priority ?? '',
    flash_attention: toggle(s.load.flash_attention),
    offload_kv_cache_to_gpu: toggle(s.load.offload_kv_cache_to_gpu),
    temperature: n(s.inference?.temperature),
    top_p: n(s.inference?.top_p),
    max_output_tokens: n(s.inference?.max_output_tokens),
    reasoning: s.inference?.reasoning ?? 'default',
    models_dir: s.llamacpp?.models_dir ?? '',
    gpu: n(s.llamacpp?.gpu),
    compact_at_tokens: n(s.compact_at_tokens),
    idle_unload_minutes: n(s.idle_unload_minutes ?? 5),
  };
}

const num = (s: string) => (s.trim() ? Number(s) : null);
const bool = (t: Toggle) => (t === 'default' ? null : t === 'on');

export function changes(before: AgentForm, after: AgentForm): LlmChange {
  const out: LlmChange = {};
  if (after.provider !== before.provider) out.provider = after.provider;
  // An emptied address is not sent, as an emptied model is not: the built-in llama.cpp has no address, and the PC
  // drops the old provider's one by itself when the provider changes. The PC refuses an empty address.
  if (after.base_url.trim() !== before.base_url && after.base_url.trim()) out.base_url = after.base_url.trim();
  if (after.model.trim() !== before.model && after.model.trim()) out.model = after.model.trim();
  const load: Partial<LoadParams> = {};
  for (const key of ['context_length', 'eval_batch_size', 'num_experts', 'moe_cpu_layers'] as const) {
    if (after[key].trim() !== before[key]) load[key] = num(after[key]);
  }
  for (const key of ['flash_attention', 'offload_kv_cache_to_gpu'] as const) {
    if (after[key] !== before[key]) load[key] = bool(after[key]);
  }
  for (const key of ['gpu_layers', 'gpu_split', 'gpu_priority'] as const) {
    if (after[key] !== before[key]) load[key] = after[key] || null;
  }
  if (Object.keys(load).length) out.load = load;
  const inference: Partial<InferenceParams> = {};
  for (const key of ['temperature', 'top_p', 'max_output_tokens'] as const) {
    if (after[key].trim() !== before[key]) inference[key] = num(after[key]);
  }
  if (after.reasoning !== before.reasoning) inference.reasoning = after.reasoning === 'default' ? (null as unknown as string) : after.reasoning;
  if (Object.keys(inference).length) out.inference = inference;
  if (after.models_dir.trim() !== before.models_dir) out.models_dir = after.models_dir.trim() || null;
  if (after.gpu.trim() !== before.gpu) out.gpu = num(after.gpu);
  if (after.compact_at_tokens.trim() !== before.compact_at_tokens) out.compact_at_tokens = num(after.compact_at_tokens);
  if (after.idle_unload_minutes !== before.idle_unload_minutes) out.idle_unload_minutes = num(after.idle_unload_minutes);
  return out;
}

const RANGES = {
  context_length: [512, 2_000_000],
  eval_batch_size: [1, 65_536],
  num_experts: [1, 256],
  moe_cpu_layers: [0, 1024],
  max_output_tokens: [1, 1_000_000],
  gpu: [0, 64],
} as const;

/**
 * Why the form cannot be saved, or ''. `saved` is the form as last saved: while the provider, address or folder
 * differ from it, the model list on screen is not this provider's, so a model cannot be demanded yet.
 */
export function validate(form: AgentForm, saved?: AgentForm): string {
  const local = form.provider === 'llamacpp';
  if (!local && !/^https?:\/\/\S+$/.test(form.base_url.trim())) return 'The endpoint must start with http:// or https://.';
  if (!local && !form.model.trim() && !(saved && listingChanged(saved, form))) return 'Choose or enter a model.';
  for (const [key, [lo, hi]] of Object.entries(RANGES) as [keyof typeof RANGES, readonly [number, number]][]) {
    const v = form[key].trim();
    if (v && (!/^\d+$/.test(v) || Number(v) < lo || Number(v) > hi)) return `${key.replace(/_/g, ' ')} must be a whole number from ${lo} to ${hi}.`;
  }
  const t = form.temperature.trim();
  if (t && !(Number(t) >= 0 && Number(t) <= 2)) return 'Temperature must be a number from 0 to 2.';
  const p = form.top_p.trim();
  if (p && !(Number(p) > 0 && Number(p) <= 1)) return 'Top p must be a number above 0 and up to 1.';
  const c = form.compact_at_tokens.trim();
  if (c && (!/^\d+$/.test(c) || Number(c) < TOKEN_STEP || Number(c) > 2_000_000 || Number(c) % TOKEN_STEP)) {
    return `The context limit must be a multiple of ${TOKEN_STEP} tokens, from ${TOKEN_STEP} to 2,000,000.`;
  }
  return '';
}

/** Cloud endpoints receive everything in the agent's context. The built-in llama.cpp never does. */
export function sendsOffPc(form: AgentForm): boolean {
  if (form.provider === 'llamacpp') return false;
  return !/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/.test(form.base_url.trim());
}

/** The part of the form that decides which models can be listed; the list belongs to what is saved, not to unsaved edits. */
export function listingChanged(before: AgentForm, after: AgentForm): boolean {
  return (['provider', 'base_url', 'models_dir'] as const).some((k) => after[k].trim() !== before[k]);
}

const LMSTUDIO_DEFAULT_ADDRESS = 'http://localhost:1234';

/**
 * Switch the form to another provider. A model name or address from one provider means nothing to another, so the
 * form shows what that provider used last (or what is saved, when switching back to the saved provider), or nothing.
 */
export function switchProvider(form: AgentForm, settings: LlmSettings, next: Provider): void {
  if (next === form.provider) return;
  const kept = next === settings.provider ? { model: settings.model, base_url: settings.base_url } : (settings.remembered?.[next] ?? {});
  form.provider = next;
  form.model = kept.model ?? '';
  form.base_url = kept.base_url ?? (next === 'lmstudio' ? LMSTUDIO_DEFAULT_ADDRESS : '');
}

/**
 * The model to select by itself once a provider's list arrives: the only one there is, when nothing valid is
 * chosen. Null leaves the choice to the person.
 */
export function onlyChoice(form: AgentForm, models: { key: string }[]): string | null {
  if (models.length !== 1 || models[0].key === form.model) return null;
  return PROVIDERS[form.provider].folders || !form.model.trim() ? models[0].key : null;
}
