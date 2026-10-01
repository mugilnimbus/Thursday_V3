<!-- Modal dialog: focus moves in on open, Tab stays inside, Escape or the scrim closes it. -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let { title, onclose, children }: { title: string; onclose: () => void; children: Snippet } = $props();

  let dialog: HTMLDivElement;
  const id = `dlg-${Math.random().toString(36).slice(2, 8)}`;
  let previous: Element | null = null;

  $effect(() => {
    previous = document.activeElement;
    const first = dialog.querySelector<HTMLElement>('input, textarea, .btn.plain, button');
    first?.focus();
    return () => (previous as HTMLElement | null)?.focus?.();
  });

  function onKey(event: KeyboardEvent) {
    if (event.key === 'Escape') onclose();
    if (event.key !== 'Tab') return;
    const focusable = [...dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea, [href]')];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div class="scrim open" role="presentation" onclick={(e) => e.target === e.currentTarget && onclose()} onkeydown={onKey}>
  <div bind:this={dialog} class="dialog" role="dialog" aria-modal="true" aria-labelledby={id}>
    <h2 {id}>{title}</h2>
    {@render children()}
  </div>
</div>
