<!-- A task inside the chat: one line with a status dot and a small arrow. Opening it shows the story
     of what the main agent did (live while it runs) and its result. -->
<script lang="ts">
  import { router } from '../../lib/state/router.svelte';
  import { isTerminal, liveLine, type TaskView } from '../../lib/state/timeline';
  import Icon from '../../lib/ui/Icon.svelte';
  import Markdown from '../../lib/ui/Markdown.svelte';

  let { task }: { task: TaskView } = $props();

  let collapsed = $state<boolean | null>(null);
  const folded = $derived(collapsed ?? isTerminal(task.state));
  const live = $derived(liveLine(task));

  // Green: done. Red: failed. Orange: needs you or paused. Violet (pulsing): working. Grey: stopped.
  const status = $derived.by(() => {
    if (task.state === 'input_required') return { dot: 'warn', text: 'Waiting for you' };
    if (task.state === 'completed') return { dot: 'ok', text: 'Completed' };
    if (task.state === 'failed') return { dot: 'bad', text: 'Failed' };
    if (task.state === 'canceled') return { dot: '', text: 'Stopped' };
    if (task.pauseState === 'paused') return { dot: 'warn', text: 'Paused' };
    return { dot: 'run pulse', text: task.step ? `Working, step ${task.step}` : 'Working' };
  });

  const TONE = { ok: 'tl-ok', warn: 'tl-warn', run: 'tl-run', bad: 'tl-bad', info: '' } as const;
</script>

<div class="task">
  <button class="task-head" aria-expanded={!folded} onclick={() => (collapsed = !folded)}>
    <span class="dot {status.dot}" title={status.text}></span>
    <strong>{task.instruction || 'Starting…'}</strong>
    <span class="sr-only">{status.text}</span>
    <Icon name="chev" class="task-chev" size={16} />
  </button>
  {#if !folded}
    <ol class="timeline">
      {#each task.lines as line, i (i)}
        <li class={TONE[line.tone]}>{line.text}<span class="t">{line.seconds.toFixed(1)} s</span></li>
      {/each}
      {#if live}<li class={TONE[live.tone]}>{live.text}</li>{/if}
    </ol>
    {#if task.summary}<div class="task-result"><Markdown text={task.summary} /></div>{/if}
    <button class="btn plain task-trace" onclick={() => router.go({ name: 'trace', taskId: task.taskId })}>Open full trace</button>
  {/if}
</div>
