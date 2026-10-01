<!-- The shell: side panel (wide) or tab bar (narrow), top bar, and the current screen. -->
<script lang="ts">
  import ChatView from './features/chat/ChatView.svelte';
  import ChatsList from './features/chat/ChatsList.svelte';
  import MonitorView from './features/monitor/MonitorView.svelte';
  import Dialogs from './features/projects/Dialogs.svelte';
  import NewProject from './features/projects/NewProject.svelte';
  import ProjectSettings from './features/projects/ProjectSettings.svelte';
  import SettingsView from './features/settings/SettingsView.svelte';
  import Resizer from './features/shell/Resizer.svelte';
  import Sidebar from './features/shell/Sidebar.svelte';
  import TabBar from './features/shell/TabBar.svelte';
  import TopBar from './features/shell/TopBar.svelte';
  import ToolsView from './features/tools/ToolsView.svelte';
  import TraceView from './features/trace/TraceView.svelte';
  import { app } from './lib/state/app.svelte';
  import { prefs } from './lib/state/prefs.svelte';
  import { router } from './lib/state/router.svelte';
  import { ui } from './lib/state/ui.svelte';
  import Icons from './lib/ui/Icons.svelte';
  import Toasts from './lib/ui/Toasts.svelte';

  let shell = $state<HTMLDivElement>();
  let viewport = $state<HTMLDivElement>();

  const route = $derived(router.route);

  // "Home" resolves to the newest chat on a wide screen, the chat list on a phone, or first run.
  $effect(() => {
    if (route.name !== 'home' || !app.loaded) return;
    if (!app.projects.length) return router.go({ name: 'new-project' }, true);
    if (ui.narrow) return router.go({ name: 'chats' }, true);
    const chat = app.latestChat();
    router.go(chat ? { name: 'chat', chatId: chat.chat_id } : { name: 'chats' }, true);
  });

  // The chat list is the phone's home; on a wide screen the side panel shows it, so go to the newest chat.
  // With no chat at all the list stays (it offers "New chat"): "home" would only send us back here, forever.
  $effect(() => {
    if (route.name === 'chats' && !ui.narrow && app.loaded && app.latestChat()) router.go({ name: 'home' }, true);
  });

  // One chat session at a time, kept while its screen is open.
  $effect(() => {
    if (route.name === 'chat') ui.openChat(route.chatId);
    else ui.closeChat();
  });

  $effect(() => {
    void route;
    if (viewport) viewport.scrollTop = 0;
  });
</script>

<Icons />
<div class="app">
  <div class="shell" bind:this={shell} style:--nav-w={prefs.navWidth ? `${prefs.navWidth}px` : undefined}>
    <Sidebar />
    <Resizer {shell} />
    <div class="main">
      <TopBar />
      <div class="viewport" bind:this={viewport}>
        {#if app.loadError && !app.loaded}
          <section class="view page on" aria-label="Cannot reach Thursday">
            <div class="card stack" style="max-width:560px">
              <h3>Cannot reach Thursday</h3>
              <p class="muted-text" style="margin:0">{app.loadError} Retrying automatically. Start it with <span class="mono">uv run thursday up</span> if it is not running.</p>
              <div><button class="btn" onclick={() => app.retryNow()}>Retry now</button></div>
            </div>
          </section>
        {:else if route.name === 'chat' && ui.session}
          {#key ui.session.chatId}<ChatView session={ui.session} />{/key}
        {:else if route.name === 'chats'}
          <ChatsList />
        {:else if route.name === 'project'}
          <ProjectSettings projectId={route.projectId} />
        {:else if route.name === 'new-project'}
          <NewProject />
        {:else if route.name === 'trace'}
          <TraceView taskId={route.taskId} />
        {:else if route.name === 'tools'}
          <ToolsView />
        {:else if route.name === 'monitor'}
          <MonitorView />
        {:else if route.name === 'settings'}
          <SettingsView tab={route.tab} />
        {:else}
          <section class="view page on" aria-label="Loading">
            <div class="card stack"><div class="skeleton"></div><div class="skeleton" style="width:70%"></div><div class="skeleton" style="width:40%"></div></div>
          </section>
        {/if}
      </div>
      <TabBar />
    </div>
  </div>
  <Dialogs />
  <Toasts />
  {#if app.connection === 'offline' && app.loaded}
    <div class="sr-only" role="status">Connection to Thursday lost. Reconnecting.</div>
  {/if}
</div>
