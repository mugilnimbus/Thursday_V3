<!-- One agent's model settings. Keys are only read from .env; this screen shows whether one is set.
     `form` is the parent's reactive object; edits here are the parent's unsaved changes. -->
<script lang="ts">
  import type { LlmSettings } from '../../lib/api/types';
  import { formatContext } from '../../lib/state/timeline';
  import { sendsOffPc, type AgentForm } from './agentForm';

  let {
    title,
    id,
    settings,
    form,
    error,
    busy,
    onreload,
    onunload,
    onload,
    onreloadkeys,
  }: {
    title: string;
    id: string;
    settings: LlmSettings;
    form: AgentForm;
    error: string;
    busy: string;
    onreload: () => void;
    onunload: () => void;
    onload: () => void;
    onreloadkeys: () => void;
  } = $props();

  const lmstudio = $derived(form.provider === 'lmstudio');
  const offPc = $derived(sendsOffPc(form));
  const chip = $derived.by(() => {
    if (busy === 'reload' || busy === 'load') return { text: 'loading…', color: 'var(--accent-bright)' };
    if (settings.reachable === false) return { text: 'endpoint unreachable', color: 'var(--danger)' };
    if (!settings.supports_lifecycle) return { text: 'remote', color: 'var(--text-muted)' };
    if (settings.loaded) return { text: `loaded · ${formatContext(settings.loaded.context_length)}`, color: 'var(--success)' };
    return { text: 'loads on first use', color: 'var(--text-muted)' };
  });
</script>

<div class="card agent-card">
  <div class="between"><h2>{title}</h2><span class="chip" style:color={chip.color}>{chip.text}</span></div>
  <div class="field">
    <span class="label-like" id="{id}-provider">Provider</span>
    <div class="seg" role="group" aria-labelledby="{id}-provider">
      <button aria-pressed={lmstudio} onclick={() => (form.provider = 'lmstudio')}>LM Studio</button>
      <button aria-pressed={!lmstudio} onclick={() => (form.provider = 'openai_compatible')}>OpenAI-compatible</button>
    </div>
  </div>
  <div class="field"><label for="{id}-ep">Endpoint</label><input id="{id}-ep" class="input mono" bind:value={form.base_url} spellcheck="false" /></div>
  <div class="field"><label for="{id}-model">Model</label><input id="{id}-model" class="input mono" bind:value={form.model} spellcheck="false" /></div>
  {#if offPc}
    <p class="caption" style="margin:0;color:var(--danger);font-weight:var(--weight-semibold)">Everything in this agent's context leaves this PC.</p>
  {/if}
  <div class="switch-row">
    <span class="field" style="gap:0">
      <span class="label-like">API key</span>
      <span class="caption">{settings.api_key_set ? 'Set' : 'Not set'}{#if settings.api_key_source}{' · '}<span class="mono">{settings.api_key_source}</span> in .env{/if}</span>
    </span>
    <button class="btn plain" disabled={!!busy} onclick={onreloadkeys}>{busy === 'keys' ? 'Reloading…' : 'Reload keys'}</button>
  </div>
  {#if lmstudio}
    <div class="params">
      <h3 class="section-title">Load parameters</h3>
      <div class="form-grid">
        <div class="field"><label for="{id}-ctx">Context length</label><input id="{id}-ctx" class="input" inputmode="numeric" placeholder="model default" bind:value={form.context_length} /></div>
        <div class="field"><label for="{id}-batch">Eval batch size</label><input id="{id}-batch" class="input" inputmode="numeric" placeholder="model default" bind:value={form.eval_batch_size} /></div>
        <div class="field"><label for="{id}-exp">Experts</label><input id="{id}-exp" class="input" inputmode="numeric" placeholder="model default" bind:value={form.num_experts} /></div>
      </div>
      <div class="switch-row">
        <span>Flash attention{#if form.flash_attention === null}<span class="caption default-note">model default</span>{/if}</span>
        <input type="checkbox" class="switch" aria-label="Flash attention" checked={!!form.flash_attention} onchange={(e) => (form.flash_attention = e.currentTarget.checked)} />
      </div>
      <div class="switch-row">
        <span>Keep KV cache on GPU{#if form.offload_kv_cache_to_gpu === null}<span class="caption default-note">model default</span>{/if}</span>
        <input type="checkbox" class="switch" aria-label="Keep KV cache on GPU" checked={!!form.offload_kv_cache_to_gpu} onchange={(e) => (form.offload_kv_cache_to_gpu = e.currentTarget.checked)} />
      </div>
      <div class="hstack">
        <button class="btn primary" disabled={!!busy} onclick={onreload}>{busy === 'reload' ? 'Loading model…' : 'Reload with these'}</button>
        {#if settings.loaded}
          <button class="btn" disabled={!!busy} onclick={onunload}>{busy === 'unload' ? 'Unloading…' : 'Unload'}</button>
        {:else}
          <button class="btn" disabled={!!busy} onclick={onload}>{busy === 'load' ? 'Loading…' : 'Load'}</button>
        {/if}
      </div>
    </div>
  {/if}
  {#if error}<p class="caption" style="margin:0;color:var(--danger)" role="alert">{error}</p>{/if}
</div>

<style>
  .default-note { margin-left: 0.5em; }
</style>
