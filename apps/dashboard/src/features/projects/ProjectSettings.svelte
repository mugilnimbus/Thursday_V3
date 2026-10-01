<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import { app, errorText } from '../../lib/state/app.svelte';
  import { ui } from '../../lib/state/ui.svelte';
  import Icon from '../../lib/ui/Icon.svelte';

  let { projectId }: { projectId: string } = $props();

  const project = $derived(app.project(projectId));
  const chats = $derived((app.chats[projectId] ?? []).length);

  let name = $state('');
  let folder = $state('');
  let error = $state('');
  let saving = $state(false);
  let server = $state('');

  function reset() {
    name = project?.name ?? '';
    folder = project?.folder ?? '';
    error = '';
  }

  $effect(() => {
    void projectId;
    reset();
    api
      .tools()
      .then((t) => {
        const s = t.servers.find((x) => x.project_id === projectId);
        server = !t.main_agent_reachable ? 'unknown · main agent not running' : s?.alive ? `running${s.open_sessions ? ` · ${s.open_sessions} shell session${s.open_sessions > 1 ? 's' : ''}` : ''}` : 'stopped · starts on next use';
      })
      .catch(() => (server = 'unknown'));
  });

  const dirty = $derived(!!project && (name.trim() !== project.name || folder.trim() !== project.folder));

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!project) return;
    saving = true;
    error = '';
    try {
      await app.updateProject(projectId, { name: name.trim(), folder: folder.trim() });
      app.toast('Project saved.', 'ok');
    } catch (e) {
      error = errorText(e);
    } finally {
      saving = false;
    }
  }
</script>

<section class="view page on" aria-label="Project settings" style="max-width:860px">
  {#if !project}
    <div class="card empty"><div class="title">{app.loaded ? 'This project no longer exists.' : 'Loading…'}</div></div>
  {:else}
    <form class="card form" onsubmit={save}>
      <h2>General</h2>
      <div class="field"><label for="p-name">Name</label><input id="p-name" class="input" bind:value={name} maxlength="120" required /></div>
      <div class="field" class:invalid={!!error}>
        <label for="p-folder">Folder on this PC</label>
        <input id="p-folder" class="input mono" bind:value={folder} required />
        <span class="help">{error || 'The main agent can only read and change files inside this folder.'}</span>
      </div>
      <dl class="kv">
        <dt>Chats</dt><dd>{chats}</dd>
        <dt>Created</dt><dd>{new Date(project.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</dd>
        <dt>Tool server</dt><dd>{server || '…'}</dd>
      </dl>
      <div class="hstack"><button class="btn primary" disabled={!dirty || saving}>Save</button><button type="button" class="btn plain" disabled={!dirty} onclick={reset}>Cancel</button></div>
    </form>
    <div class="card form danger-zone">
      <h2>Delete project</h2>
      <p class="muted-text" style="margin:0;font-size:var(--text-caption)">Deletes its {chats} {chats === 1 ? 'chat' : 'chats'}, their tasks, traces, and allow-always rules from every Thursday service. The folder and your files are not touched.</p>
      <div><button class="btn danger" onclick={() => (ui.dialog = { kind: 'delete-project', projectId })}><Icon name="trash" />Delete project…</button></div>
    </div>
  {/if}
</section>
