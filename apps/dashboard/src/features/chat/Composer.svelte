<!-- The pill-shaped message bar. Enter sends, Shift+Enter adds a line. Drafts are kept per chat.
     The mic is push to talk: click to start, click again to send what you said (Escape cancels).
     The speaker button turns reading replies aloud on or off. The bolt (or a right-click on Send) switches this chat
     between the voice agent and sending straight to the main agent, word for word. -->
<script lang="ts">
  import { prefs } from '../../lib/state/prefs.svelte';
  import { voiceIO } from '../../lib/state/voice.svelte';
  import { tick } from 'svelte';
  import Icon from '../../lib/ui/Icon.svelte';

  let { chatId, direct, onsend, ondirect }: { chatId: string; direct: boolean; onsend: (text: string) => void; ondirect: (on: boolean) => void } = $props();

  let text = $state('');
  let box: HTMLTextAreaElement;
  let saveTimer: ReturnType<typeof setTimeout> | undefined;

  const recording = $derived(voiceIO.mode === 'recording');
  const transcribing = $derived(voiceIO.mode === 'transcribing');
  const placeholder = $derived(
    recording ? 'Listening… click the mic to send, Esc to cancel' : transcribing ? 'Writing down what you said…' : direct ? 'Message the main agent…' : 'Message Thursday…',
  );

  // The menu on the Send button: where this chat's messages go.
  let sendButton: HTMLButtonElement;
  let sendMenu = $state<HTMLDivElement>();
  let menuAt = $state<{ right: number; bottom: number } | null>(null);

  async function openMenu(event: MouseEvent) {
    event.preventDefault();
    const r = sendButton.getBoundingClientRect();
    menuAt = { right: Math.max(8, window.innerWidth - r.right), bottom: window.innerHeight - r.top + 8 };
    await tick();
    sendMenu?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
  }

  function closeMenu(returnFocus = true) {
    if (!menuAt) return;
    menuAt = null;
    if (returnFocus) sendButton?.focus();
  }

  function pick(on: boolean) {
    closeMenu();
    if (on !== direct) ondirect(on);
  }

  function menuKey(event: KeyboardEvent) {
    if (!menuAt) return;
    if (event.key === 'Escape') closeMenu();
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const items = [...(sendMenu?.querySelectorAll('button') ?? [])];
      const at = items.indexOf(document.activeElement as HTMLButtonElement);
      items[(at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    }
  }

  $effect(() => {
    text = prefs.draft(chatId);
    queueMicrotask(fit);
  });

  function fit() {
    if (!box) return;
    box.style.height = 'auto';
    box.style.height = `${Math.min(box.scrollHeight, 144)}px`;
  }

  function input() {
    fit();
    clearTimeout(saveTimer);
    const id = chatId;
    const value = text;
    saveTimer = setTimeout(() => prefs.saveDraft(id, value), 400);
  }

  function send() {
    const value = text.trim();
    if (!value || recording || transcribing) return;
    onsend(value);
    text = '';
    clearTimeout(saveTimer);
    prefs.saveDraft(chatId, '');
    queueMicrotask(fit);
    box.focus();
  }

  function key(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  }

  async function mic() {
    if (recording) {
      const heard = await voiceIO.stopRecording();
      if (heard) onsend(heard);
    } else if (!transcribing) {
      await voiceIO.startRecording();
    }
  }
</script>

<svelte:window
  onkeydown={(e) => {
    if (e.key === 'Escape' && recording) voiceIO.cancelRecording();
    menuKey(e);
  }}
  onclick={(e) => menuAt && !sendMenu?.contains(e.target as Node) && closeMenu(false)}
  onresize={() => (closeMenu(false), fit())}
/>

{#if voiceIO.error}
  <p class="caption voice-error" role="alert">{voiceIO.error}</p>
{/if}
<div class="composer">
  <button
    class="btn icon-btn mic"
    aria-pressed={recording}
    disabled={!voiceIO.available || transcribing}
    aria-label={recording ? 'Stop and send what you said' : 'Talk to Thursday'}
    title={voiceIO.available ? (recording ? 'Click to send' : 'Click, speak, click again to send') : 'Speech is not available: the speech service is not running'}
    onclick={mic}
  >
    <Icon name="mic" />
  </button>
  <textarea
    bind:this={box}
    bind:value={text}
    rows="1"
    maxlength="20000"
    {placeholder}
    title="Enter to send, Shift+Enter for a new line"
    aria-label="Message"
    disabled={recording || transcribing}
    oninput={input}
    onkeydown={key}
  ></textarea>
  {#if voiceIO.available}
    <button
      class="btn icon-btn speak"
      aria-pressed={voiceIO.speakReplies}
      aria-label="Read replies aloud"
      title={voiceIO.speakReplies ? 'Replies are read aloud. Click to turn off.' : 'Read replies aloud'}
      onclick={() => voiceIO.setSpeakReplies(!voiceIO.speakReplies)}
    >
      <Icon name={voiceIO.speakReplies ? 'speaker' : 'mute'} />
    </button>
  {/if}
  <button
    class="btn direct"
    aria-pressed={direct}
    aria-label="Send straight to the main agent"
    title={direct ? 'Direct: your messages go straight to the main agent, word for word. Click to go back to the voice agent.' : 'Send straight to the main agent, skipping the voice agent'}
    onclick={() => ondirect(!direct)}
  >
    <Icon name="direct" /><span class="direct-label">Direct</span>
  </button>
  <button
    bind:this={sendButton}
    class="btn primary icon-only"
    aria-label={direct ? 'Send to main agent' : 'Send'}
    aria-haspopup="menu"
    aria-expanded={menuAt !== null}
    title={direct ? 'Sends straight to the main agent. Right-click to change.' : 'Right-click to send straight to the main agent'}
    aria-disabled={!text.trim() || recording || transcribing}
    onclick={send}
    oncontextmenu={openMenu}
  >
    <Icon name="send" />
  </button>
</div>
{#if menuAt}
  <div bind:this={sendMenu} class="menu open" role="menu" aria-label="Where this chat sends" style:right="{menuAt.right}px" style:bottom="{menuAt.bottom}px" style:top="auto" style:left="auto">
    <button role="menuitemradio" aria-checked={!direct} onclick={() => pick(false)}><span class="check">{direct ? '' : '✓'}</span>Send to the voice agent</button>
    <button role="menuitemradio" aria-checked={direct} onclick={() => pick(true)}><span class="check">{direct ? '✓' : ''}</span>Send straight to the main agent</button>
  </div>
{/if}

<style>
  .voice-error { margin: 0; text-align: center; color: var(--danger); }
  .speak[aria-pressed='true'], .direct[aria-pressed='true'] { color: var(--accent-bright); }
  /* The Direct switch is a labelled pill; on a narrow app it shrinks to just the bolt. */
  .composer .btn.direct { display: inline-flex; align-items: center; gap: 6px; width: auto; padding: 0 14px; border-radius: 22px; font-size: var(--text-caption); }
  .composer .btn.direct[aria-pressed='true'] { background: var(--accent-fill); border-color: var(--accent); }
  @container app (max-width: 640px) {
    .direct-label { display: none; }
    .composer .btn.direct { width: 44px; padding: 0; border-radius: 50%; justify-content: center; }
  }
  .menu .check { width: 1.1em; color: var(--accent-bright); }
  .menu button[aria-checked='true'] { color: var(--accent-bright); }
</style>
