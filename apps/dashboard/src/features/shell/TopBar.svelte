<!-- Breadcrumb on the left; on a chat, the running task's state with Pause and Stop at the far right. -->
<script lang="ts">
  import { app } from '../../lib/state/app.svelte';
  import { router } from '../../lib/state/router.svelte';
  import { isTerminal } from '../../lib/state/timeline';
  import { ui } from '../../lib/state/ui.svelte';
  import Icon from '../../lib/ui/Icon.svelte';

  const crumb = $derived.by(() => {
    const r = router.route;
    switch (r.name) {
      case 'chat': {
        const found = app.chat(r.chatId);
        return found ? `${found.project.name} › ${found.chat.title}` : 'Chat';
      }
      case 'project':
        return `${app.project(r.projectId)?.name ?? 'Project'} › Project settings`;
      case 'new-project':
        return 'New project';
      case 'chats':
      case 'home':
        return 'Chats';
      default:
        return r.name[0].toUpperCase() + r.name.slice(1);
    }
  });

  const back = $derived(['chat', 'project', 'new-project'].includes(router.route.name));

  const active = $derived.by(() => {
    if (router.route.name !== 'chat' || !ui.session) return null;
    const open = [...ui.session.tasks.values()].filter((t) => !isTerminal(t.state));
    return open.at(-1) ?? null;
  });

  const label = $derived.by(() => {
    if (!active) return { text: '', status: 'live' };
    if (active.state === 'input_required') return { text: 'waiting for you', status: 'stale' };
    if (active.pauseState === 'paused') return { text: 'paused', status: 'stale' };
    if (active.pauseState === 'pausing') return { text: 'pausing after this step', status: 'stale' };
    return { text: active.step ? `working · step ${active.step}` : 'working', status: 'live' };
  });

  let busy = $state(false);
  async function act(action: 'pause' | 'resume' | 'stop') {
    if (!active) return;
    busy = true;
    await app.control(active.taskId, action);
    busy = false;
  }
</script>

<header class="topbar">
  {#if back}
    <button class="btn icon-btn only-narrow" aria-label="Back to chats" onclick={() => router.go({ name: 'chats' })}><Icon name="back" /></button>
  {/if}
  <strong class="crumb">{crumb}</strong>
  <span class="spacer"></span>
  {#if active}
    <span class="hstack" role="group" aria-label="Running task">
      <span class="live" data-status={label.status}><span class="hide-narrow">{label.text}</span></span>
      {#if active.pauseState === 'paused'}
        <button class="btn ctl" disabled={busy} aria-label="Resume the task" onclick={() => act('resume')}><Icon name="play" /><span class="hide-narrow">Resume</span></button>
      {:else}
        <button class="btn ctl" disabled={busy || active.pauseState === 'pausing'} aria-label="Pause the task after this step" onclick={() => act('pause')}><Icon name="pause" /><span class="hide-narrow">Pause</span></button>
      {/if}
      <button class="btn danger ctl" disabled={busy} aria-label="Stop the task now" onclick={() => act('stop')}><Icon name="stop" /><span class="hide-narrow">Stop</span></button>
    </span>
  {/if}
</header>
