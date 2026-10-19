<!-- One line resting on the message bar, with the particle line running behind it: each agent's speed and how
     much of its context is in use, in tokens. A long line breaks between the two agents, never inside one. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { Agent, LlmSettings } from '../../lib/api/types';
  import { Poller } from '../../lib/live/poll';
  import { app } from '../../lib/state/app.svelte';
  import type { ChatSession } from '../../lib/state/chat.svelte';
  import { agentStats, contextText, isTerminal } from '../../lib/state/timeline';

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
    const parts = [stats.tokensPerSecond ? `${stats.tokensPerSecond} tok/s` : '', contextText(stats.contextTokens, settings.loaded?.context_length ?? stats.contextLength)].filter(Boolean);
    return { parts: parts.length ? parts : ['ready'], offPc: settings.sends_data_off_pc };
  }

  const voice = $derived(describe('voice'));
  const main = $derived(describe('main'));
</script>

<p class="telemetry" aria-label="Agent speed and context use">
  <span class="agent"><b>Voice</b> {voice.parts.join(' · ')}{#if voice.offPc}<span class="off-pc"> · sends data off this PC</span>{/if}</span>
  <span class="sep">·</span>
  <span class="agent"><b>Main</b> {main.parts.join(' · ')}{#if main.offPc}<span class="off-pc"> · sends data off this PC</span>{/if}</span>
  {#if busy && !waiting}<span class="sr-only">A task is running.</span>{/if}
</p>
