<!-- PC and service health. Live values stream over a WebSocket only while this screen is visible;
     history for the chosen range comes over REST. Every graph covers the chosen period on a real time
     axis: a break in a line means there were no measurements then (Thursday was not running). -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { Agent, LlmCall, LlmSettings, MetricsSample } from '../../lib/api/types';
  import { backoffDelay } from '../../lib/live/stream';
  import { app } from '../../lib/state/app.svelte';
  import { formatContext } from '../../lib/state/timeline';
  import Gauge from '../../lib/ui/Gauge.svelte';
  import Spark from '../../lib/ui/Spark.svelte';
  import { SERVICE_LABEL, gb, gpuMemory, headline, hueFor, num, rate, service } from './monitor';
  import { ago, buildChart, slots, spanText, type ChartOptions } from './series';

  type Range = '15m' | '1h' | '24h' | '7d';
  const SPAN_MS: Record<Range, number> = { '15m': 900_000, '1h': 3_600_000, '24h': 86_400_000, '7d': 604_800_000 };

  let range = $state<Range>('1h');
  let history = $state.raw<MetricsSample[]>([]);
  let latest = $state<MetricsSample | null>(null);
  let calls = $state.raw<LlmCall[]>([]);
  let now = $state(Date.now());
  let models = $state<{ main: LlmSettings | null; voice: LlmSettings | null }>({ main: null, voice: null });
  let threshold = $state<number | null>(null);

  $effect(() => {
    const r = range;
    let cancelled = false;
    const load = () =>
      api.monitor(r).then(
        (d) => {
          if (cancelled || document.hidden) return;
          history = d.history;
          calls = d.llm_calls ?? [];
          latest = d.latest ?? latest;
        },
        () => undefined,
      );
    void load();
    const again = setInterval(load, 20_000); // picks up new model calls; live samples arrive on the socket
    return () => {
      cancelled = true;
      clearInterval(again);
    };
  });

  $effect(() => {
    api.llm('main').then((s) => (models.main = s), () => undefined);
    api.llm('voice').then((s) => (models.voice = s), () => undefined);
    api.general().then((g) => (threshold = g.compaction_threshold_percent ?? null), () => undefined);
    const clock = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(clock);
  });

  // Live samples: one socket while visible, closed when hidden, reconnected with backoff.
  $effect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let stopped = false;
    const open = () => {
      if (stopped || socket || document.hidden) return;
      const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/v1/metrics/stream`);
      socket = ws;
      ws.onopen = () => (attempt = 0);
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(e.data);
          if (m.kind !== 'metrics') return;
          latest = m.sample;
          if (history.at(-1)?.ts === m.sample.ts) return;
          const since = Date.now() - SPAN_MS[range];
          const first = history.findIndex((s) => Date.parse(s.ts) >= since);
          history = [...(first > 0 ? history.slice(first) : history).slice(-4000), m.sample];
        } catch {
          /* ignore a malformed frame */
        }
      };
      ws.onclose = () => {
        if (socket !== ws) return;
        socket = null;
        if (!stopped && !document.hidden) retry = setTimeout(open, backoffDelay(++attempt));
      };
    };
    const visibility = () => {
      if (document.hidden) {
        const ws = socket;
        socket = null;
        ws?.close();
      } else open();
    };
    document.addEventListener('visibilitychange', visibility);
    open();
    return () => {
      stopped = true;
      clearTimeout(retry);
      document.removeEventListener('visibilitychange', visibility);
      socket?.close();
    };
  });

  // Every graph spans the chosen period, ending now.
  const from = $derived(now - SPAN_MS[range]);
  const samples = $derived(history.map((s) => ({ t: Date.parse(s.ts), s })));

  function chart(pick: (s: MetricsSample) => number | null, options?: ChartOptions) {
    const points = [];
    for (const { t, s } of samples) {
      const v = pick(s);
      if (v !== null && Number.isFinite(v)) points.push({ t, v });
    }
    return buildChart(slots(points, from, now), options);
  }

  function callChart(agent: Agent, pick: (c: LlmCall) => number | null, options?: ChartOptions) {
    const points = [];
    for (const c of calls) {
      const v = c.agent === agent ? pick(c) : null;
      if (v !== null && Number.isFinite(v)) points.push({ t: Date.parse(c.ts), v });
    }
    return buildChart(slots(points, from, now), { sparse: true, ...options });
  }

  const lastCall = (agent: Agent) => calls.filter((c) => c.agent === agent).at(-1) ?? null;
  const long = $derived(range === '24h' || range === '7d');
  const clock = (ms: number) =>
    new Date(ms).toLocaleTimeString(undefined, long ? { weekday: 'short', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
  function span(min: number | null, max: number | null, fmt: (v: number) => string): string {
    if (min === null || max === null) return 'no data in this period';
    return fmt(min) === fmt(max) ? `steady at ${fmt(min)}` : `${fmt(min)} to ${fmt(max)}`;
  }

  const story = $derived(headline(latest, now));
  const vram = $derived(gpuMemory(latest));
  const age = $derived(latest ? Math.max(0, Math.round((now - Date.parse(latest.ts)) / 1000)) : null);
  const task = $derived(app.running[0] ?? null);
  const stepAt = $derived(task ? ({ submitted: 0, working: 1, input_required: 2 } as Record<string, number>)[task.state] ?? 1 : -1);
  const ram = $derived(latest && latest.ram_total_mb ? latest.ram_used_mb / latest.ram_total_mb : 0);
  const modelName = (s: LlmSettings | null) => (s ? (s.model.split('/').at(-1) ?? s.model) : '');
  const ctxUse = (agent: Agent) => {
    const call = lastCall(agent);
    return call?.input_tokens != null && call.context_length ? `${Math.round((call.input_tokens / call.context_length) * 100)}%` : '—';
  };
  const latency = (ms: number | null) => (ms === null ? '—' : ms < 1 ? '<1 ms' : `${Math.round(ms)} ms`);
  const contextCaption = $derived.by(() => {
    const main = lastCall('main')?.context_length ?? null;
    const voice = lastCall('voice')?.context_length ?? null;
    const parts = [];
    if (main || voice) parts.push(`${formatContext(main)} and ${formatContext(voice)} windows`);
    else parts.push(`No model calls in ${spanText(range)}`);
    if (threshold) parts.push(`summarise at ${threshold}%`);
    return parts.join(' · ');
  });
  const ttft = $derived.by(() => {
    const [main, voice] = (['main', 'voice'] as const).map((a) => lastCall(a)?.ttft_seconds ?? null);
    if (main === null && voice === null) return '—';
    return `${main?.toFixed(1) ?? '—'} · ${voice?.toFixed(1) ?? '—'} s`;
  });
  const backlog = $derived((num(latest, 'main_agent', 'outbox_backlog') ?? 0) + (num(latest, 'voice_agent', 'outbox_backlog') ?? 0));
  const awake = $derived(service(latest, 'main_agent')?.metrics.keeping_awake);
</script>

<section class="view page on" aria-label="Monitor">
  <div class="between">
    <span class="live" data-status={age === null ? 'offline' : age < 15 ? 'live' : 'stale'}>{age === null ? 'No data' : `Updated ${age} s ago`}</span>
    <div class="seg" role="group" aria-label="Time range">
      {#each ['15m', '1h', '24h', '7d'] as const as r (r)}
        <button aria-pressed={range === r} onclick={() => (range = r)}>{r}</button>
      {/each}
    </div>
  </div>

  <div class="card raised story">
    <div class="stack">
      <span class="caption">Right now</span>
      <p class="headline" style="margin:0">{story.text}{#if story.alert}{' '}<em data-state="alert" style="--h:var(--hue-alert)">{story.alert}</em>{/if}</p>
      {#if task}
        <ol class="steps" aria-label="Current task: {task.instruction}">
          {#each ['Delegated', 'Working', 'Waiting for you', 'Done'] as label, i (label)}
            <li class="step" class:done={i < stepAt} class:current={i === stepAt}>{label}</li>
          {/each}
        </ol>
      {/if}
    </div>
    <div class="gauge-card">
      {#if vram.total}
        <Gauge value={vram.used / vram.total} label="GPU memory" state={hueFor(vram.used / vram.total)} />
      {:else}
        <Gauge value={ram} label="RAM" state={hueFor(ram)} />
      {/if}
    </div>
  </div>

  <div class="between">
    <h2 class="section-title">Hardware</h2>
    <span class="caption">Graphs show {spanText(range)}: {clock(from)} to {clock(now)}. A break in a line means no measurements then.</span>
  </div>
  <div class="tile-grid">
    {#each latest?.gpus ?? [] as gpu, i (gpu.index)}
      {@const f = gpu.vram_total_mb ? gpu.vram_used_mb / gpu.vram_total_mb : 0}
      {@const c = chart((s) => s.gpus[i]?.vram_used_mb ?? null)}
      <div class="tile" data-state={hueFor(f)}>
        <div class="label">GPU {gpu.index} <span>{gpu.name} · VRAM</span></div>
        <div class="value">{gb(gpu.vram_used_mb)} / {gb(gpu.vram_total_mb)} GB</div>
        <span class="caption range">{span(c.min, c.max, (v) => `${(v / 1024).toFixed(1)} GB`)}</span>
        <Spark chart={c} />
      </div>
    {/each}
    {#if latest}
      {@const ramChart = chart((s) => (s.ram_total_mb ? (s.ram_used_mb / s.ram_total_mb) * 100 : null))}
      {@const cpuChart = chart((s) => s.cpu_percent, { zero: true })}
      {@const netChart = chart((s) => s.net_rx_bytes_per_s + s.net_tx_bytes_per_s, { zero: true })}
      <div class="tile" data-state={hueFor(ram)}>
        <div class="label">RAM <span>of {gb(latest.ram_total_mb)} GB</span></div>
        <div class="value">{Math.round(ram * 100)}%</div>
        <span class="caption range">{span(ramChart.min, ramChart.max, (v) => `${Math.round(v)}%`)}</span>
        <Spark chart={ramChart} />
      </div>
      <div class="tile" data-state={hueFor(latest.cpu_percent / 100)}>
        <div class="label">CPU</div>
        <div class="value">{Math.round(latest.cpu_percent)}%</div>
        <span class="caption range">{cpuChart.max === null ? 'no data in this period' : `peak ${Math.round(cpuChart.max)}%`}</span>
        <Spark chart={cpuChart} />
      </div>
      <div class="tile" data-state="info">
        <div class="label">Network <span>down · up</span></div>
        <div class="value" style="font-size:var(--text-title)">{rate(latest.net_rx_bytes_per_s)} · {rate(latest.net_tx_bytes_per_s)}</div>
        <span class="caption range">{netChart.max === null ? 'no data in this period' : `peak ${rate(netChart.max)}`}</span>
        <Spark chart={netChart} />
      </div>
    {:else}
      <div class="tile"><div class="label">Waiting for the first measurement…</div></div>
    {/if}
  </div>

  <h2 class="section-title">Models</h2>
  <div class="tile-grid">
    {#each [['main', 'Main', models.main], ['voice', 'Voice', models.voice]] as const as [agent, label, settings] (agent)}
      {@const last = lastCall(agent)}
      {@const count = calls.filter((c) => c.agent === agent).length}
      <div class="tile" data-state="info">
        <div class="label">{label}{settings ? ` · ${modelName(settings)}` : ''} <span>tokens/s</span></div>
        <div class="value">{last?.tokens_per_second != null ? Math.round(last.tokens_per_second) : '—'}</div>
        <span class="caption range">{last ? `last call ${ago(now - Date.parse(last.ts))} · ${count} ${count === 1 ? 'call' : 'calls'}, one dot each` : `no calls in ${spanText(range)}`}</span>
        <Spark chart={callChart(agent, (c) => c.tokens_per_second, { zero: true })} />
      </div>
    {/each}
    <div class="tile" data-state="calm">
      <div class="label">Time to first token <span>main · voice</span></div>
      <div class="value">{ttft}</div>
      <span class="caption range">main agent, one dot per call</span>
      <Spark chart={callChart('main', (c) => c.ttft_seconds, { zero: true })} />
    </div>
    <div class="tile" data-state="focus">
      <div class="label">Context in use <span>main · voice</span></div>
      <div class="value">{ctxUse('main')} · {ctxUse('voice')}</div>
      <span class="caption">{contextCaption}</span>
    </div>
  </div>

  <div class="cols-2">
    <div class="card stack">
      <h2>Services</h2>
      {#each ['gateway', 'voice_agent', 'main_agent'] as name (name)}
        {@const s = service(latest, name)}
        <div class="svc-row">
          <span class="hstack"><span class="dot {s?.up ? 'ok' : latest ? 'bad' : ''}"></span>{SERVICE_LABEL[name]}</span>
          <Spark chart={chart((x) => service(x, name)?.latency_ms ?? null, { zero: true })} area={false} state="calm" />
          <span class="caption">{s?.up ? latency(s.latency_ms) : latest ? 'not running' : '—'}</span>
        </div>
      {/each}
      <div class="svc-row">
        <span class="hstack"><span class="dot {age !== null && age < 30 ? 'ok' : 'bad'}"></span>Metrics collector</span>
        <span class="spark"></span>
        <span class="caption">{age !== null && age < 30 ? 'sending' : 'no recent data'}</span>
      </div>
    </div>
    <div class="card stack">
      <h2>Waiting and queued</h2>
      <div class="cols-auto" style="grid-template-columns:repeat(2,minmax(0,1fr))">
        <div class="stat" style:border-color={app.approvals.length ? 'color-mix(in srgb,var(--warning) 60%,var(--border))' : undefined}><span class="caption">Approvals waiting</span><span class="v">{app.approvals.length}</span></div>
        <div class="stat"><span class="caption">Messages queued</span><span class="v">{num(latest, 'gateway', 'queued_messages') ?? app.status?.queued_messages ?? '—'}</span></div>
        <div class="stat"><span class="caption">Events not yet delivered</span><span class="v">{latest ? backlog : '—'}</span></div>
        <div class="stat"><span class="caption">PC kept awake</span><span class="v" style="font-size:var(--text-base)">{awake === true ? (task?.state === 'input_required' ? 'Yes · task waiting' : 'Yes · task running') : awake === false ? 'No' : '—'}</span></div>
      </div>
    </div>
  </div>
</section>
