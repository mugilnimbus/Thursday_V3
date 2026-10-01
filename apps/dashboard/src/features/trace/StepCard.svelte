<!-- One model step: timing, the model's words, its tool calls with approvals and results, and the
     captured request and response bodies. -->
<script lang="ts">
  import type { TraceStep } from '../../lib/state/timeline';
  import Icon from '../../lib/ui/Icon.svelte';
  import Markdown from '../../lib/ui/Markdown.svelte';

  let { step, open = false, final = false }: { step: TraceStep; open?: boolean; final?: boolean } = $props();

  let body = $state<'request' | 'response'>('request');
  let copied = $state(false);

  const llm = $derived(step.llm ?? {});
  const title = $derived(
    final ? 'Answer' : step.tools.length ? step.tools.map((t) => t.tool).join(', ') : llm.status && llm.status !== 'ok' ? 'Model call failed' : `Step ${step.no}`,
  );
  const caption = $derived.by(() => {
    const parts: string[] = [];
    if (llm.ttft_seconds != null) parts.push(`${Number(llm.ttft_seconds).toFixed(2)} s to first token`);
    if (llm.tokens_per_second) parts.push(`${Math.round(llm.tokens_per_second)} tok/s`);
    if (llm.usage?.input_tokens != null) parts.push(`${llm.usage.input_tokens} in / ${llm.usage.output_tokens ?? 0} out`);
    if (step.attempts > 1) parts.push(`${step.attempts} attempts`);
    if (llm.status && llm.status !== 'ok') parts.push(llm.status);
    return parts.join(' · ');
  });
  const shown = $derived(pretty(body === 'request' ? llm.request_body : llm.response_body));

  function pretty(value: unknown): string {
    if (value == null) return 'Not captured.';
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    const text = String(value);
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }

  function chip(status: string) {
    if (status === 'ok') return 'var(--success)';
    if (status === 'unknown') return 'var(--warning)';
    if (status === 'requested' || status === 'running') return 'var(--accent-bright)';
    return 'var(--danger)';
  }

  const APPROVAL: Record<string, string> = { allowed: 'allowed', denied: 'denied', timed_out: 'timed out', canceled: 'cancelled' };
  const BY: Record<string, string> = { allow_always_rule: 'by an always rule', gateway: 'by you', timer: 'by the timer' };

  function approvalLine(a: NonNullable<TraceStep['tools'][number]['approval']>): string {
    const asked = new Date(a.askedAt).toLocaleTimeString();
    if (!a.outcome) return `Approval asked ${asked} · waiting`;
    const after = a.answeredAt ? ` after ${((Date.parse(a.answeredAt) - Date.parse(a.askedAt)) / 1000).toFixed(1)} s` : '';
    return `Approval asked ${asked} · ${APPROVAL[a.outcome] ?? a.outcome}${after} ${BY[a.by ?? ''] ?? ''}`.trim();
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(shown);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      /* clipboard blocked: nothing to do */
    }
  }
</script>

<details class="step-card" {open}>
  <summary>
    <span class="step-no">{step.no}</span>
    <span class="grow"><b>{title}</b><br /><span class="caption">{caption}</span></span>
    <Icon name="chev" class="chev" />
  </summary>
  <div class="step-body">
    {#if llm.text && step.tools.length}<p class="reasoning" style="margin:0">{llm.text}</p>{/if}
    {#if final && llm.text}<div class="answer"><Markdown text={llm.text} /></div>{/if}
    {#each step.tools as call (call.callKey)}
      <details class="toolcall" open={!!call.approval}>
        <summary>
          <span class="chip" style:color={chip(call.status)}>{call.status}</span>
          <b class="mono">{call.tool}</b>
          <span class="args mono">{JSON.stringify(call.args)}</span>
          {#if call.seconds != null}<span class="caption">{call.seconds.toFixed(2)} s</span>{/if}
        </summary>
        <div class="inner">
          {#if call.approval}
            <div class="hstack caption"><span class="dot {call.approval.outcome === 'allowed' ? 'ok' : 'warn'}"></span>{approvalLine(call.approval)}</div>
          {/if}
          {#if JSON.stringify(call.args).length > 60}<pre class="code">{JSON.stringify(call.args, null, 2)}</pre>{/if}
          {#if call.result}<pre class="code">{call.result}</pre>{/if}
        </div>
      </details>
    {/each}
    <div class="hstack">
      <div class="seg">
        <button aria-pressed={body === 'request'} onclick={() => (body = 'request')}>Request</button>
        <button aria-pressed={body === 'response'} onclick={() => (body = 'response')}>Response</button>
      </div>
      <span class="spacer"></span>
      <button class="btn plain" style="min-height:32px" onclick={copy}><Icon name="copy" />{copied ? 'Copied' : 'Copy'}</button>
    </div>
    <pre class="code">{shown}</pre>
    <span class="caption">Headers are never stored. Bodies over 200 kB are cut and marked.{llm.body_truncated ? ' This one was cut.' : ''}</span>
  </div>
</details>
