<!-- System prompts with versions. Saving always makes a new version; restoring loads an old one into
     the editor so you can look before saving it. Save and Discard are the ones at the top right of Settings. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { Agent, PromptVersion } from '../../lib/api/types';
  import { app, errorText, relativeTime } from '../../lib/state/app.svelte';
  import { ui } from '../../lib/state/ui.svelte';
  import type { SaveBar } from './savebar.svelte';

  let { bar }: { bar: SaveBar } = $props();

  let agent = $state<Agent>('main');
  let text = $state('');
  let saved = $state('');
  let version = $state(0);
  let versions = $state<PromptVersion[]>([]);
  let fallback = $state('');
  let error = $state('');
  let loading = $state(true);

  async function load(which: Agent) {
    loading = true;
    error = '';
    try {
      const [current, list] = await Promise.all([api.prompt(which), api.promptVersions(which)]);
      if (which !== agent) return;
      text = saved = current.text;
      version = current.version;
      versions = [...list.versions].sort((a, b) => b.version - a.version);
      fallback = list.default;
    } catch (e) {
      error = errorText(e);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void load(agent);
  });

  $effect(() =>
    bar.attach({
      save: async () => {
        if (!text.trim()) {
          error = 'The prompt cannot be empty.';
          throw new Error(error);
        }
        error = '';
        await api.savePrompt(agent, text);
        app.toast(`Saved version ${version + 1}. New tasks use it.`, 'ok');
        await load(agent);
      },
      discard: () => (text = saved),
    }),
  );

  $effect(() => {
    bar.dirty = !loading && text !== saved;
    bar.label = `Save as version ${version + 1}`;
  });

  async function pick(next: Agent) {
    if (next === agent) return;
    if (bar.dirty) {
      const choice = await ui.askUnsaved('Your edits to this prompt have not been saved.', bar.label);
      if (choice === 'cancel') return;
      if (choice === 'save' && !(await bar.run())) return;
    }
    agent = next;
  }

  const when = (iso: string) => relativeTime(iso);
</script>

<div class="between">
  <div class="seg" role="group" aria-label="Agent">
    <button aria-pressed={agent === 'main'} onclick={() => pick('main')}>Main agent</button>
    <button aria-pressed={agent === 'voice'} onclick={() => pick('voice')}>Voice agent</button>
  </div>
  <span class="caption">{version ? `Version ${version}${versions[0] ? ` · saved ${when(versions[0].created_at)}` : ''}` : 'Built-in default'}</span>
</div>
{#if error}<div class="banner" role="alert"><span class="grow">{error}</span></div>{/if}
<div class="prompt-layout">
  <div class="stack">
    <textarea class="input" aria-label="System prompt" bind:value={text} disabled={loading} spellcheck="false"></textarea>
  </div>
  <div class="card stack" style="padding:0">
    <h3 style="padding:var(--space-3) var(--space-4) 0">Versions</h3>
    <div class="list" style="border:0;border-top:1px solid var(--border);border-radius:0">
      {#each versions as v (v.version)}
        <div class="list-row">
          <span class="main-text grow">Version {v.version}{v.version === version ? ' · current' : ''}<small>{when(v.created_at)}</small></span>
          {#if v.version !== version}<button class="btn plain sm" onclick={() => (text = v.text)}>Restore</button>{/if}
        </div>
      {/each}
      <div class="list-row">
        <span class="main-text grow">Default{version === 0 ? ' · current' : ''}<small>Built in</small></span>
        {#if version !== 0}<button class="btn plain sm" onclick={() => (text = fallback)}>Restore</button>{/if}
      </div>
    </div>
  </div>
</div>
