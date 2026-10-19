<!-- One agent's model settings. `form` is the parent's reactive object; edits here are the parent's unsaved changes.
     What shows depends on the provider: LM Studio and the built-in llama.cpp can load and unload models and take
     load settings; a cloud endpoint takes only answer settings. The model is picked from the provider's own list,
     and every setting is a list of the values the provider accepts, with its default named first.
     An API key is typed here and kept in this PC's credential store; it is never shown again. -->
<script lang="ts">
  import type { Agent, LlmSettings, ModelEntry } from '../../lib/api/types';
  import { formatContext } from '../../lib/state/timeline';
  import FolderPicker from './FolderPicker.svelte';
  import { PROVIDERS, TOKEN_STEP, choices, contextDefault, sizeText, type ChoiceField, type Provider } from './agentChoices';
  import { sendsOffPc, switchProvider, type AgentForm } from './agentForm';

  let {
    title,
    id,
    settings,
    form,
    error,
    busy,
    models,
    modelsError,
    listingStale,
    providerUnsaved,
    onreload,
    onunload,
    onload,
    onsavekey,
    onrefreshmodels,
  }: {
    title: string;
    id: Agent;
    settings: LlmSettings;
    form: AgentForm;
    error: string;
    busy: string;
    models: ModelEntry[];
    modelsError: string;
    /** Provider, endpoint or folder were edited and not saved: the list still belongs to the saved settings. */
    listingStale: boolean;
    /** The provider was changed and not saved: a key typed now would be stored for the old provider. */
    providerUnsaved: boolean;
    onreload: () => void;
    onunload: () => void;
    onload: () => void;
    /** Store this key for the saved provider; an empty string removes the stored key. Resolves true when stored. */
    onsavekey: (key: string) => Promise<boolean>;
    onrefreshmodels: () => void;
  } = $props();

  const kind = $derived(PROVIDERS[form.provider]);
  const offPc = $derived(sendsOffPc(form));
  const listed = $derived(models.some((m) => m.key === form.model));
  let typing = $state(false);
  let browsing = $state(false);
  let newKey = $state('');
  const chosen = $derived(models.find((m) => m.key === form.model));
  /** A model this provider can load: for a folder of files it must be one of them; elsewhere any name will do. */
  const loadable = $derived(!!form.model.trim() && (!kind.folders || listed));
  const notInstalled = $derived(kind.folders && settings.provider === 'llamacpp' && !settings.llamacpp?.installed);
  const chip = $derived.by(() => {
    if (busy === 'reload' || busy === 'load') return { text: 'loading…', color: 'var(--accent-bright)' };
    if (settings.reachable === false) return { text: settings.provider === 'llamacpp' ? 'not set up' : 'endpoint unreachable', color: 'var(--danger)' };
    if (!settings.supports_lifecycle) return { text: 'remote', color: 'var(--text-muted)' };
    if (settings.loaded) return { text: `loaded · ${formatContext(settings.loaded.context_length)}`, color: 'var(--success)' };
    return { text: 'off · loads on first use', color: 'var(--text-muted)' };
  });

  async function saveKey(value: string) {
    if (await onsavekey(value)) newKey = '';
  }
</script>

{#snippet pick(field: ChoiceField, label: string)}
  <div class="field">
    <label for="{id}-{field}">{label}</label>
    <select id="{id}-{field}" class="input" bind:value={form[field]}>
      {#each choices(field, form.provider, form[field], { maxContext: field === 'context_length' ? chosen?.max_context_length : null, cards: settings.llamacpp?.devices }) as c, i (i)}
        <option value={c.value}>{c.label}</option>
      {/each}
    </select>
  </div>
{/snippet}

<div class="card agent-card">
  <div class="between"><h2>{title}</h2><span class="chip" style:color={chip.color}>{chip.text}</span></div>
  <div class="field">
    <span class="label-like" id="{id}-provider">Provider</span>
    <div class="seg providers" role="group" aria-labelledby="{id}-provider">
      {#each Object.entries(PROVIDERS) as [value, p] (value)}
        <button aria-pressed={form.provider === value} onclick={() => switchProvider(form, settings, value as Provider)}>{p.label}</button>
      {/each}
    </div>
    {#if form.provider === 'openai_compatible'}
      <p class="caption" style="margin:0">A cloud endpoint, or a llama.cpp server you run yourself: give its address and, if it asks for one, its key.</p>
    {:else if form.provider === 'llamacpp'}
      <p class="caption" style="margin:0">Thursday starts llama.cpp itself when the model is loaded and stops it on unload. Nothing leaves this PC.</p>
    {/if}
  </div>

  {#if kind.folders}
    {#if notInstalled}
      <p class="caption" style="margin:0;color:var(--danger)" role="alert">llama.cpp is not installed yet. Run <span class="mono">uv run thursday setup</span> in the Thursday folder; it downloads the right build for this PC.</p>
    {/if}
    <div class="field">
      <label for="{id}-models_dir">Models folder</label>
      <div class="hstack">
        <input id="{id}-models_dir" class="input mono grow" placeholder="The folder that holds your .gguf model files" bind:value={form.models_dir} spellcheck="false" />
        <button class="btn" onclick={() => (browsing = !browsing)}>Browse</button>
      </div>
      {#if browsing}
        <FolderPicker start={form.models_dir || ''} onpick={(p) => ((form.models_dir = p), (browsing = false))} oncancel={() => (browsing = false)} />
      {/if}
    </div>
  {:else}
    <div class="field"><label for="{id}-ep">Endpoint</label><input id="{id}-ep" class="input mono" bind:value={form.base_url} spellcheck="false" /></div>
  {/if}

  <div class="field">
    <label for="{id}-model">Model</label>
    {#if listingStale}
      <p class="caption" style="margin:0">Save to see the models this provider offers.</p>
    {:else if typing || (!models.length && !kind.folders)}
      <input id="{id}-model" class="input mono" placeholder="model name" bind:value={form.model} spellcheck="false" />
    {:else}
      <select id="{id}-model" class="input mono" bind:value={form.model}>
        {#if !listed}<option value={form.model}>{form.model && !kind.folders ? `${form.model} (not in the list)` : 'Choose a model…'}</option>{/if}
        {#each models as m, i (i)}
          <option value={m.key}>{m.key}{m.size_bytes ? ` · ${sizeText(m.size_bytes)}` : ''}{m.loaded ? ' · loaded' : ''}</option>
        {/each}
      </select>
    {/if}
    <div class="hstack">
      <button class="btn plain sm" disabled={!!busy} onclick={onrefreshmodels}>Refresh list</button>
      {#if !kind.folders}<button class="btn plain sm" onclick={() => (typing = !typing)}>{typing ? 'Pick from the list' : 'Type a name'}</button>{/if}
    </div>
    {#if modelsError && !listingStale}<p class="caption" style="margin:0;color:var(--danger)">{modelsError}</p>{/if}
    {#if !listingStale && !modelsError && !loadable && !typing}
      <p class="caption" style="margin:0;color:var(--warning)">
        {models.length ? 'Choose a model from the list, then save.' : kind.folders ? 'No .gguf model files were found in this folder or the folders inside it.' : 'Choose or type a model, then save.'}
      </p>
    {/if}
    {#if kind.folders && chosen && !listingStale}
      <p class="caption" style="margin:0">{chosen.projector ? `Projector found (${chosen.projector}): this model can take images and, if it supports it, speech.` : 'No projector beside this file: text only.'}</p>
    {/if}
  </div>

  {#if offPc}
    <p class="caption" style="margin:0;color:var(--danger);font-weight:var(--weight-semibold)">Everything in this agent's context leaves this PC.</p>
  {/if}
  {#if kind.endpoint}
    <div class="field">
      <label for="{id}-key">API key <span class="caption default-note">{settings.api_key_held_back && !providerUnsaved ? 'typed for another address: type it again' : settings.api_key_set && !providerUnsaved ? 'set' : 'not set'}</span></label>
      {#if providerUnsaved}
        <p class="caption" style="margin:0">Save the provider change first: each provider keeps its own key.</p>
      {:else}
        <div class="hstack">
          <input id="{id}-key" class="input mono grow" type="password" autocomplete="off" placeholder={settings.api_key_set ? 'Type a new key to replace it' : 'Paste the key'} bind:value={newKey} spellcheck="false" />
          <button class="btn" disabled={!!busy || !newKey.trim()} onclick={() => saveKey(newKey.trim())}>{busy === 'key' ? 'Saving…' : 'Save key'}</button>
          {#if settings.api_key_set}<button class="btn plain" disabled={!!busy} onclick={() => saveKey('')}>Remove</button>{/if}
        </div>
        <p class="caption" style="margin:0">Kept in this PC's credential store, encrypted for your account. It is never shown again.</p>
      {/if}
    </div>
  {/if}

  {#if kind.lifecycle}
    <div class="params">
      <h3 class="section-title">Load parameters</h3>
      <div class="form-grid">
        {@render pick('context_length', 'Context length')}
        {@render pick('eval_batch_size', 'Batch size')}
        {@render pick('flash_attention', 'Flash attention')}
        {@render pick('offload_kv_cache_to_gpu', 'KV cache')}
        {#if form.provider === 'llamacpp'}
          {@render pick('moe_cpu_layers', 'Expert layers on CPU')}
          {@render pick('gpu', 'Graphics cards')}
          {@render pick('gpu_layers', 'Layers on the cards')}
          {#if form.gpu === ''}{@render pick('gpu_priority', 'A model larger than one card')}{/if}
          {#if form.gpu === '' && form.gpu_priority === ''}{@render pick('gpu_split', 'Split between the cards')}{/if}
        {:else}
          <div class="field"><label for="{id}-exp">Experts</label><input id="{id}-exp" class="input" type="number" min="1" max="256" placeholder="LM Studio's setting" value={form.num_experts} oninput={(e) => (form.num_experts = e.currentTarget.value)} /></div>
        {/if}
      </div>
      {#if form.provider === 'llamacpp'}
        <p class="caption" style="margin:0">
          {form.gpu_priority !== '' && form.gpu === ''
            ? 'The model goes on the chosen card. Only what does not fit there goes on the next card, and the other card stays free for a model that fits one card.'
            : 'A model too large for one card is split across the cards by layer; what does not fit on them runs on the CPU, which is slower.'}
          {#if settings.llamacpp?.placement} Loaded now: {settings.llamacpp.placement}.{/if}
        </p>
      {/if}
      <div class="form-grid">{@render pick('idle_unload_minutes', 'Unload when not used for')}</div>
      <div class="hstack">
        <button class="btn primary" disabled={!!busy || listingStale || !loadable} onclick={onreload}>{busy === 'reload' ? 'Loading model…' : 'Reload with these'}</button>
        {#if settings.loaded}
          <button class="btn" disabled={!!busy} onclick={onunload}>{busy === 'unload' ? 'Unloading…' : 'Unload'}</button>
        {:else}
          <button class="btn" disabled={!!busy || listingStale || !loadable} onclick={onload}>{busy === 'load' ? 'Loading…' : 'Load'}</button>
        {/if}
      </div>
    </div>
  {/if}

  <div class="params">
    <h3 class="section-title">Answers</h3>
    <div class="form-grid">
      {@render pick('temperature', 'Temperature')}
      {@render pick('top_p', 'Top p')}
      {@render pick('max_output_tokens', 'Output token limit')}
      {@render pick('reasoning', form.provider === 'llamacpp' ? 'Thinking' : 'Reasoning effort')}
    </div>
    {#if form.provider === 'openai_compatible'}
      <p class="caption" style="margin:0">Cloud reasoning models reject temperature and top p while reasoning is on, and accept only some effort levels. The endpoint says if it refuses one.</p>
    {:else if form.provider === 'lmstudio'}
      <p class="caption" style="margin:0">LM Studio documents reasoning effort for its responses endpoint; it does not document the others there, so a model may ignore them.</p>
    {/if}
    {#if settings.hears_audio}<p class="caption" style="margin:0;color:var(--success)">This model can hear speech.</p>{/if}
  </div>

  <div class="params">
    <h3 class="section-title">Context</h3>
    <div class="field">
      <label for="{id}-compact">{id === 'main' ? 'Summarise older turns when the context reaches' : 'Send at most this much of the conversation'}</label>
      <div class="hstack">
        <input id="{id}-compact" class="input tokens" type="number" min={TOKEN_STEP} max="2000000" step={TOKEN_STEP} placeholder={contextDefault(id, form.provider, settings.loaded?.context_length)} value={form.compact_at_tokens} oninput={(e) => (form.compact_at_tokens = e.currentTarget.value)} />
        <span class="caption">tokens</span>
      </div>
      <p class="caption" style="margin:0">
        {#if id === 'main'}
          {form.provider === 'openai_compatible' ? 'A cloud endpoint does not report its window, so older turns are only summarised once a limit is set here.' : 'Empty: at 90% of the loaded window. A limit larger than the window is cut to that.'}
        {:else}
          Empty: the last 60 messages. Older messages are left out, not summarised.
        {/if}
      </p>
    </div>
  </div>
  {#if error}<p class="caption" style="margin:0;color:var(--danger)" role="alert">{error}</p>{/if}
</div>

<style>
  .default-note { margin-left: 0.5em; }
  .providers { flex-wrap: wrap; }
  .providers button { white-space: nowrap; flex: 1 1 auto; }
  .tokens { max-width: 12rem; }
</style>
