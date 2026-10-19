import { describe, expect, it } from 'vitest';
import type { LlmSettings } from '../../lib/api/types';
import { choices, contextDefault } from './agentChoices';
import { changes, listingChanged, onlyChoice, sendsOffPc, switchProvider, toForm, validate } from './agentForm';

const settings: LlmSettings = {
  provider: 'lmstudio',
  base_url: 'http://127.0.0.1:1234',
  model: 'google/gemma-4-26b',
  load: { context_length: 32768, flash_attention: true, offload_kv_cache_to_gpu: null, eval_batch_size: null, num_experts: 8, moe_cpu_layers: null, gpu_layers: null, gpu_split: null, gpu_priority: null },
  inference: { temperature: null, top_p: null, max_output_tokens: null, reasoning: 'default' },
  llamacpp: { installed: false, models_dir: '', gpu: null },
  compact_at_tokens: null,
  idle_unload_minutes: 5,
  idle_seconds: null,
  hears_audio: false,
  api_key_set: true,
  sends_data_off_pc: false,
  supports_lifecycle: true,
  loaded: null,
};

describe('agent settings form', () => {
  it('sends only what changed, with "Default" as null', () => {
    const before = toForm(settings);
    expect(before.flash_attention).toBe('on');
    expect(before.offload_kv_cache_to_gpu).toBe('default');
    const after = { ...before, model: ' google/gemma-4-e2b ', context_length: '', flash_attention: 'off' as const, offload_kv_cache_to_gpu: 'on' as const };
    expect(changes(before, after)).toEqual({
      model: 'google/gemma-4-e2b',
      load: { context_length: null, flash_attention: false, offload_kv_cache_to_gpu: true },
    });
    expect(changes(before, { ...before, flash_attention: 'default' })).toEqual({ load: { flash_attention: null } });
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

  it('sends answer, folder and llama.cpp changes, clearing with null', () => {
    const before = toForm(settings);
    const after = { ...before, temperature: '0.3', top_p: '', reasoning: 'off', models_dir: ' D:\\models ', gpu: '1', moe_cpu_layers: '4' };
    expect(changes(before, after)).toEqual({
      inference: { temperature: 0.3, reasoning: 'off' },
      models_dir: 'D:\\models',
      gpu: 1,
      load: { moe_cpu_layers: 4 },
    });
    const cleared = changes({ ...before, temperature: '0.7', reasoning: 'low', models_dir: 'D:\\m' }, { ...before, temperature: '', reasoning: 'default', models_dir: '' });
    expect(cleared).toEqual({ inference: { temperature: null, reasoning: null }, models_dir: null });
  });

  it('needs no endpoint or model name for the built-in llama.cpp, and never sends data off the PC', () => {
    const local = { ...toForm(settings), provider: 'llamacpp' as const, base_url: '', model: '' };
    expect(validate(local)).toBe('');
    expect(sendsOffPc(local)).toBe(false);
    expect(validate({ ...local, gpu: '-1' })).toContain('gpu');
    expect(validate({ ...local, temperature: '3' })).toContain('Temperature');
    expect(validate({ ...local, top_p: '0' })).toContain('Top p');
  });

  it('lists the values each provider accepts, with its default named first', () => {
    const values = (list: { value: string }[]) => list.map((c) => c.value);
    expect(values(choices('reasoning', 'llamacpp', 'default'))).toEqual(['default', 'off', 'on']);
    expect(values(choices('reasoning', 'openai_compatible', 'default'))).toContain('xhigh');
    expect(choices('context_length', 'llamacpp', '')[0]).toEqual({ value: '', label: '8,192 tokens (default)' });
    expect(choices('temperature', 'llamacpp', '')[0].label).toBe('0.8 (default)');
    expect(choices('temperature', 'openai_compatible', '')[0].label).toBe('1 (default)');
    expect(choices('context_length', 'lmstudio', '')[0].label).toBe("LM Studio's (default)");
    expect(values(choices('temperature', 'llamacpp', ''))).toEqual(expect.arrayContaining(['0', '0.7', '2']));
    expect(values(choices('flash_attention', 'llamacpp', 'default'))).toEqual(['default', 'on', 'off']);
  });

  it('never offers a context longer than the model allows, and keeps a saved value that is not a usual one', () => {
    const sizes = choices('context_length', 'lmstudio', '', { maxContext: 131072 }).map((c) => c.value);
    expect(sizes).toContain('131072');
    expect(sizes).not.toContain('262144');
    expect(choices('context_length', 'lmstudio', '32000').at(-1)).toEqual({ value: '32000', label: '32000 (saved)' });
  });

  it('takes the context limit in steps of 1024 tokens, per agent', () => {
    const form = toForm(settings);
    expect(changes(form, { ...form, compact_at_tokens: '65536' })).toEqual({ compact_at_tokens: 65536 });
    expect(changes({ ...form, compact_at_tokens: '65536' }, form)).toEqual({ compact_at_tokens: null });
    expect(validate({ ...form, compact_at_tokens: '65536' })).toBe('');
    expect(validate({ ...form, compact_at_tokens: '5000' })).toContain('multiple of 1024');
    expect(validate({ ...form, compact_at_tokens: '512' })).toContain('multiple of 1024');
    expect(contextDefault('main', 'lmstudio', 32768)).toBe('28672');
    expect(contextDefault('main', 'openai_compatible', null)).toBe('no limit');
    expect(contextDefault('voice', 'lmstudio', 32768)).toBe('the last 60 messages');
  });

  it('knows the model list belongs to what is saved', () => {
    const before = toForm(settings);
    expect(listingChanged(before, { ...before, model: 'other', temperature: '1' })).toBe(false);
    expect(listingChanged(before, { ...before, models_dir: 'D:\\models' })).toBe(true);
    expect(listingChanged(before, { ...before, provider: 'llamacpp' })).toBe(true);
  });

  it('lets llama.cpp use every card, one card, some layers, or a chosen split', () => {
    const local = { ...toForm(settings), provider: 'llamacpp' as const };
    expect(choices('gpu', 'llamacpp', '')[0].label).toBe('All cards (default)');
    expect(choices('gpu_layers', 'llamacpp', '').map((c) => c.value)).toEqual(['', 'all', '8', '16', '24', '32', '48', '64', '0']);
    expect(choices('gpu_split', 'llamacpp', '')[0].label).toBe('By free memory (default)');
    expect(changes(local, { ...local, gpu_layers: '24', gpu_split: '3,1' })).toEqual({ load: { gpu_layers: '24', gpu_split: '3,1' } });
    expect(changes({ ...local, gpu_layers: 'all', gpu_split: '1,1' }, local)).toEqual({ load: { gpu_layers: null, gpu_split: null } });
  });

  it('unloads an idle model after a chosen time, with 0 for never', () => {
    const form = toForm(settings);
    expect(form.idle_unload_minutes).toBe('5');
    expect(choices('idle_unload_minutes', 'lmstudio', '5').map((c) => c.value)).toEqual(['0', '1', '2', '5', '10', '15', '30', '60']);
    expect(choices('idle_unload_minutes', 'lmstudio', '5')[0].label).toBe('Never');
    expect(choices('idle_unload_minutes', 'lmstudio', '7').at(-1)).toEqual({ value: '7', label: '7 minutes (saved)' });
    expect(changes(form, { ...form, idle_unload_minutes: '0' })).toEqual({ idle_unload_minutes: 0 });
    expect(changes(form, { ...form, idle_unload_minutes: '30' })).toEqual({ idle_unload_minutes: 30 });
  });

  it('switching to the built-in llama.cpp sends no address and no model', () => {
    const form = toForm(settings);
    switchProvider(form, settings, 'llamacpp');
    form.models_dir = 'D:\\models';
    expect([form.base_url, form.model]).toEqual(['', '']);
    expect(changes(toForm(settings), form)).toEqual({ provider: 'llamacpp', models_dir: 'D:\\models' });
  });

  it('switching provider never carries a model or address over to a provider it means nothing to', () => {
    const lm = { ...settings, base_url: 'http://127.0.0.1:2124', model: 'google/gemma-4-12b-qat', remembered: { openai_compatible: { model: 'big', base_url: 'https://api.example.com' } } };
    const form = toForm(lm);
    switchProvider(form, lm, 'llamacpp');
    expect([form.provider, form.model, form.base_url]).toEqual(['llamacpp', '', '']);
    expect(validate(form, toForm(lm))).toBe('');
    switchProvider(form, lm, 'openai_compatible');
    expect([form.model, form.base_url]).toEqual(['big', 'https://api.example.com']);
    switchProvider(form, lm, 'lmstudio');
    expect([form.model, form.base_url]).toEqual(['google/gemma-4-12b-qat', 'http://127.0.0.1:2124']);
    expect(changes(toForm(lm), form)).toEqual({});

    const local = { ...settings, provider: 'llamacpp' as const, model: 'a.gguf', base_url: '' };
    const other = toForm(local);
    switchProvider(other, local, 'lmstudio');
    expect(other.base_url).toBe('http://localhost:1234');
    expect(validate(other, toForm(local))).toBe('');
    expect(validate(other)).toContain('model');
  });

  it('chooses the only model there is when nothing valid is chosen, and otherwise leaves the choice alone', () => {
    const local = { ...toForm(settings), provider: 'llamacpp' as const, model: 'google/gemma-4-12b-qat' };
    expect(onlyChoice(local, [{ key: 'gemma-12b-Q4.gguf' }])).toBe('gemma-12b-Q4.gguf');
    expect(onlyChoice(local, [{ key: 'a.gguf' }, { key: 'b.gguf' }])).toBeNull();
    expect(onlyChoice({ ...local, model: 'a.gguf' }, [{ key: 'a.gguf' }])).toBeNull();
    const studio = toForm(settings);
    expect(onlyChoice(studio, [{ key: 'other/model' }])).toBeNull();
    expect(onlyChoice({ ...studio, model: '' }, [{ key: 'other/model' }])).toBe('other/model');
  });

  it('can fill one card first and names the cards the PC really has', () => {
    const local = { ...toForm(settings), provider: 'llamacpp' as const };
    const cards = [{ index: 0, name: 'NVIDIA GeForce RTX 3080 Ti' }, { index: 1, name: 'NVIDIA GeForce RTX 3080 Ti' }];
    expect(choices('gpu_priority', 'llamacpp', '', { cards })).toEqual([
      { value: '', label: 'Spread over cards (default)' },
      { value: '0', label: 'Fill card 0 (RTX 3080 Ti) first' },
      { value: '1', label: 'Fill card 1 (RTX 3080 Ti) first' },
    ]);
    expect(choices('gpu', 'llamacpp', '', { cards }).map((c) => c.label)).toEqual(['All cards (default)', 'Only card 0 (RTX 3080 Ti)', 'Only card 1 (RTX 3080 Ti)']);
    expect(choices('gpu_priority', 'llamacpp', '')).toHaveLength(5);
    expect(changes(local, { ...local, gpu_priority: '1' })).toEqual({ load: { gpu_priority: '1' } });
    expect(changes({ ...local, gpu_priority: '1' }, local)).toEqual({ load: { gpu_priority: null } });
  });
});
