/* Voice in and out for the dashboard.

   In: the mic records a clip (push to talk), the gateway turns it into text, and the text is sent as
   a normal message, so everything else (delegation, spoken yes/no approvals, the timeline) is unchanged.
   Out: replies are read aloud when "read replies aloud" is on, one sentence at a time: the first sentence
   plays while the next is being prepared, and a reply that is still being written is read as it arrives.

   Both directions expose a Web Audio AnalyserNode so the particle field moves with the real sound.
   Audio is never stored: the recording goes to the PC's speech service and is discarded. */

import { ApiError } from '../api/http';
import { SentenceFeed, sentences } from '../ui/sentences';

export type VoiceMode = 'idle' | 'recording' | 'transcribing' | 'playing';

const HEADERS = { 'X-Thursday-Client': 'dashboard' };
const MAX_RECORD_MS = 120_000;

function readPref(): boolean {
  try {
    return localStorage.getItem('thursday.speakReplies') === '1';
  } catch {
    return false;
  }
}

async function problem(response: Response): Promise<ApiError> {
  let detail = '';
  try {
    const body = await response.json();
    detail = body.detail || body.title || '';
  } catch {
    /* not JSON */
  }
  return new ApiError(response.status, 'speech', detail || `Speech request failed (${response.status}).`);
}

class VoiceIO {
  available = $state(false);
  speakReplies = $state(readPref());
  mode = $state<VoiceMode>('idle');
  analyser = $state<AnalyserNode | null>(null);
  error = $state('');

  private context: AudioContext | null = null;
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];
  private limit: ReturnType<typeof setTimeout> | undefined;
  /** Settles when the recorder has stopped, whoever stopped it. */
  private ended: Promise<void> = Promise.resolve();
  private source: AudioBufferSourceNode | null = null;
  private queue: { text: string; audio: Promise<AudioBuffer | null> | null }[] = [];
  private feeds = new Map<string, SentenceFeed>(); // replies being read while they are still written
  private speaking = false;

  async init(): Promise<void> {
    try {
      const response = await fetch('/v1/speech');
      this.available = response.ok && (await response.json()).available === true && !!navigator.mediaDevices?.getUserMedia;
    } catch {
      this.available = false;
    }
  }

  setSpeakReplies(on: boolean): void {
    this.speakReplies = on;
    try {
      localStorage.setItem('thursday.speakReplies', on ? '1' : '0');
    } catch {
      /* kept for this session only */
    }
    if (on) void this.audio().resume(); // a click is the user gesture browsers need before playing sound
    else this.stopSpeaking();
  }

  private audio(): AudioContext {
    this.context ??= new AudioContext();
    return this.context;
  }

  private tap(node: AudioNode): void {
    const analyser = this.audio().createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.6;
    node.connect(analyser);
    this.analyser = analyser;
  }

  get sampleRate(): number {
    return this.context?.sampleRate ?? 48_000;
  }

  /* ---------- speech to text ---------- */

  async startRecording(): Promise<void> {
    if (this.mode !== 'idle' && this.mode !== 'playing') return;
    this.stopSpeaking();
    this.error = '';
    this.warm();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      this.error = 'Microphone access was blocked. Allow it for this page to talk to Thursday.';
      return;
    }
    await this.audio().resume();
    this.tap(this.audio().createMediaStreamSource(this.stream));
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    const recorder = this.recorder;
    this.ended = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
    this.recorder.start();
    this.mode = 'recording';
    // At the limit the recording ends and the microphone is let go; pressing stop then sends what was said.
    this.limit = setTimeout(() => {
      if (recorder.state === 'recording') recorder.stop();
      this.stream?.getTracks().forEach((track) => track.stop());
    }, MAX_RECORD_MS);
  }

  /** The microphone was pressed: the PC starts loading what the turn needs while you are still talking.
      Models that were unloaded after a break would otherwise make the first turn wait. */
  private warm(): void {
    void fetch('/v1/speech/warm', { method: 'POST', headers: { ...HEADERS, 'Content-Type': 'application/json' }, body: JSON.stringify({ speak: this.speakReplies }) }).catch(() => undefined);
  }

  /** A message was sent and its reply will be read aloud: the PC loads the voice while the reply is written. */
  warmVoice(): void {
    if (!this.wanted) return;
    void fetch('/v1/speech/warm', { method: 'POST', headers: { ...HEADERS, 'Content-Type': 'application/json' }, body: JSON.stringify({ speak: true, listen: false }) }).catch(() => undefined);
  }

  /** Stop recording and return what was said ('' when nothing was heard). */
  async stopRecording(): Promise<string> {
    const recorder = this.recorder;
    if (!recorder || this.mode !== 'recording') return '';
    clearTimeout(this.limit);
    if (recorder.state === 'recording') recorder.stop();
    await this.ended;
    const audio = new Blob(this.chunks, { type: recorder.mimeType || 'audio/webm' });
    this.releaseMic();
    this.mode = 'transcribing';
    try {
      const response = await fetch('/v1/speech/transcribe', { method: 'POST', headers: { ...HEADERS, 'Content-Type': audio.type }, body: audio });
      if (!response.ok) throw await problem(response);
      const text = String((await response.json()).text ?? '').trim();
      if (!text) this.error = 'I did not hear anything. Try again a little closer to the microphone.';
      return text;
    } catch (e) {
      this.error = e instanceof ApiError ? e.message : 'Cannot reach the speech service.';
      return '';
    } finally {
      this.mode = 'idle';
    }
  }

  cancelRecording(): void {
    if (this.mode !== 'recording') return;
    clearTimeout(this.limit);
    if (this.recorder) this.recorder.onstop = null;
    if (this.recorder?.state === 'recording') this.recorder.stop();
    this.releaseMic();
    this.mode = 'idle';
  }

  private releaseMic(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.recorder = null;
    this.analyser = null;
  }

  /* ---------- text to speech ---------- */

  private get wanted(): boolean {
    return this.speakReplies && this.available;
  }

  /** Read a whole reply aloud, sentence by sentence (behind anything still playing). Nothing unless the setting is on. */
  say(text: string): void {
    if (this.wanted) sentences(text).forEach((piece) => this.enqueue(piece));
  }

  /** Read a reply aloud while it is still being written: call with each new part of its text. */
  sayPart(replyId: string, part: string): void {
    if (!this.wanted) return;
    let feed = this.feeds.get(replyId);
    if (!feed) this.feeds.set(replyId, (feed = new SentenceFeed()));
    feed.push(part).forEach((piece) => this.enqueue(piece));
  }

  /** The reply is complete: read what is left of it. False when none of it came through `sayPart`. */
  sayEnd(replyId: string): boolean {
    const feed = this.feeds.get(replyId);
    if (!feed) return false;
    this.feeds.delete(replyId);
    feed.flush().forEach((piece) => this.enqueue(piece));
    return true;
  }

  stopSpeaking(): void {
    this.queue = [];
    this.feeds.clear();
    try {
      this.source?.stop();
    } catch {
      /* already stopped */
    }
  }

  private enqueue(text: string): void {
    this.queue.push({ text, audio: null });
    this.prepare();
    if (!this.speaking) void this.drain();
  }

  /** Have the audio of the piece that plays next, and of the one after it, on its way. */
  private prepare(): void {
    for (const item of this.queue.slice(0, 2)) item.audio ??= this.fetchAudio(item.text);
  }

  private async fetchAudio(text: string): Promise<AudioBuffer | null> {
    try {
      const response = await fetch('/v1/speech/speak', { method: 'POST', headers: { ...HEADERS, 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      if (response.status === 422) return null; // nothing in this piece that a voice can say
      if (!response.ok) throw await problem(response);
      return await this.audio().decodeAudioData(await response.arrayBuffer());
    } catch (e) {
      this.error = e instanceof ApiError ? e.message : 'Could not play the reply.';
      return null;
    }
  }

  private async drain(): Promise<void> {
    this.speaking = true;
    while (this.queue.length) {
      this.prepare();
      const item = this.queue[0];
      const buffer = await item.audio;
      if (this.queue[0] !== item) continue; // stopped while this piece was being made
      this.queue.shift();
      this.prepare(); // the piece after this one is made while this one plays
      if (!buffer || this.mode === 'recording' || this.mode === 'transcribing' || !this.speakReplies) continue; // the user started talking
      await this.play(buffer);
    }
    this.speaking = false;
    if (this.mode === 'playing') {
      this.mode = 'idle';
      this.analyser = null;
    }
  }

  private play(buffer: AudioBuffer): Promise<void> {
    return new Promise((resolve) => {
      const source = this.audio().createBufferSource();
      source.buffer = buffer;
      this.tap(source);
      source.connect(this.audio().destination);
      source.onended = () => {
        if (this.source === source) {
          this.source = null;
          // Between two sentences of one reply the voice is still speaking; it is idle once nothing is left.
          if (this.mode === 'playing' && !this.queue.length) {
            this.mode = 'idle';
            this.analyser = null;
          }
        }
        resolve();
      };
      this.source = source;
      this.mode = 'playing';
      source.start();
    });
  }
}

export const voiceIO = new VoiceIO();
