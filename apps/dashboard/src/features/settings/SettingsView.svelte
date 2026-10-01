<script lang="ts">
  import { errorText } from '../../lib/state/app.svelte';
  import { router } from '../../lib/state/router.svelte';
  import { SETTINGS_TABS, type SettingsTab } from '../../lib/state/routes';
  import { ui } from '../../lib/state/ui.svelte';
  import AgentsTab from './AgentsTab.svelte';
  import AppearanceTab from './AppearanceTab.svelte';
  import BackupTab from './BackupTab.svelte';
  import DevicesTab from './DevicesTab.svelte';
  import GeneralTab from './GeneralTab.svelte';
  import PromptsTab from './PromptsTab.svelte';
  import { SaveBar } from './savebar.svelte';

  let { tab }: { tab: SettingsTab } = $props();

  const bar = new SaveBar();
  const LABEL: Record<SettingsTab, string> = { agents: 'Agents', prompts: 'Prompts', devices: 'Devices', backup: 'Backup', general: 'General', appearance: 'Appearance' };

  async function pick(next: SettingsTab) {
    if (bar.dirty && !(await ui.ask({ title: 'Discard changes?', body: 'You have unsaved changes on this tab.', action: 'Discard', danger: true }))) return;
    router.go({ name: 'settings', tab: next }, true);
  }

  function key(event: KeyboardEvent) {
    const at = SETTINGS_TABS.indexOf(tab);
    if (event.key === 'ArrowRight') pick(SETTINGS_TABS[(at + 1) % SETTINGS_TABS.length]);
    if (event.key === 'ArrowLeft') pick(SETTINGS_TABS[(at - 1 + SETTINGS_TABS.length) % SETTINGS_TABS.length]);
  }

  async function save() {
    bar.saving = true;
    bar.error = '';
    try {
      await bar.save();
    } catch (e) {
      bar.error = errorText(e);
    } finally {
      bar.saving = false;
    }
  }
</script>

<svelte:window onbeforeunload={(e) => bar.dirty && e.preventDefault()} />

<section class="view page on" aria-label="Settings">
  <div class="tabs" role="tablist" tabindex="-1" onkeydown={key}>
    {#each SETTINGS_TABS as t (t)}
      <button class="tab" role="tab" id="tab-{t}" aria-selected={tab === t} aria-controls="panel-{t}" tabindex={tab === t ? 0 : -1} onclick={() => pick(t)}>{LABEL[t]}</button>
    {/each}
  </div>
  <div class="tabpanel on" role="tabpanel" id="panel-{tab}" aria-labelledby="tab-{tab}">
    {#key tab}
      {#if tab === 'agents'}<AgentsTab {bar} />
      {:else if tab === 'prompts'}<PromptsTab />
      {:else if tab === 'devices'}<DevicesTab />
      {:else if tab === 'backup'}<BackupTab {bar} />
      {:else if tab === 'general'}<GeneralTab {bar} />
      {:else}<AppearanceTab />{/if}
    {/key}
  </div>
</section>
{#if bar.dirty}
  <div class="savebar">
    <span class="grow caption" role="status">{bar.error || 'You have unsaved changes.'}</span>
    <button class="btn plain" disabled={bar.saving} onclick={() => bar.discard()}>Discard</button>
    <button class="btn primary" disabled={bar.saving} onclick={save}>{bar.saving ? 'Saving…' : 'Save changes'}</button>
  </div>
{/if}
