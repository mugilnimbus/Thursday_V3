<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { GeneralSettings } from '../../lib/api/types';
  import { app, errorText } from '../../lib/state/app.svelte';
  import type { SaveBar } from './savebar.svelte';

  let { bar }: { bar: SaveBar } = $props();

  let saved = $state<GeneralSettings | null>(null);
  let paused = $state('');
  let traces = $state('');
  let metrics = $state('');
  let error = $state('');

  function reset() {
    paused = saved?.keep_awake_paused_minutes != null ? String(saved.keep_awake_paused_minutes) : '';
    traces = String(saved?.trace_retention_days ?? '');
    metrics = String(saved?.metrics_retention_days ?? '');
  }

  function whole(value: string, label: string, lo: number, hi: number): number {
    const n = Number(value);
    if (!/^\d+$/.test(value.trim()) || n < lo || n > hi) throw new Error(`${label} must be a whole number from ${lo} to ${hi}.`);
    return n;
  }

  $effect(() => {
    api.general().then(
      (g) => ((saved = g), reset()),
      (e) => (error = errorText(e)),
    );
    return bar.attach({
      save: async () => {
        const changes: Partial<GeneralSettings> = {
          trace_retention_days: whole(traces, 'Keep traces', 1, 3650),
          metrics_retention_days: whole(metrics, 'Keep metrics', 1, 365),
        };
        if (saved?.main_agent_reachable) changes.keep_awake_paused_minutes = whole(paused, 'Minutes while paused', 0, 1440);
        saved = await api.saveGeneral(changes);
        reset();
        app.toast('Settings saved.', 'ok');
      },
      discard: reset,
    });
  });

  $effect(() => {
    bar.dirty =
      !!saved &&
      (traces !== String(saved.trace_retention_days) ||
        metrics !== String(saved.metrics_retention_days) ||
        (saved.keep_awake_paused_minutes != null && paused !== String(saved.keep_awake_paused_minutes)));
  });
</script>

{#if error}<div class="banner" role="alert"><span class="grow">{error}</span></div>{/if}
<div class="card form" style="max-width:760px">
  <div class="field" style="gap:0">
    <span>Keep the PC awake while a task runs</span>
    <span class="caption">Always on while a task runs or waits for approval. It cannot stop a manual sleep or closing the lid.</span>
  </div>
  {#if saved && !saved.main_agent_reachable}
    <p class="caption" style="margin:0">The main agent is not running, so its settings cannot be changed right now.</p>
  {/if}
  <div class="field" style="max-width:260px">
    <label for="g-pause">…and while paused, for up to (minutes)</label>
    <input id="g-pause" class="input" inputmode="numeric" bind:value={paused} disabled={!saved?.main_agent_reachable} />
  </div>
  <div class="form-grid">
    <div class="field"><label for="g-trace">Keep traces (days)</label><input id="g-trace" class="input" inputmode="numeric" bind:value={traces} /></div>
    <div class="field"><label for="g-met">Keep metrics (days)</label><input id="g-met" class="input" inputmode="numeric" bind:value={metrics} /></div>
  </div>
</div>
