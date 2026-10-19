<!-- A chat: the thread (messages, task cards, approvals), the voice agent's particle field, the
     telemetry subtitle, and the message bar. Stays pinned to the newest item unless you scroll up. -->
<script lang="ts">
  import { tick } from 'svelte';
  import { app, clockTime } from '../../lib/state/app.svelte';
  import type { ChatSession } from '../../lib/state/chat.svelte';
  import { prefs } from '../../lib/state/prefs.svelte';
  import { voiceIO } from '../../lib/state/voice.svelte';
  import Icon from '../../lib/ui/Icon.svelte';
  import Markdown from '../../lib/ui/Markdown.svelte';
  import CopyButton from '../../lib/ui/CopyButton.svelte';
  import VoiceField from '../../lib/ui/VoiceField.svelte';
  import ApprovalCard from './ApprovalCard.svelte';
  import Composer from './Composer.svelte';
  import TaskCard from './TaskCard.svelte';
  import Telemetry from './Telemetry.svelte';

  let { session }: { session: ChatSession } = $props();

  let thread: HTMLDivElement;
  let view: HTMLElement;
  let pinned = true;
  let lineCentre = $state<number | null>(null);

  const found = $derived(app.chat(session.chatId));
  const approvals = $derived(app.approvals.filter((a) => a.chat_id === session.chatId));
  const taskIds = $derived(new Set(session.tasks.keys()));
  const orphans = $derived(approvals.filter((a) => !taskIds.has(a.task_id)));
  const replies = $derived(Object.entries(session.replies));
  const voiceDown = $derived(app.status?.voice_agent === false);
  const direct = $derived(found?.chat.direct ?? false);

  // The particle field shows the microphone while you talk and the reply while it is read aloud.
  const fieldState = $derived(voiceIO.mode === 'recording' ? 'listening' : voiceIO.mode === 'playing' ? 'speaking' : voiceIO.mode === 'transcribing' ? 'thinking' : session.voice);

  $effect(() => {
    // A reply is read as it is written; one that arrives whole (a task's result) is read once it is here.
    session.onReplyPart = (id, part) => voiceIO.sayPart(id, part);
    session.onReply = (text, id) => {
      if (!(id && voiceIO.sayEnd(id))) voiceIO.say(text);
    };
    return () => {
      session.onReply = null;
      session.onReplyPart = null;
      voiceIO.cancelRecording();
      voiceIO.stopSpeaking();
    };
  });

  // The particle line runs along the status line, which sits on the message box: wherever the box's height puts
  // the status line, the field is told how far above its own bottom that is.
  $effect(() => {
    const status = view.querySelector<HTMLElement>('.telemetry');
    const field = view.querySelector<HTMLElement>('.voicefield');
    const box = view.querySelector<HTMLElement>('.composer');
    if (!status || !field || !box) return;
    const measure = () => {
      const line = status.getBoundingClientRect();
      lineCentre = Math.round(field.getBoundingClientRect().bottom - (line.top + line.height / 2));
    };
    const observer = new ResizeObserver(measure);
    for (const element of [view, status, box]) observer.observe(element);
    measure();
    return () => observer.disconnect();
  });

  function onScroll() {
    pinned = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
  }

  // Follow new content while pinned to the bottom.
  $effect(() => {
    void [session.items.length, session.outgoing.length, replies.map(([, t]) => t.length).join(), approvals.length, session.voice];
    if (pinned) tick().then(() => thread && (thread.scrollTop = thread.scrollHeight));
  });

  // Messages that could not reach the gateway go out again once the stream is back.
  $effect(() => {
    if (app.connection === 'live') session.retryUnsent();
  });

  function outgoingMeta(status: string, error: string, straight: boolean): string {
    const tag = straight ? ' · direct' : '';
    switch (status) {
      case 'sending':
        return `Sending…${tag}`;
      case 'queued':
        return (voiceDown ? 'Queued · sends when the voice agent is back' : 'Queued') + tag;
      case 'delivered':
        return `Delivered${tag}`;
      case 'unsent':
        return 'Not sent · cannot reach Thursday';
      default:
        return `Failed · ${error || (straight ? 'the main agent refused it' : 'the voice agent refused it')}`;
    }
  }
</script>

<section class="view chat on" aria-label="Chat" bind:this={view} style:--line-centre={lineCentre === null ? null : `${lineCentre}px`}>
  <div class="thread" bind:this={thread} onscroll={onScroll} aria-live="polite">
    {#each app.banners as banner (banner.code)}
      <div class="banner" role="alert"><Icon name="alert" /><span class="grow">{banner.text}</span></div>
    {/each}

    {#if session.loading}
      <div class="stack" aria-label="Loading"><div class="skeleton"></div><div class="skeleton" style="width:70%"></div><div class="skeleton" style="width:40%"></div></div>
    {:else if session.error}
      <div class="card stack">
        <h3>Could not load this chat</h3>
        <p class="muted-text" style="margin:0">{session.error}</p>
        <div><button class="btn" onclick={() => session.load()}>Retry now</button></div>
      </div>
    {:else}
      {#if session.hasEarlier}
        <button class="btn plain" style="justify-self:center;min-height:32px" onclick={() => ((pinned = false), session.loadEarlier())}>Show earlier messages</button>
      {/if}
      {#if !session.items.length && !session.outgoing.length}
        <div class="empty">
          <Icon name="chat" />
          <div class="title">Start with what you want done</div>
          <p class="muted-text" style="margin:0">For example: “List the files in this project and tell me what it is.”</p>
        </div>
      {/if}
      {#each session.items as item (item.key)}
        {#if item.kind === 'message'}
          <div class="msg" class:user={item.message.role === 'user'}>
            {#if item.message.role === 'user'}{item.message.text}{:else}<Markdown text={item.message.text} />{/if}<span class="meta">{item.message.role === 'user' ? (item.message.direct ? 'You · direct' : 'You') : 'Voice agent'} · {clockTime(item.message.created_at)}<CopyButton text={item.message.text} /></span>
          </div>
        {:else}
          <TaskCard task={item.task} />
          {#each approvals.filter((a) => a.task_id === item.task.taskId) as approval (approval.approval_id)}
            <ApprovalCard {approval} project={found?.project.name ?? 'this project'} instruction={item.task.instruction} />
          {/each}
        {/if}
      {/each}
      {#each orphans as approval (approval.approval_id)}
        <ApprovalCard {approval} project={found?.project.name ?? 'this project'} instruction="" />
      {/each}
      {#each session.outgoing as out (out.clientMessageId)}
        <div class="msg user">
          {out.text}<span class="meta">{outgoingMeta(out.status, out.error, out.direct)}<CopyButton text={out.text} /></span>
          {#if out.status === 'unsent' || out.status === 'failed'}
            <button class="btn sm" style="margin-top:6px" onclick={() => session.retry(out.clientMessageId)}>Retry</button>
          {/if}
        </div>
      {/each}
      {#each replies as [id, text] (id)}
        <div class="msg"><Markdown {text} /><span class="caret"></span><span class="meta">Voice agent · replying</span></div>
      {/each}
      {#if session.voice === 'thinking' && !replies.length}
        <div class="msg"><span class="typing" aria-label="Voice agent is thinking"><i></i><i></i><i></i></span></div>
      {/if}
    {/if}
  </div>
  <!-- The face lies behind the messages; the particle line is drawn over them and lets them show through. -->
  <VoiceField state={fieldState} analyser={voiceIO.analyser} sampleRate={voiceIO.sampleRate} face={prefs.voiceFace} {lineCentre} parts="face" />
  <VoiceField state={fieldState} analyser={voiceIO.analyser} sampleRate={voiceIO.sampleRate} {lineCentre} parts="line" />
  <Telemetry {session} />
  <Composer
    chatId={session.chatId}
    {direct}
    onsend={(text) => ((pinned = true), voiceIO.warmVoice(), session.send(text))}
    ondirect={(on) => app.setChatDirect(session.chatId, on)}
  />
</section>
