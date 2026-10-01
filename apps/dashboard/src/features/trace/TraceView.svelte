<!-- Every task, searchable, and one task's full trace: steps, tool calls, approvals, compaction. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { TaskRow, TimelineMessage } from '../../lib/api/types';
  import { Poller } from '../../lib/live/poll';
  import { app, errorText } from '../../lib/state/app.svelte';
  import { router } from '../../lib/state/router.svelte';
  import { buildTrace, isTerminal } from '../../lib/state/timeline';
  import Icon from '../../lib/ui/Icon.svelte';
  import { groupTasks, type GroupBy, type Order } from './grouping';
  import Markdown from '../../lib/ui/Markdown.svelte';
  import StepCard from './StepCard.svelte';

  let { taskId }: { taskId: string | null } = $props();

  let filter = $state<'all' | 'running' | 'failed'>('all');
  let q = $state('');
  let groupBy = $state<GroupBy>(readChoice('thursday.traceGroup', ['chat', 'project', 'none'], 'chat'));
  let order = $state<Order>(readChoice('thursday.traceOrder', ['newest', 'oldest'], 'newest'));
  let closed = $state<Record<string, boolean>>({});

  // The grouping and order are remembered in this browser.
  function readChoice<T extends string>(key: string, allowed: T[], fallback: T): T {
    try {
      const saved = localStorage.getItem(key) as T | null;
      return saved && allowed.includes(saved) ? saved : fallback;
    } catch {
      return fallback;
    }
  }
  function remember(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* kept for this visit only */
    }
  }
  let tasks = $state<TaskRow[] | null>(null);
  let listError = $state('');
  let detail = $state<{ task: TaskRow; trace: TimelineMessage[] } | null>(null);
  let detailError = $state('');
  let showSummary = $state<Record<number, boolean>>({});

  const groups = $derived(groupTasks(tasks ?? [], groupBy, order));
  const selected = $derived(taskId ?? tasks?.[0]?.task_id ?? null);

  $effect(() => {
    const state = filter;
    const term = q.trim();
    const poller = new Poller({
      fetch: () => api.tasks(state, term || undefined),
      onData: (r) => ((tasks = r.tasks), (listError = '')),
      onError: (e) => (listError = errorText(e)),
      intervalMs: 15_000,
    });
    const timer = setTimeout(() => poller.start(), term ? 250 : 0);
    return () => (clearTimeout(timer), poller.stop());
  });

  async function loadDetail(id: string) {
    try {
      const d = await api.task(id);
      if (selected === id) detail = d;
      detailError = '';
    } catch (e) {
      detailError = errorText(e);
    }
  }

  $effect(() => {
    const id = selected;
    detail = null;
    showSummary = {};
    if (!id) return;
    void loadDetail(id);
    // Follow a running task live.
    let timer: ReturnType<typeof setTimeout> | undefined;
    const off = app.stream.subscribe((m) => {
      if ('event' in m && m.event.task_id === id && !timer) timer = setTimeout(() => ((timer = undefined), loadDetail(id)), 500);
    });
    return () => (off(), clearTimeout(timer));
  });

  const events = $derived(detail?.trace.map((m) => m.event) ?? []);
  const steps = $derived(buildTrace(events));
  const facts = $derived.by(() => {
    if (!detail) return null;
    const llm = events.filter((e) => e.type === 'llm_call' && e.payload.agent === 'main');
    const tools = events.filter((e) => e.type === 'tool_call' && !['requested', 'running'].includes(e.payload.status));
    const tokens = llm.reduce((n, e) => n + (e.payload.usage?.input_tokens ?? 0) + (e.payload.usage?.output_tokens ?? 0), 0);
    const first = events[0]?.ts ?? detail.task.created_at;
    const last = isTerminal(detail.task.state) ? detail.task.updated_at : new Date().toISOString();
    const model = llm.map((e) => modelOf(e.payload.request_body)).find(Boolean);
    return {
      seconds: Math.max(0, (Date.parse(last) - Date.parse(first)) / 1000),
      llm: llm.length,
      tools: tools.length,
      approvals: events.filter((e) => e.type === 'approval_requested').length,
      tokens,
      model: model as string | undefined,
      started: new Date(first).toLocaleTimeString(),
    };
  });

  const DOT: Record<string, string> = { completed: 'ok', failed: 'bad', canceled: '', input_required: 'warn', working: 'run', submitted: 'run' };
  const STATE: Record<string, string> = { completed: 'Completed', failed: 'Failed', canceled: 'Stopped', input_required: 'Waiting for approval', working: 'Working', submitted: 'Starting' };
  const COLOR: Record<string, string> = { completed: 'var(--success)', failed: 'var(--danger)', canceled: 'var(--text-muted)', input_required: 'var(--warning)' };

  function when(t: TaskRow): string {
    const d = new Date(t.created_at);
    const today = d.toDateString() === new Date().toDateString();
    return today ? `today ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}` : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }
  function modelOf(body: unknown): string | null {
    if (body && typeof body === 'object') return (body as { model?: string }).model ?? null;
    try {
      return JSON.parse(String(body ?? '{}')).model ?? null;
    } catch {
      return null;
    }
  }
  const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
</script>

<section class="view page on" aria-label="Trace">
  <div class="trace-layout">
    <div class="task-list">
      <input class="input" type="search" placeholder="Search tasks" aria-label="Search tasks" bind:value={q} />
      <div class="seg" style="justify-self:start">
        <button aria-pressed={filter === 'all'} onclick={() => (filter = 'all')}>All</button>
        <button aria-pressed={filter === 'running'} onclick={() => (filter = 'running')}>Running</button>
        <button aria-pressed={filter === 'failed'} onclick={() => (filter = 'failed')}>Failed</button>
      </div>
      <div class="trace-sort">
        <label class="caption" for="trace-group">Group by</label>
        <select id="trace-group" class="input mini" bind:value={groupBy} onchange={() => remember('thursday.traceGroup', groupBy)}>
          <option value="chat">Chat</option>
          <option value="project">Project</option>
          <option value="none">Nothing</option>
        </select>
        <button class="btn plain mini" onclick={() => ((order = order === 'newest' ? 'oldest' : 'newest'), remember('thursday.traceOrder', order))} title="Change the order">
          {order === 'newest' ? 'Newest first' : 'Oldest first'}
        </button>
      </div>
      {#if listError}<p class="caption" style="margin:0;color:var(--danger)">{listError}</p>{/if}
      {#if tasks === null}
        <div class="skeleton"></div><div class="skeleton" style="width:70%"></div>
      {:else}
        {#each groups as group (group.key)}
          {#if group.label}
            <button class="group-head" aria-expanded={!closed[group.key]} onclick={() => (closed[group.key] = !closed[group.key])}>
              <Icon name="chev" size={14} class="task-chev" /><span class="grow">{group.label}</span><span class="count">{group.tasks.length}</span>
            </button>
          {/if}
          {#if !closed[group.key]}
            {#each group.tasks as t (t.task_id)}
          <button class="task-item" aria-current={selected === t.task_id ? 'true' : undefined} onclick={() => router.go({ name: 'trace', taskId: t.task_id })}>
            <span class="t1"><span class="dot {DOT[t.state] ?? ''}"></span><span>{t.instruction || 'Task'}</span></span>
            <small>{STATE[t.state] ?? t.state}{groupBy !== 'chat' && t.chat_title ? ` · ${t.chat_title}` : ''} · {when(t)}</small>
          </button>
            {/each}
          {/if}
        {:else}
          <p class="caption" style="margin:0">{q ? 'No tasks match.' : 'No tasks yet. Ask for something in a chat and its trace appears here.'}</p>
        {/each}
      {/if}
    </div>

    <div class="stack" style="gap:var(--space-4);min-width:0">
      {#if detailError}
        <div class="card stack"><h3>Could not load this trace</h3><p class="muted-text" style="margin:0">{detailError}</p></div>
      {:else if detail && facts}
        <div class="card trace-head">
          <div class="between">
            <h2>{detail.task.instruction || 'Task'}</h2>
            <span class="chip" style:color={COLOR[detail.task.state] ?? 'var(--accent-bright)'}>{STATE[detail.task.state] ?? detail.task.state}</span>
          </div>
          <div class="facts">
            <span><b>{facts.seconds.toFixed(1)} s</b> total</span><span><b>{facts.llm}</b> LLM calls</span><span><b>{facts.tools}</b> tool calls</span>
            <span><b>{facts.approvals}</b> {facts.approvals === 1 ? 'approval' : 'approvals'}</span><span><b>{k(facts.tokens)}</b> tokens</span>
          </div>
          <div class="facts">
            {#if detail.task.chat_id}<span>Chat <a href="#/chat/{detail.task.chat_id}" style="color:var(--accent-bright)">{app.chat(detail.task.chat_id)?.chat.title ?? 'open'}</a></span>{/if}
            {#if facts.model}<span>{facts.model}</span>{/if}
            <span>Started {facts.started}</span>
          </div>
        </div>

        <div class="steps-v">
          {#each steps as step, i (step.no)}
            {#if step.compactedBefore}
              {@const c = step.compactedBefore}
              <div class="marker">
                Earlier turns summarised · {c.estimated_tokens_before} → {c.estimated_tokens_after} tokens ·
                <button class="btn plain" style="min-height:28px;padding:0 6px;color:var(--accent-bright)" onclick={() => (showSummary[step.no] = !showSummary[step.no])}>{showSummary[step.no] ? 'hide' : 'view'} summary</button>
              </div>
              {#if showSummary[step.no]}<pre class="code wrap">{c.summary}</pre>{/if}
            {/if}
            <StepCard {step} open={i < 2 || !isTerminal(detail.task.state)} final={i === steps.length - 1 && !step.tools.length && detail.task.state === 'completed'} />
          {:else}
            <p class="caption">No model steps recorded yet.</p>
          {/each}
          {#if detail.task.summary}
            <div class="card answer"><Markdown text={detail.task.summary} /><span class="caption">Final result, sent to the voice agent</span></div>
          {/if}
        </div>
      {:else if selected}
        <div class="card stack"><div class="skeleton"></div><div class="skeleton" style="width:60%"></div></div>
      {/if}
    </div>
  </div>
</section>
