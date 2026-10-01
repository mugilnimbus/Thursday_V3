<!-- Tools, most important first: what runs without asking (revocable), then tool servers, then
     the built-in tools and whether each asks first. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { ToolsOverview } from '../../lib/api/types';
  import { Poller } from '../../lib/live/poll';
  import { app, errorText, relativeTime } from '../../lib/state/app.svelte';

  let data = $state<ToolsOverview | null>(null);
  let error = $state('');
  let busy = $state<string | null>(null);
  let poller: Poller<ToolsOverview>;

  $effect(() => {
    poller = new Poller({ fetch: () => api.tools(), onData: (d) => ((data = d), (error = '')), onError: (e) => (error = errorText(e)), intervalMs: 30_000 });
    return poller.start();
  });

  async function act(key: string, fn: () => Promise<unknown>, done: string) {
    busy = key;
    try {
      await fn();
      app.toast(done, 'ok');
      poller.refresh();
    } catch (e) {
      app.toast(errorText(e), 'bad');
    } finally {
      busy = null;
    }
  }

  // Group the built-in tools so the risky ones come first.
  const GROUPS = [
    { names: ['shell', 'shell.session.open', 'shell.session.exec', 'shell.session.close'], label: 'shell · shell sessions', text: 'Run PowerShell in the project folder' },
    { names: ['fs.delete'], label: 'fs.delete', text: 'Delete files or folders' },
    { names: ['fs.write', 'fs.edit', 'fs.patch'], label: 'fs.write · fs.edit · fs.patch', text: 'Create and change files' },
    { names: ['fs.read', 'fs.list'], label: 'fs.read · fs.list', text: 'Read files and folders' },
  ];
  const builtIn = $derived.by(() => {
    const catalog = data?.catalog ?? [];
    const known = new Set(GROUPS.flatMap((g) => g.names));
    const rows = GROUPS.map((g) => {
      const tools = catalog.filter((t) => g.names.includes(t.name));
      return { label: g.label, text: g.text, asks: tools.some((t) => t.asks_first) || (!tools.length && g.names[0] !== 'fs.read' && g.names[0] !== 'fs.write') };
    });
    const extra = catalog.filter((t) => !known.has(t.name)).map((t) => ({ label: t.name, text: t.description, asks: t.asks_first }));
    return [...rows, ...extra].sort((a, b) => Number(b.asks) - Number(a.asks));
  });

  function serverLine(s: ToolsOverview['servers'][number]): string {
    if (!data?.main_agent_reachable) return 'Unknown · the main agent is not running';
    if (!s.alive) return 'Stopped · starts on next use';
    const parts = ['Running'];
    if (s.open_sessions) parts.push(`${s.open_sessions} shell session${s.open_sessions > 1 ? 's' : ''} open`);
    if (s.idle_seconds != null) parts.push(`idle ${Math.round(s.idle_seconds / 60)} min`);
    return parts.join(' · ');
  }
</script>

<section class="view page on" aria-label="Tools">
  {#if error}<div class="banner" role="alert"><span class="grow">{error}</span></div>{/if}
  {#if data && !data.main_agent_reachable}
    <div class="banner" role="alert"><span class="grow">The main agent is not running, so rules and tool servers cannot be read right now.</span></div>
  {/if}

  <div class="card stack">
    <div class="between"><h2>Allowed without asking</h2><span class="caption">Only inside the chat shown · revoke any time</span></div>
    <div class="list">
      {#each data?.rules ?? [] as rule (rule.chat_id + rule.tool)}
        <div class="list-row">
          <span class="main-text grow">
            <span class="hstack"><b class="mono">{rule.tool}</b>{#if rule.tool.startsWith('shell')}<span class="chip" style="color:var(--danger)">any command</span>{/if}</span>
            <small>Chat “{rule.chat_title}” · since {relativeTime(rule.created_at)}</small>
          </span>
          <button class="btn danger sm" disabled={busy === rule.chat_id + rule.tool} onclick={() => act(rule.chat_id + rule.tool, () => api.revokeRule(rule.chat_id, rule.tool), `Revoked ${rule.tool} for “${rule.chat_title}”.`)}>Revoke</button>
        </div>
      {:else}
        <div class="list-row"><span class="main-text grow"><small>{data ? 'Nothing. Every risky tool asks first.' : 'Loading…'}</small></span></div>
      {/each}
    </div>
  </div>

  <div class="cols-2">
    <div class="card stack">
      <h2>Tool servers</h2>
      <div class="list">
        {#each data?.servers ?? [] as s (s.project_id)}
          <div class="list-row">
            <span class="dot {s.alive ? 'ok' : ''}"></span>
            <span class="main-text grow">{s.project_name}<small>{serverLine(s)}</small></span>
            {#if s.alive}
              <button class="btn sm" disabled={busy === s.project_id} title={s.open_sessions ? 'Also ends its open shell sessions' : undefined} onclick={() => act(s.project_id, () => api.stopToolServer(s.project_id), `Stopped the tool server for ${s.project_name}.`)}>Stop</button>
            {/if}
          </div>
        {:else}
          <div class="list-row"><span class="main-text grow"><small>{data ? 'No projects yet.' : 'Loading…'}</small></span></div>
        {/each}
      </div>
      <span class="caption">One tool server per project. A server with an open shell session is never stopped automatically.</span>
    </div>
    <div class="card stack">
      <h2>Built-in tools</h2>
      <div class="list">
        {#each builtIn as tool (tool.label)}
          <div class="list-row">
            <span class="main-text grow"><b class="mono">{tool.label}</b><small>{tool.text}</small></span>
            <span class="chip" style:color={tool.asks ? 'var(--warning)' : 'var(--text-muted)'}>{tool.asks ? 'asks first' : 'allowed'}</span>
          </div>
        {/each}
      </div>
    </div>
  </div>
</section>
