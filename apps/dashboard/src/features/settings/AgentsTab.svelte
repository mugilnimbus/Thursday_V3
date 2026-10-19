<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { Agent, LlmSettings, ModelEntry } from '../../lib/api/types';
  import { app, errorText } from '../../lib/state/app.svelte';
  import AgentCard from './AgentCard.svelte';
  import { changes, listingChanged, onlyChoice, toForm, validate, type AgentForm } from './agentForm';
  import type { SaveBar } from './savebar.svelte';

  let { bar }: { bar: SaveBar } = $props();

  const AGENTS: { agent: Agent; title: string }[] = [
    { agent: 'main', title: 'Main agent' },
    { agent: 'voice', title: 'Voice agent' },
  ];

  let settings = $state<Record<Agent, LlmSettings | null>>({ main: null, voice: null });
  let original = $state<Record<Agent, AgentForm | null>>({ main: null, voice: null });
  let form = $state<Record<Agent, AgentForm | null>>({ main: null, voice: null });
  let failed = $state<Record<Agent, string>>({ main: '', voice: '' });
  let errors = $state<Record<Agent, string>>({ main: '', voice: '' });
  let busy = $state<Record<Agent, string>>({ main: '', voice: '' });
  let models = $state<Record<Agent, ModelEntry[]>>({ main: [], voice: [] });
  let modelsError = $state<Record<Agent, string>>({ main: '', voice: '' });

  function take(agent: Agent, s: LlmSettings) {
    settings[agent] = s;
    original[agent] = toForm(s);
    form[agent] = toForm(s);
  }

  /** The models the saved provider settings offer. Listing never loads anything. */
  async function listModels(agent: Agent) {
    try {
      const r = await api.models(agent);
      models[agent] = r.models;
      modelsError[agent] = r.error ?? '';
      // With one model to choose from and nothing valid chosen, choose it: it shows as an unsaved change.
      const f = form[agent];
      const o = original[agent];
      const only = f && o && !listingChanged(o, f) ? onlyChoice(f, r.models) : null;
      if (f && only) f.model = only;
    } catch (e) {
      models[agent] = [];
      modelsError[agent] = errorText(e);
    }
  }

  async function load(agent: Agent) {
    try {
      take(agent, await api.llm(agent));
      failed[agent] = '';
      void listModels(agent);
    } catch (e) {
      failed[agent] = errorText(e);
    }
  }

  $effect(() => {
    void load('main');
    void load('voice');
    return bar.attach({ save, discard });
  });

  const diff = $derived({
    main: original.main && form.main ? changes(original.main, form.main) : {},
    voice: original.voice && form.voice ? changes(original.voice, form.voice) : {},
  });

  $effect(() => {
    bar.dirty = Object.keys(diff.main).length > 0 || Object.keys(diff.voice).length > 0;
  });

  async function saveAgent(agent: Agent): Promise<void> {
    const f = form[agent];
    if (!f || !Object.keys(diff[agent]).length) return;
    const problem = validate(f, original[agent] ?? undefined);
    errors[agent] = problem;
    if (problem) throw new Error(problem);
    take(agent, await api.updateLlm(agent, diff[agent]));
    void listModels(agent);
  }

  async function save() {
    for (const { agent } of AGENTS) {
      try {
        await saveAgent(agent);
      } catch (e) {
        errors[agent] = e instanceof Error && !('status' in e) ? e.message : errorText(e);
        throw new Error(`${agent === 'main' ? 'Main' : 'Voice'} agent: ${errors[agent]}`);
      }
    }
    app.toast('Settings saved.', 'ok');
  }

  function discard() {
    for (const { agent } of AGENTS) if (original[agent]) form[agent] = { ...original[agent]! };
    errors = { main: '', voice: '' };
  }

  async function run(agent: Agent, label: string, fn: () => Promise<LlmSettings>) {
    busy[agent] = label;
    errors[agent] = '';
    try {
      const unsaved = form[agent];
      const next = await fn();
      settings[agent] = next;
      // Keep unrelated unsaved edits; refresh the saved baseline.
      original[agent] = toForm(next);
      void listModels(agent);
      if (!unsaved || !Object.keys(diff[agent]).length) form[agent] = toForm(next);
    } catch (e) {
      errors[agent] = errorText(e);
    } finally {
      busy[agent] = '';
    }
  }

  /** Keys go straight to the credential store, apart from the save bar: a secret never waits in the form. */
  async function saveKey(agent: Agent, key: string): Promise<boolean> {
    await run(agent, 'key', () => api.setKey(agent, key));
    if (errors[agent]) return false;
    app.toast(key ? 'Key saved.' : 'Key removed.', 'ok');
    return true;
  }

  const reload = (agent: Agent) =>
    run(agent, 'reload', async () => {
      await saveAgent(agent);
      await api.model(agent, 'reload');
      return api.llm(agent);
    });
</script>

<div class="cols-2 settle">
  {#each AGENTS as { agent, title } (agent)}
    {#if settings[agent] && form[agent]}
      <AgentCard
        {title}
        id={agent}
        settings={settings[agent]!}
        form={form[agent]!}
        error={errors[agent]}
        busy={busy[agent]}
        models={models[agent]}
        modelsError={modelsError[agent]}
        listingStale={!!original[agent] && listingChanged(original[agent]!, form[agent]!)}
        providerUnsaved={original[agent]?.provider !== form[agent]!.provider}
        onrefreshmodels={() => listModels(agent)}
        onreload={() => reload(agent)}
        onunload={() => run(agent, 'unload', async () => (await api.model(agent, 'unload'), api.llm(agent)))}
        onload={() => run(agent, 'load', async () => (await api.model(agent, 'load'), api.llm(agent)))}
        onsavekey={(key) => saveKey(agent, key)}
      />
    {:else}
      <div class="card agent-card">
        <h2>{title}</h2>
        {#if failed[agent]}
          <p class="muted-text" style="margin:0">{failed[agent]}</p>
          <div><button class="btn" onclick={() => load(agent)}>Retry</button></div>
        {:else}
          <div class="skeleton"></div><div class="skeleton" style="width:60%"></div>
        {/if}
      </div>
    {/if}
  {/each}
</div>
