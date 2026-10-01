<!-- Side panel on wide screens: brand and connection, sections, and the project and chat tree. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import { app, errorText } from '../../lib/state/app.svelte';
  import { router } from '../../lib/state/router.svelte';
  import type { Section } from '../../lib/state/routes';
  import { ui } from '../../lib/state/ui.svelte';
  import Icon from '../../lib/ui/Icon.svelte';
  import Menu from '../../lib/ui/Menu.svelte';
  import ConnectionBadge from './ConnectionBadge.svelte';
  import { SECTIONS, goSection } from './sections';

  const current = $derived(router.route.name === 'chat' ? router.route.chatId : null);

  async function openTrace(chatId: string) {
    try {
      const { tasks } = await api.chatTasks(chatId);
      if (tasks[0]) router.go({ name: 'trace', taskId: tasks[0].task_id });
      else app.toast('This chat has no tasks yet.');
    } catch (error) {
      app.toast(errorText(error), 'bad');
    }
  }

  async function newChat(projectId: string) {
    try {
      await app.createChat(projectId);
    } catch (error) {
      app.toast(errorText(error), 'bad');
    }
  }

  const isOn = (section: Section) => router.section === section;
</script>

<aside class="sidebar" aria-label="Primary">
  <div class="brand"><img class="brand-logo" src="/logo-64.png" alt="" width="28" height="28" /><strong>Thursday</strong><span class="spacer"></span><ConnectionBadge /></div>
  <nav class="stack" style="gap:2px" aria-label="Sections">
    {#each SECTIONS as s (s.id)}
      <button class="nav-item" aria-current={isOn(s.id) ? 'page' : undefined} onclick={() => goSection(s.id)}><Icon name={s.icon} />{s.label}</button>
    {/each}
  </nav>
  <div class="between" style="padding: var(--space-2) var(--space-2) 0">
    <h2 class="section-title">Projects</h2>
    <button class="btn icon-btn" aria-label="New project" onclick={() => router.go({ name: 'new-project' })}><Icon name="plus" /></button>
  </div>
  <div class="tree" role="tree" aria-label="Projects and chats">
    {#if !app.loaded && !app.loadError}
      <div class="skeleton"></div>
      <div class="skeleton" style="width:70%"></div>
    {/if}
    {#each app.projects as project (project.project_id)}
      {@const chats = app.chats[project.project_id] ?? []}
      {@const open = !app.collapsed[project.project_id]}
      <div class="tree-row" role="treeitem" aria-expanded={open} aria-selected="false" aria-current={router.route.name === 'project' && router.route.projectId === project.project_id ? 'true' : undefined}>
        <Icon name="folder" />
        <button class="name" onclick={() => (app.collapsed[project.project_id] = open)} title={project.folder}>{project.name}</button>
        <span class="count">{chats.length}</span>
        <Menu
          label="Actions for project {project.name}"
          items={[
            { label: 'New chat', icon: 'plus', run: () => newChat(project.project_id) },
            { label: 'Project settings', icon: 'gear', run: () => router.go({ name: 'project', projectId: project.project_id }) },
            { label: 'Delete project…', icon: 'trash', danger: true, separated: true, run: () => (ui.dialog = { kind: 'delete-project', projectId: project.project_id }) },
          ]}
        />
      </div>
      {#if open}
        {#each chats as chat (chat.chat_id)}
          {@const dot = app.dot(chat.chat_id)}
          <div class="tree-row chat" role="treeitem" aria-selected={current === chat.chat_id} aria-current={current === chat.chat_id ? 'true' : undefined}>
            <span class="dot {dot}" title={dot === 'warn' ? 'Waiting for approval' : dot === 'run' ? 'Task running' : undefined}></span>
            <button class="name" onclick={() => router.go({ name: 'chat', chatId: chat.chat_id })}>{chat.title}</button>
            <Menu
              label="Actions for chat {chat.title}"
              items={[
                { label: 'Rename', icon: 'edit', run: () => (ui.dialog = { kind: 'rename-chat', chatId: chat.chat_id }) },
                { label: 'Open trace', icon: 'trace', run: () => openTrace(chat.chat_id) },
                { label: 'Delete chat…', icon: 'trash', danger: true, separated: true, run: () => (ui.dialog = { kind: 'delete-chat', chatId: chat.chat_id }) },
              ]}
            />
          </div>
        {/each}
        <div class="tree-row chat add-row"><Icon name="plus" size={16} /><button class="name" onclick={() => newChat(project.project_id)}>New chat</button></div>
      {/if}
    {/each}
  </div>
</aside>
