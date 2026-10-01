<!-- System prompts with versions. Saving always makes a new version; restoring loads an old one into
     the editor so you can look before saving it. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { Agent, PromptVersion } from '../../lib/api/types';
  import { app, errorText, relativeTime } from '../../lib/state/app.svelte';
  import { ui } from '../../lib/state/ui.svelte';

  let agent = $state<Agent>('main');
  let text = $state('');
  let saved = $state('');
  let version = $state(0);
  let versions = $state<PromptVersion[]>([]);
  let fallback = $state('');
  let error = $state('');
  let loading = $state(true);
  let busy = $state(false);

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

  async function pick(next: Agent) {
    if (text !== saved && !(await ui.ask({ title: 'Discard changes?', body: 'Your edits to this prompt have not been saved.', action: 'Discard', danger: true }))) return;
    agent = next;
  }

  async function save() {
    busy = true;
    error = '';
    try {
      await api.savePrompt(agent, text);
      app.toast(`Saved version ${version + 1}. New tasks use it.`, 'ok');
      await load(agent);
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = false;
    }
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
    <div class="hstack">
      <button class="btn primary" disabled={busy || loading || text === saved || !text.trim()} onclick={save}>Save as version {version + 1}</button>
      <button class="btn plain" disabled={text === saved} onclick={() => (text = saved)}>Discard changes</button>
    </div>
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
