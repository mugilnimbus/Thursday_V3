<script lang="ts">
  import { api } from '../../lib/api/gateway';
  import type { BackupSettings } from '../../lib/api/types';
  import { app, errorText } from '../../lib/state/app.svelte';
  import type { SaveBar } from './savebar.svelte';

  let { bar }: { bar: SaveBar } = $props();

  let saved = $state<BackupSettings | null>(null);
  let folder = $state('');
  let daily = $state(false);
  let keep = $state('7');
  let error = $state('');
  let running = $state(false);

  function reset() {
    folder = saved?.folder ?? '';
    daily = saved?.daily ?? false;
    keep = String(saved?.keep_copies ?? 7);
  }

  async function load() {
    try {
      saved = await api.backupSettings();
      reset();
    } catch (e) {
      error = errorText(e);
    }
  }

  $effect(() => {
    void load();
    return bar.attach({
      save: async () => {
        const copies = Number(keep);
        if (!Number.isInteger(copies) || copies < 1 || copies > 365) throw new Error('Copies to keep must be a whole number from 1 to 365.');
        const next = await api.saveBackupSettings({ folder: folder.trim(), daily, keep_copies: copies });
        saved = { ...next, last_run: saved?.last_run ?? null };
        reset();
        app.toast('Backup settings saved.', 'ok');
      },
      discard: reset,
    });
  });

  $effect(() => {
    bar.dirty = !!saved && (folder.trim() !== saved.folder || daily !== saved.daily || keep !== String(saved.keep_copies));
  });

  async function backupNow() {
    running = true;
    error = '';
    try {
      const run = await api.backupNow();
      if (saved) saved.last_run = run;
      app.toast(run.complete ? 'Backup complete.' : 'Backup finished, but some services were not running.', run.complete ? 'ok' : 'warn');
    } catch (e) {
      error = errorText(e);
    } finally {
      running = false;
    }
  }

  const last = $derived(saved?.last_run ?? null);
  const missing = $derived(last ? Object.entries(last.services).filter(([, ok]) => !ok).map(([name]) => name.replace('_', ' ')) : []);
</script>

<div class="card form" style="max-width:760px">
  <div class="field">
    <label for="b-folder">Backup folder</label>
    <input id="b-folder" class="input mono" bind:value={folder} placeholder="C:\Users\you\Thursday Backup" spellcheck="false" />
    <span class="help">Holds your chats and device token hashes; keep it private. .env is never included.</span>
  </div>
  <div class="switch-row"><span>Back up every day</span><input type="checkbox" class="switch" aria-label="Back up every day" bind:checked={daily} /></div>
  <div class="field" style="max-width:220px"><label for="b-keep">Copies to keep</label><input id="b-keep" class="input" inputmode="numeric" bind:value={keep} /></div>
  <div class="hstack">
    <button class="btn primary" disabled={running || !saved?.folder || bar.dirty} title={bar.dirty ? 'Save your changes first' : undefined} onclick={backupNow}>{running ? 'Backing up…' : 'Back up now'}</button>
    <span class="caption">{last ? `Last: ${new Date(last.created_at).toLocaleString()} · ${last.complete ? 'complete' : 'partial'}` : 'No backup yet'}</span>
  </div>
  {#if error}<p class="caption" style="margin:0;color:var(--danger)" role="alert">{error}</p>{/if}
</div>
{#if last}
  <div class="card stack" style="max-width:760px">
    <h2>Last backup</h2>
    <div class="list">
      <div class="list-row">
        <span class="dot {last.complete ? 'ok' : 'warn'}"></span>
        <span class="main-text grow"><span class="mono">{last.folder}</span><small>{last.complete ? `Complete · ${Object.keys(last.services).map((s) => s.replace('_', ' ')).join(', ')}` : `Partial · ${missing.join(', ')} not running`}</small></span>
      </div>
    </div>
  </div>
{/if}
