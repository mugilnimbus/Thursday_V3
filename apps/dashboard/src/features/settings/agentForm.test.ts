import { describe, expect, it } from 'vitest';
import type { LlmSettings } from '../../lib/api/types';
import { changes, sendsOffPc, toForm, validate } from './agentForm';

const settings: LlmSettings = {
  provider: 'lmstudio',
  base_url: 'http://127.0.0.1:1234',
  model: 'google/gemma-4-26b',
  load: { context_length: 32000, flash_attention: true, offload_kv_cache_to_gpu: null, eval_batch_size: null, num_experts: 8 },
  api_key_set: true,
  api_key_source: 'LMSTUDIO_API_TOKEN',
  sends_data_off_pc: false,
  supports_lifecycle: true,
  loaded: null,
};

describe('agent settings form', () => {
  it('sends only what changed, with cleared numbers as null', () => {
    const before = toForm(settings);
    const after = { ...before, model: ' google/gemma-4-e2b ', context_length: '', flash_attention: false };
    expect(changes(before, after)).toEqual({ model: 'google/gemma-4-e2b', load: { context_length: null, flash_attention: false } });
    expect(changes(before, before)).toEqual({});
  });

  it('checks ranges and endpoints', () => {
    const form = toForm(settings);
    expect(validate(form)).toBe('');
    expect(validate({ ...form, base_url: 'ftp://x' })).toContain('http');
    expect(validate({ ...form, context_length: '100' })).toContain('512');
    expect(validate({ ...form, num_experts: '2.5' })).toContain('whole number');
  });

  it('knows when data leaves the PC', () => {
    const form = toForm(settings);
    expect(sendsOffPc(form)).toBe(false);
    expect(sendsOffPc({ ...form, base_url: 'http://localhost:1234/v1' })).toBe(false);
    expect(sendsOffPc({ ...form, base_url: 'https://api.example.com/v1' })).toBe(true);
    expect(sendsOffPc({ ...form, base_url: 'http://127.0.0.1.evil.com' })).toBe(true);
  });
});
