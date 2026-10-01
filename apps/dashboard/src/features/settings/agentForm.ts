/* The editable part of an agent's LLM settings, and the minimal change to send.
   Only fields that differ are sent; clearing a number sends null, which returns it to the .env value. */

import type { LlmSettings, LoadParams } from '../../lib/api/types';

export interface AgentForm {
  provider: LlmSettings['provider'];
  base_url: string;
  model: string;
  context_length: string;
  eval_batch_size: string;
  num_experts: string;
  flash_attention: boolean | null;
  offload_kv_cache_to_gpu: boolean | null;
}

export function toForm(s: LlmSettings): AgentForm {
  const n = (v: number | null) => (v === null || v === undefined ? '' : String(v));
  return {
    provider: s.provider,
    base_url: s.base_url,
    model: s.model,
    context_length: n(s.load.context_length),
    eval_batch_size: n(s.load.eval_batch_size),
    num_experts: n(s.load.num_experts),
    flash_attention: s.load.flash_attention,
    offload_kv_cache_to_gpu: s.load.offload_kv_cache_to_gpu,
  };
}

export type LlmChange = Partial<Pick<LlmSettings, 'provider' | 'base_url' | 'model'>> & { load?: Partial<LoadParams> };

export function changes(before: AgentForm, after: AgentForm): LlmChange {
  const out: LlmChange = {};
  if (after.provider !== before.provider) out.provider = after.provider;
  if (after.base_url.trim() !== before.base_url) out.base_url = after.base_url.trim();
  if (after.model.trim() !== before.model) out.model = after.model.trim();
  const load: Partial<LoadParams> = {};
  for (const key of ['context_length', 'eval_batch_size', 'num_experts'] as const) {
    if (after[key].trim() !== before[key]) load[key] = after[key].trim() ? Number(after[key]) : null;
  }
  for (const key of ['flash_attention', 'offload_kv_cache_to_gpu'] as const) {
    if (after[key] !== before[key]) load[key] = after[key];
  }
  if (Object.keys(load).length) out.load = load;
  return out;
}

export function validate(form: AgentForm): string {
  if (!/^https?:\/\/\S+$/.test(form.base_url.trim())) return 'The endpoint must start with http:// or https://.';
  if (!form.model.trim()) return 'Enter a model name.';
  const ranges = { context_length: [512, 2_000_000], eval_batch_size: [1, 65_536], num_experts: [1, 256] } as const;
  for (const [key, [lo, hi]] of Object.entries(ranges) as [keyof typeof ranges, readonly [number, number]][]) {
    const v = form[key].trim();
    if (v && (!/^\d+$/.test(v) || Number(v) < lo || Number(v) > hi)) return `${key.replace(/_/g, ' ')} must be a whole number from ${lo} to ${hi}.`;
  }
  return '';
}

/** Cloud endpoints receive everything in the agent's context. */
export function sendsOffPc(form: AgentForm): boolean {
  return !/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/.test(form.base_url.trim());
}
