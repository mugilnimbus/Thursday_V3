<script lang="ts">
  let { value, label, state }: { value: number; label: string; state?: string } = $props();
  const clamped = $derived(Math.max(0, Math.min(1, value)));
</script>

<div class="gauge" data-state={state} style:--v={clamped} role="img" aria-label="{label} {Math.round(clamped * 100)} percent">
  <svg viewBox="0 0 120 120"><circle class="track" cx="60" cy="60" r="52" /><circle class="bar" cx="60" cy="60" r="52" /></svg>
  <div class="center"><span class="large">{Math.round(clamped * 100)}%</span><small>{label}</small></div>
</div>
