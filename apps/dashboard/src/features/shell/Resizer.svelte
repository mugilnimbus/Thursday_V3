<!-- Drag to resize the side panel; arrow keys when focused; double-click returns to the automatic width. -->
<script lang="ts">
  import { NAV_MAX, NAV_MIN, prefs } from '../../lib/state/prefs.svelte';

  let { shell }: { shell: HTMLElement | undefined } = $props();
  let dragging = $state(false);

  function current(): number {
    return shell?.querySelector('.sidebar')?.getBoundingClientRect().width ?? 272;
  }

  function down(event: PointerEvent) {
    const target = event.currentTarget as HTMLElement;
    target.setPointerCapture(event.pointerId);
    dragging = true;
    const left = shell?.getBoundingClientRect().left ?? 0;
    const move = (e: PointerEvent) => prefs.setNavWidth(e.clientX - left);
    const up = () => {
      dragging = false;
      target.removeEventListener('pointermove', move);
      target.removeEventListener('pointerup', up);
    };
    target.addEventListener('pointermove', move);
    target.addEventListener('pointerup', up);
  }

  function key(event: KeyboardEvent) {
    if (event.key === 'ArrowLeft') prefs.setNavWidth(current() - 16);
    if (event.key === 'ArrowRight') prefs.setNavWidth(current() + 16);
  }
</script>

<!-- A focusable separator is the ARIA window-splitter pattern. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="resizer"
  class:dragging
  tabindex="0"
  role="separator"
  aria-orientation="vertical"
  aria-label="Resize side panel"
  aria-valuemin={NAV_MIN}
  aria-valuemax={NAV_MAX}
  aria-valuenow={prefs.navWidth ?? Math.round(current())}
  onpointerdown={down}
  onkeydown={key}
  ondblclick={() => prefs.setNavWidth(null)}
></div>
