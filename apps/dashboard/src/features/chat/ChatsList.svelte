<!-- Phone and tablet: every project's chats in one list, plus search across all chats.
     On a wide screen the side panel's tree does this job. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import { app, errorText } from '../../lib/state/app.svelte';
  import { router } from '../../lib/state/router.svelte';
  import { ui } from '../../lib/state/ui.svelte';
  import Icon from '../../lib/ui/Icon.svelte';
  import Menu from '../../lib/ui/Menu.svelte';

  type Result = Awaited<ReturnType<typeof api.search>>['results'][number];

  let q = $state('');
  let results = $state<Result[] | null>(null);
  let searchError = $state('');
  let timer: ReturnType<typeof setTimeout> | undefined;

  function search() {
    clearTimeout(timer);
    const term = q.trim();
    if (term.length < 2) {
      results = null;
      return;
    }
    timer = setTimeout(async () => {
      try {
        const found = await api.search(term);
        if (q.trim() === term) results = found.results;
        searchError = '';
      } catch (error) {
        searchError = errorText(error);
      }
    }, 250);
  }

  async function newChat(projectId: string) {
    try {
      await app.createChat(projectId);
    } catch (error) {
      app.toast(errorText(error), 'bad');
    }
  }
</script>

<section class="view page on" aria-label="Chats">
  <div class="field-row">
    <input class="input" type="search" placeholder="Search all chats" aria-label="Search all chats" bind:value={q} oninput={search} />
    <button class="btn primary" onclick={() => router.go({ name: 'new-project' })}><Icon name="plus" />Project</button>
  </div>

  {#if results}
    <h2 class="section-title">Search results</h2>
    {#if searchError}<p class="caption" style="margin:0;color:var(--danger)">{searchError}</p>{/if}
    <div class="list">
      {#each results as r, i (i)}
        <button class="list-row" style="width:100%;text-align:left;background:none;border:0;color:inherit;font:inherit;cursor:pointer" onclick={() => router.go({ name: 'chat', chatId: r.chat_id })}>
          <span class="main-text grow">{r.chat_title}<small>{r.role === 'user' ? 'You' : 'Voice agent'}: {r.text.slice(0, 120)}</small></span>
        </button>
      {:else}
        <div class="list-row"><span class="main-text grow"><small>No messages match “{q}”.</small></span></div>
      {/each}
    </div>
  {:else}
    {#each app.projects as project (project.project_id)}
      <div class="between">
        <h2 class="section-title">{project.name}</h2>
        <Menu
          label="Actions for project {project.name}"
          items={[
            { label: 'New chat', icon: 'plus', run: () => newChat(project.project_id) },
            { label: 'Project settings', icon: 'gear', run: () => router.go({ name: 'project', projectId: project.project_id }) },
            { label: 'Delete project…', icon: 'trash', danger: true, separated: true, run: () => (ui.dialog = { kind: 'delete-project', projectId: project.project_id }) },
          ]}
        />
      </div>
      <div class="list">
        {#each app.chats[project.project_id] ?? [] as chat (chat.chat_id)}
          <div class="list-row">
            <span class="dot {app.dot(chat.chat_id)}"></span>
            <button class="main-text grow chat-open" onclick={() => router.go({ name: 'chat', chatId: chat.chat_id })}>{chat.title}<small>{app.chatLine(chat)}</small></button>
            <Menu
              label="Actions for chat {chat.title}"
              items={[
                { label: 'Rename', icon: 'edit', run: () => (ui.dialog = { kind: 'rename-chat', chatId: chat.chat_id }) },
                { label: 'Delete chat…', icon: 'trash', danger: true, separated: true, run: () => (ui.dialog = { kind: 'delete-chat', chatId: chat.chat_id }) },
              ]}
            />
          </div>
        {/each}
        <button class="list-row add-row chat-open" style="width:100%" onclick={() => newChat(project.project_id)}><Icon name="plus" />New chat</button>
      </div>
    {:else}
      {#if app.loaded}
        <div class="card empty">
          <Icon name="folder" />
          <div class="title">No projects yet</div>
          <button class="btn primary" onclick={() => router.go({ name: 'new-project' })}>Add a project folder</button>
        </div>
      {/if}
    {/each}
  {/if}
</section>

<style>
  .chat-open { background: none; border: 0; color: inherit; font: inherit; text-align: left; cursor: pointer; padding: 0; }
  .list-row.chat-open { padding: 0 var(--space-4); display: flex; align-items: center; gap: var(--space-3); }
</style>
