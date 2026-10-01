<script lang="ts">
  import { router } from '../../lib/state/router.svelte';
  import Icon from '../../lib/ui/Icon.svelte';
  import { SECTIONS, goSection } from './sections';
</script>

<nav class="tabbar" aria-label="Sections">
  {#each SECTIONS as s (s.id)}
    <button class="nav-item" aria-current={router.section === s.id ? 'page' : undefined} onclick={() => goSection(s.id)}><Icon name={s.icon} />{s.label}</button>
  {/each}
</nav>
