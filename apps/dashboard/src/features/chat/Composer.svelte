<!-- The pill-shaped message bar. Enter sends, Shift+Enter adds a line. Drafts are kept per chat.
     The mic is push to talk: click to start, click again to send what you said (Escape cancels).
     The speaker button turns reading replies aloud on or off. -->
<script lang="ts">
  import { prefs } from '../../lib/state/prefs.svelte';
  import { voiceIO } from '../../lib/state/voice.svelte';
  import Icon from '../../lib/ui/Icon.svelte';

  let { chatId, onsend }: { chatId: string; onsend: (text: string) => void } = $props();

  let text = $state('');
  let box: HTMLTextAreaElement;
  let saveTimer: ReturnType<typeof setTimeout> | undefined;

  const recording = $derived(voiceIO.mode === 'recording');
  const transcribing = $derived(voiceIO.mode === 'transcribing');
  const placeholder = $derived(recording ? 'Listening… click the mic to send, Esc to cancel' : transcribing ? 'Writing down what you said…' : 'Message Thursday…');

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
    if (!value) return;
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

<svelte:window onkeydown={(e) => e.key === 'Escape' && recording && voiceIO.cancelRecording()} />

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
  <button class="btn primary icon-only" aria-label="Send" disabled={!text.trim() || recording || transcribing} onclick={send}><Icon name="send" /></button>
</div>

<style>
  .voice-error { margin: 0; text-align: center; color: var(--danger); }
  .speak[aria-pressed='true'] { color: var(--accent-bright); }
</style>
