<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { Agent, LlmSettings } from '../../lib/api/types';
  import { app, errorText } from '../../lib/state/app.svelte';
  import AgentCard from './AgentCard.svelte';
  import { changes, toForm, validate, type AgentForm } from './agentForm';
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
  let threshold = $state<number | null>(null);
  let thresholdSaved = $state<number | null>(null);

  function take(agent: Agent, s: LlmSettings) {
    settings[agent] = s;
    original[agent] = toForm(s);
    form[agent] = toForm(s);
  }

  async function load(agent: Agent) {
    try {
      take(agent, await api.llm(agent));
      failed[agent] = '';
    } catch (e) {
      failed[agent] = errorText(e);
    }
  }

  $effect(() => {
    void load('main');
    void load('voice');
    api.general().then(
      (g) => (threshold = thresholdSaved = g.compaction_threshold_percent ?? null),
      () => undefined,
    );
    return bar.attach({ save, discard });
  });

  const diff = $derived({
    main: original.main && form.main ? changes(original.main, form.main) : {},
    voice: original.voice && form.voice ? changes(original.voice, form.voice) : {},
  });

  $effect(() => {
    bar.dirty = Object.keys(diff.main).length > 0 || Object.keys(diff.voice).length > 0 || threshold !== thresholdSaved;
  });

  async function saveAgent(agent: Agent): Promise<void> {
    const f = form[agent];
    if (!f || !Object.keys(diff[agent]).length) return;
    const problem = validate(f);
    errors[agent] = problem;
    if (problem) throw new Error(problem);
    take(agent, await api.updateLlm(agent, diff[agent]));
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
    if (threshold !== thresholdSaved && threshold !== null) {
      const g = await api.saveGeneral({ compaction_threshold_percent: threshold });
      threshold = thresholdSaved = g.compaction_threshold_percent ?? threshold;
    }
    app.toast('Settings saved.', 'ok');
  }

  function discard() {
    for (const { agent } of AGENTS) if (original[agent]) form[agent] = { ...original[agent]! };
    threshold = thresholdSaved;
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
      if (!unsaved || !Object.keys(diff[agent]).length) form[agent] = toForm(next);
    } catch (e) {
      errors[agent] = errorText(e);
    } finally {
      busy[agent] = '';
    }
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
        onreload={() => reload(agent)}
        onunload={() => run(agent, 'unload', async () => (await api.model(agent, 'unload'), api.llm(agent)))}
        onload={() => run(agent, 'load', async () => (await api.model(agent, 'load'), api.llm(agent)))}
        onreloadkeys={() => run(agent, 'keys', () => api.reloadKeys(agent))}
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
<div class="card form">
  <div class="between"><h2>Context</h2><span class="caption">Main agent</span></div>
  {#if threshold !== null}
    <div class="field">
      <label for="compact">Summarise older turns when the context is <b>{threshold}%</b> full</label>
      <input id="compact" type="range" min="50" max="98" bind:value={threshold} />
    </div>
  {:else}
    <p class="caption" style="margin:0">Available when the main agent is running.</p>
  {/if}
</div>
