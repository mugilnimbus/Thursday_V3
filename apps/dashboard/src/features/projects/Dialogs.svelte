<!-- Rename and delete confirmations for chats and projects. Deleting removes the item from every
     Thursday service; the project folder and its files are never touched. -->
<script lang="ts">
  import { untrack } from 'svelte';
  import { app, errorText } from '../../lib/state/app.svelte';
  import { ui } from '../../lib/state/ui.svelte';
  import Dialog from '../../lib/ui/Dialog.svelte';

  const dialog = $derived(ui.dialog);
  const chat = $derived(dialog && dialog.kind !== 'delete-project' ? app.chat(dialog.chatId) : undefined);
  const project = $derived(dialog?.kind === 'delete-project' ? app.project(dialog.projectId) : undefined);

  let title = $state('');
  let confirm = $state('');
  let error = $state('');
  let busy = $state(false);

  // Reset the fields when a dialog opens (not when live updates touch the chat).
  $effect(() => {
    void ui.dialog;
    untrack(() => {
      title = chat?.chat.title ?? '';
      confirm = '';
      error = '';
    });
  });

  const close = () => (ui.dialog = null);

  async function run(fn: () => Promise<void>) {
    busy = true;
    error = '';
    try {
      await fn();
      close();
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = false;
    }
  }
</script>

{#if ui.question}
  {@const q = ui.question}
  <Dialog title={q.title} onclose={() => ui.answer(false)}>
    <p class="caption" style="margin:0">{q.body}</p>
    <div class="hstack" style="justify-content:flex-end">
      <button class="btn plain" onclick={() => ui.answer(false)}>Cancel</button>
      <button class="btn" class:danger={q.danger} class:primary={!q.danger} onclick={() => ui.answer(true)}>{q.action}</button>
    </div>
  </Dialog>
{:else if dialog?.kind === 'rename-chat' && chat}
  <Dialog title="Rename chat" onclose={close}>
    <form class="form" onsubmit={(e) => (e.preventDefault(), run(() => app.renameChat(chat.chat.chat_id, title.trim())))}>
      <div class="field" class:invalid={!!error}>
        <label for="rename-title">Name</label>
        <input id="rename-title" class="input" bind:value={title} maxlength="200" required />
        {#if error}<span class="help">{error}</span>{/if}
      </div>
      <div class="hstack" style="justify-content:flex-end">
        <button type="button" class="btn plain" onclick={close}>Cancel</button>
        <button class="btn primary" disabled={busy || !title.trim()}>Rename</button>
      </div>
    </form>
  </Dialog>
{:else if dialog?.kind === 'delete-chat' && chat}
  <Dialog title="Delete chat “{chat.chat.title}”?" onclose={close}>
    <p class="caption" style="margin:0">Its messages, tasks, traces, and allow-always rules are removed from every service. A running task is stopped first. This cannot be undone.</p>
    {#if error}<p class="caption" style="margin:0;color:var(--danger)">{error}</p>{/if}
    <div class="hstack" style="justify-content:flex-end">
      <button class="btn plain" onclick={close}>Cancel</button>
      <button class="btn danger" disabled={busy} onclick={() => run(() => app.deleteChat(chat.chat.chat_id))}>Delete chat</button>
    </div>
  </Dialog>
{:else if dialog?.kind === 'delete-project' && project}
  {@const count = (app.chats[project.project_id] ?? []).length}
  <Dialog title="Delete project “{project.name}”?" onclose={close}>
    <p style="margin:0">This removes, from every Thursday service:</p>
    <ul>
      <li>{count} {count === 1 ? 'chat' : 'chats'} and their messages</li>
      <li>their tasks, traces, and approvals</li>
      <li>their allow-always rules</li>
    </ul>
    <p class="caption" style="margin:0">The folder {project.folder} and your files are not touched. This cannot be undone.</p>
    <div class="field">
      <label for="dp-confirm">Type the project name to confirm</label>
      <input id="dp-confirm" class="input" placeholder={project.name} bind:value={confirm} autocomplete="off" />
    </div>
    {#if error}<p class="caption" style="margin:0;color:var(--danger)">{error}</p>{/if}
    <div class="hstack" style="justify-content:flex-end">
      <button class="btn plain" onclick={close}>Cancel</button>
      <button class="btn danger" disabled={busy || confirm !== project.name} onclick={() => run(() => app.deleteProject(project.project_id))}>Delete project</button>
    </div>
  </Dialog>
{/if}
