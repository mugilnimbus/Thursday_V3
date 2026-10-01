<!-- Subtitle above the message bar: each agent's model, where it runs, speed, and context use. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { Agent, LlmSettings } from '../../lib/api/types';
  import { Poller } from '../../lib/live/poll';
  import { app } from '../../lib/state/app.svelte';
  import type { ChatSession } from '../../lib/state/chat.svelte';
  import { agentStats, formatContext, isTerminal } from '../../lib/state/timeline';

  let { session }: { session: ChatSession } = $props();

  let llm = $state<Record<Agent, LlmSettings | null>>({ main: null, voice: null });

  $effect(() => {
    const poller = new Poller<[LlmSettings | null, LlmSettings | null]>({
      fetch: () => Promise.all([api.llm('main').catch(() => null), api.llm('voice').catch(() => null)]),
      onData: ([main, voice]) => (llm = { main, voice }),
      intervalMs: 60_000,
    });
    return poller.start();
  });

  const events = $derived(session.events.map((e) => e.event));
  const waiting = $derived([...session.tasks.values()].some((t) => t.state === 'input_required'));
  const busy = $derived([...session.tasks.values()].some((t) => !isTerminal(t.state)));

  function describe(agent: Agent) {
    const settings = llm[agent];
    const up = agent === 'main' ? app.status?.main_agent : app.status?.voice_agent;
    if (up === false || !settings) return { parts: [up === false ? 'offline' : '…'], offPc: false };
    const stats = agentStats(events, agent);
    const context = settings.loaded?.context_length ?? stats.contextLength;
    const parts = [settings.model.split('/').at(-1) ?? settings.model, settings.sends_data_off_pc ? '' : 'local'];
    if (agent === 'main' && waiting) parts.push('waiting for you');
    else if (stats.tokensPerSecond) parts.push(`${stats.tokensPerSecond} tok/s`);
    parts.push(stats.contextPercent !== null ? `context ${stats.contextPercent}% of ${formatContext(context)}` : `context ${formatContext(context)}`);
    return { parts: parts.filter(Boolean), offPc: settings.sends_data_off_pc };
  }

  const voice = $derived(describe('voice'));
  const main = $derived(describe('main'));
</script>

<p class="telemetry" aria-label="Agent speed and context use">
  <b>Voice</b> {voice.parts.join(' · ')}{#if voice.offPc}<span class="off-pc"> · sends data off this PC</span>{/if}
  <span class="sep">|</span>
  <b>Main</b> {main.parts.join(' · ')}{#if main.offPc}<span class="off-pc"> · sends data off this PC</span>{/if}
  {#if busy && !waiting}<span class="sr-only">A task is running.</span>{/if}
</p>
