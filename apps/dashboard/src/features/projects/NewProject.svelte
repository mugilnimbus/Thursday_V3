<!-- First run and "New project": a project is a folder on this PC the main agent may work in. -->
<script lang="ts">
  import { ApiError } from '../../lib/api/http';
  import { app, errorText } from '../../lib/state/app.svelte';
  import Icon from '../../lib/ui/Icon.svelte';

  let name = $state('');
  let folder = $state('');
  let folderError = $state('');
  let error = $state('');
  let busy = $state(false);

  async function create(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    folderError = error = '';
    try {
      const project = await app.createProject(name.trim(), folder.trim());
      await app.createChat(project.project_id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) folderError = e.message || 'This folder does not exist on this PC.';
      else error = errorText(e);
    } finally {
      busy = false;
    }
  }
</script>

<section class="view page on" aria-label="New project" style="max-width:860px">
  <div class="card empty">
    {#if app.projects.length}<Icon name="folder" />{:else}<img class="welcome-logo" src="/logo-192.png" alt="Thursday" width="96" height="96" />{/if}
    <div class="title">{app.projects.length ? 'Add a project folder' : 'Welcome. Add your first project folder'}</div>
    <p class="muted-text" style="margin:0">A project is a folder on this PC. The main agent can only work inside it.</p>
    <form class="form" style="width:min(480px,100%);text-align:left" onsubmit={create}>
      <div class="field"><label for="n-name">Name</label><input id="n-name" class="input" placeholder="My project" bind:value={name} maxlength="120" required /></div>
      <div class="field" class:invalid={!!folderError}>
        <label for="n-folder">Folder</label>
        <input id="n-folder" class="input mono" placeholder="C:\Users\you\Projects\my-project" bind:value={folder} required />
        <span class="help">{folderError || 'Paste the full path of an existing folder.'}</span>
      </div>
      {#if error}<p class="caption" style="margin:0;color:var(--danger)">{error}</p>{/if}
      <button class="btn primary" disabled={busy || !name.trim() || !folder.trim()}>Create project</button>
    </form>
  </div>
</section>
