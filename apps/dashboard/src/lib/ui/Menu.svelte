<!-- A "⋯" button with a popover menu. The menu is fixed-positioned under the button, closes on
     Escape, outside click, scroll, or after an item runs, and returns focus to the button. -->
<script lang="ts">
  import { tick } from 'svelte';
  import Icon from './Icon.svelte';
  import type { MenuItem } from './menu';

  let { label, items, class: extra = '' }: { label: string; items: MenuItem[]; class?: string } = $props();

  let open = $state(false);
  let button: HTMLButtonElement;
  let menu = $state<HTMLDivElement>();
  let pos = $state({ top: 0, left: 0 });

  async function toggle(event: MouseEvent) {
    event.stopPropagation();
    if (open) return close();
    const r = button.getBoundingClientRect();
    pos = { top: r.bottom + 4, left: Math.max(8, Math.min(r.left, window.innerWidth - 208)) };
    open = true;
    await tick();
    menu?.querySelector('button')?.focus();
  }

  function close(returnFocus = true) {
    if (!open) return;
    open = false;
    if (returnFocus) button?.focus();
  }

  function choose(item: MenuItem) {
    close(false);
    item.run();
  }

  function onKey(event: KeyboardEvent) {
    if (!open) return;
    if (event.key === 'Escape') close();
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const buttons = [...(menu?.querySelectorAll('button') ?? [])];
      const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = (at + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    }
  }
</script>

<svelte:window
  onkeydown={onKey}
  onclick={(e) => open && !menu?.contains(e.target as Node) && close(false)}
  onresize={() => close(false)}
/>
<svelte:document onscroll={() => close(false)} />

<button bind:this={button} class="btn icon-btn more {extra}" aria-label={label} aria-haspopup="menu" aria-expanded={open} onclick={toggle}>
  <Icon name="more" />
</button>
{#if open}
  <div bind:this={menu} class="menu open" role="menu" style:top="{pos.top}px" style:left="{pos.left}px">
    {#each items as item (item.label)}
      {#if item.separated}<hr />{/if}
      <button role="menuitem" class:danger={item.danger} onclick={() => choose(item)}><Icon name={item.icon} />{item.label}</button>
    {/each}
  </div>
{/if}
