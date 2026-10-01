<script lang="ts">
  import { app } from '../state/app.svelte';
  import Icon from './Icon.svelte';
</script>

<div class="toasts" role="status" aria-live="polite">
  {#each app.toasts as toast (toast.id)}
    <div class="toast" data-tone={toast.tone}>
      <span class="grow">{toast.text}</span>
      {#if toast.action}
        <button class="btn sm" onclick={() => (toast.action?.run(), app.dismiss(toast.id))}>{toast.action.label}</button>
      {/if}
      <button class="btn icon-btn" aria-label="Dismiss" onclick={() => app.dismiss(toast.id)}><Icon name="x" size={16} /></button>
    </div>
  {/each}
</div>
