<!-- Browse the folders of this PC (never files) and pick one. Used for the models folder of the built-in llama.cpp.
     Where another program keeps its models (LM Studio does, in a folder that is easy to miss) is offered as a
     shortcut at the top. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import { errorText } from '../../lib/state/app.svelte';
  import Icon from '../../lib/ui/Icon.svelte';

  let { start, onpick, oncancel }: { start: string; onpick: (path: string) => void; oncancel: () => void } = $props();

  let path = $state('');
  let parent = $state<string | null>(null);
  let folders = $state<{ name: string; path: string }[]>([]);
  let shortcuts = $state<{ name: string; path: string }[]>([]);
  let error = $state('');
  let loading = $state(true);

  async function go(to: string) {
    loading = true;
    error = '';
    try {
      const r = await api.folders(to);
      path = r.path;
      parent = r.parent;
      folders = r.folders;
      shortcuts = r.model_folders ?? [];
    } catch (e) {
      error = errorText(e);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void go(start);
  });
</script>

<div class="picker" role="group" aria-label="Choose a folder on this PC">
  <div class="hstack">
    <button class="btn plain sm" disabled={loading || (path === '' && parent === null)} onclick={() => go(parent ?? '')}>Up</button>
    <span class="mono grow" style="overflow-wrap:anywhere">{path || 'This PC'}</span>
  </div>
  {#if error}<p class="caption" style="margin:0;color:var(--danger)" role="alert">{error}</p>{/if}
  {#each shortcuts.filter((s) => s.path !== path) as s (s.path)}
    <button class="btn sm shortcut" onclick={() => go(s.path)}><Icon name="folder" size={14} /> {s.name}<span class="caption mono">{s.path}</span></button>
  {/each}
  <ul class="list">
    {#each folders as f (f.path)}
      <li><button class="btn plain sm" onclick={() => go(f.path)}><Icon name="folder" size={14} /> {f.name}</button></li>
    {:else}
      <li class="caption">{loading ? 'Loading…' : 'No sub-folders here.'}</li>
    {/each}
  </ul>
  <div class="hstack">
    <button class="btn primary sm" disabled={!path} onclick={() => onpick(path)}>Use this folder</button>
    <button class="btn plain sm" onclick={oncancel}>Cancel</button>
  </div>
</div>

<style>
  .picker { display: grid; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--bg); }
  .list { list-style: none; margin: 0; padding: 0; max-height: 220px; overflow-y: auto; display: grid; }
  .list li { min-width: 0; }
  .shortcut { justify-content: flex-start; gap: var(--space-2); flex-wrap: wrap; text-align: left; height: auto; }
  .shortcut .caption { overflow-wrap: anywhere; }
</style>
