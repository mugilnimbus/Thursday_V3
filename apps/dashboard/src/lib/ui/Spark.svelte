<!-- A small time chart drawn edge to edge: smooth lines with a gradient fading to the bottom.
     Breaks in the line are stretches with no data. Paths come from features/monitor/series.ts. -->
<script lang="ts">
  import type { Chart } from '../../features/monitor/series';

  let { chart, area = true, state }: { chart: Chart; area?: boolean; state?: string } = $props();

  const id = `spark-${Math.random().toString(36).slice(2, 9)}`;
</script>

<svg class="spark" viewBox="0 0 100 40" preserveAspectRatio="none" data-state={state} aria-hidden="true">
  {#if area && chart.areas.length}
    <defs>
      <linearGradient {id} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" class="stop-top" />
        <stop offset="100%" class="stop-bottom" />
      </linearGradient>
    </defs>
    {#each chart.areas as d, i (i)}<path class="area" {d} style:fill="url(#{id})" />{/each}
  {/if}
  {#each chart.lines as d, i (i)}<path class="line" {d} />{/each}
  {#each chart.dots as dot, i (i)}<path class="point" d="M{dot.x.toFixed(2)} {dot.y.toFixed(2)}h0.01" />{/each}
</svg>
