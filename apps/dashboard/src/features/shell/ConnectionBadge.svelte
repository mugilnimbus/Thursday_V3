<script lang="ts">
  import { app } from '../../lib/state/app.svelte';

  const view = $derived(
    app.connection === 'live'
      ? { status: 'live', text: 'Live' }
      : app.connection === 'connecting'
        ? { status: 'stale', text: 'Connecting' }
        : { status: 'offline', text: 'Offline' },
  );
</script>

<span class="live" data-status={view.status} title={view.status === 'offline' ? 'Cannot reach the gateway. Retrying.' : undefined}>{view.text}</span>
