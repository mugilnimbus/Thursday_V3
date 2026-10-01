<!-- Pair a phone with a one-time code made on this PC, and revoke paired devices. -->
<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { Device, PairingCode } from '../../lib/api/types';
  import { app, errorText, relativeTime } from '../../lib/state/app.svelte';
  import { ui } from '../../lib/state/ui.svelte';
  import Qr from '../../lib/ui/Qr.svelte';

  let pairing = $state<PairingCode | null>(null);
  let devices = $state<Device[] | null>(null);
  let error = $state('');
  let busy = $state('');
  let now = $state(Date.now());

  async function refresh() {
    try {
      devices = (await api.devices()).devices;
    } catch (e) {
      error = errorText(e);
    }
  }

  $effect(() => {
    void refresh();
    const clock = setInterval(() => (now = Date.now()), 1000);
    const poll = setInterval(() => !document.hidden && refresh(), 10_000); // a phone may pair meanwhile
    return () => (clearInterval(clock), clearInterval(poll));
  });

  const left = $derived(pairing ? Math.max(0, Math.round((Date.parse(pairing.expires_at) - now) / 1000)) : 0);

  async function newCode() {
    busy = 'code';
    error = '';
    try {
      pairing = await api.pairingCode();
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = '';
    }
  }

  async function revoke(device: Device) {
    const yes = await ui.ask({ title: `Revoke ${device.name}?`, body: 'It is disconnected at once and must pair again to come back.', action: 'Revoke', danger: true });
    if (!yes) return;
    busy = device.device_id;
    try {
      await api.revokeDevice(device.device_id);
      app.toast(`${device.name} was revoked.`, 'ok');
      await refresh();
    } catch (e) {
      app.toast(errorText(e), 'bad');
    } finally {
      busy = '';
    }
  }
</script>

<div class="card" style="max-width:760px">
  <div class="between" style="align-items:flex-start">
    <div class="stack" style="max-width:520px">
      <h2>Pair a phone</h2>
      {#if pairing && left}
        <p class="muted-text" style="margin:0;font-size:var(--text-caption)">
          In the Thursday app, tap “Scan the code” and point it here, or type this address and code. The code works once and expires in
          {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')}.
        </p>
        <dl class="kv">
          <dt>Address</dt><dd class="mono">{pairing.address ?? 'Unknown: set GATEWAY_PUBLIC_URL in .env'}</dd>
          <dt>Code</dt><dd><span class="pair-code">{pairing.code}</span></dd>
        </dl>
      {:else}
        <p class="muted-text" style="margin:0;font-size:var(--text-caption)">
          Make a one-time code, then enter it in the Thursday app on your phone. Codes can only be made on this PC and expire after 5 minutes.
        </p>
      {/if}
      <div class="hstack"><button class="btn" disabled={busy === 'code'} onclick={newCode}>{pairing ? 'New code' : 'Make a pairing code'}</button></div>
      {#if error}<p class="caption" style="margin:0;color:var(--danger)" role="alert">{error}</p>{/if}
    </div>
    {#if pairing && left && pairing.pairing_uri}<Qr text={pairing.pairing_uri} label="Pairing code for the Thursday app" />{/if}
  </div>
</div>
<div class="card stack" style="max-width:760px">
  <h2>Paired devices</h2>
  <div class="list">
    {#each devices ?? [] as device (device.device_id)}
      {@const recent = device.last_seen && Date.now() - Date.parse(device.last_seen) < 10 * 60_000}
      <div class="list-row">
        <span class="dot {recent ? 'ok' : ''}"></span>
        <span class="main-text grow">{device.name}<small>Paired {new Date(device.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}{device.last_seen ? ` · last seen ${relativeTime(device.last_seen)}` : ''}</small></span>
        <button class="btn danger sm" disabled={busy === device.device_id} onclick={() => revoke(device)}>Revoke</button>
      </div>
    {:else}
      <div class="list-row"><span class="main-text grow"><small>{devices ? 'No devices paired yet.' : 'Loading…'}</small></span></div>
    {/each}
  </div>
  <span class="caption">Pairing codes can only be made on this PC. A revoked phone is disconnected at once.</span>
</div>

<style>
  .pair-code { font-family: var(--font-mono); font-size: var(--text-large); font-weight: var(--weight-semibold); letter-spacing: 0.12em; color: var(--accent-bright); }
</style>
