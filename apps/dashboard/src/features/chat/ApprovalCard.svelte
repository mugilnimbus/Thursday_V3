<!-- The main agent wants to run something that needs your yes. Only a person's click answers it. -->
<script lang="ts">
  import type { Approval } from '../../lib/api/types';
  import { app, errorText } from '../../lib/state/app.svelte';

  let { approval, project, instruction }: { approval: Approval; project: string; instruction: string } = $props();

  let now = $state(Date.now());
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(timer);
  });

  const left = $derived(Math.max(0, Math.round((Date.parse(approval.expires_at) - now) / 1000)));
  const countdown = $derived(left ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} left` : 'expired');
  const isShell = $derived(approval.tool.startsWith('shell'));
  const detail = $derived.by(() => {
    const args = approval.arguments as Record<string, unknown>;
    if (typeof args.command === 'string') return args.command;
    if (typeof args.path === 'string') return args.path;
    return JSON.stringify(args, null, 2);
  });
  const kind = $derived(isShell ? 'shell command' : approval.tool === 'fs.delete' ? 'delete' : approval.tool);

  async function answer(decision: 'allow_once' | 'allow_always' | 'deny') {
    busy = true;
    error = '';
    try {
      await app.answer(approval, decision);
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="approval" role="alertdialog" aria-labelledby="ap-{approval.approval_id}" aria-describedby="ap-d-{approval.approval_id}">
  <div class="between">
    <strong id="ap-{approval.approval_id}">Approval needed · {kind}</strong>
    <span class="chip" style="color:var(--warning)">{countdown}</span>
  </div>
  <span id="ap-d-{approval.approval_id}">{approval.summary}</span>
  <pre class="code wrap">{detail}</pre>
  <span class="caption">Runs in {project} · task “{instruction}” · asked by the main agent</span>
  <div class="actions">
    <button class="btn primary" disabled={busy || !left} onclick={() => answer('allow_once')}>Allow once</button>
    <button class="btn" disabled={busy || !left} onclick={() => answer('allow_always')}>Always in this chat</button>
    <button class="btn danger" disabled={busy || !left} onclick={() => answer('deny')}>Deny</button>
  </div>
  {#if error}<span class="caption" style="color:var(--danger)">{error}</span>{/if}
  {#if isShell}
    <span class="caption">“Always” for shell lets this chat run any command without asking. You can revoke it in Tools.</span>
  {:else}
    <span class="caption">“Always” allows {approval.tool} in this chat without asking. You can revoke it in Tools.</span>
  {/if}
</div>
