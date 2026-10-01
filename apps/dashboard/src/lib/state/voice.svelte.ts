/* Voice in and out for the dashboard.

   In: the mic records a clip (push to talk), the gateway turns it into text, and the text is sent as
   a normal message, so everything else (delegation, spoken yes/no approvals, the timeline) is unchanged.
   Out: replies are read aloud when "read replies aloud" is on.

   Both directions expose a Web Audio AnalyserNode so the particle field moves with the real sound.
   Audio is never stored: the recording goes to the PC's speech service and is discarded. */

import { ApiError } from '../api/http';

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
  private source: AudioBufferSourceNode | null = null;
  private queue: string[] = [];
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
    this.recorder.start();
    this.mode = 'recording';
    this.limit = setTimeout(() => this.recorder?.state === 'recording' && this.recorder.stop(), MAX_RECORD_MS);
  }

  /** Stop recording and return what was said ('' when nothing was heard). */
  async stopRecording(): Promise<string> {
    const recorder = this.recorder;
    if (!recorder || this.mode !== 'recording') return '';
    clearTimeout(this.limit);
    const done = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
    if (recorder.state === 'recording') recorder.stop();
    await done;
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

  /** Read a reply aloud (queued behind any reply still playing). Does nothing unless the setting is on. */
  say(text: string): void {
    if (!this.speakReplies || !this.available || !text.trim()) return;
    this.queue.push(text);
    if (!this.speaking) void this.drain();
  }

  stopSpeaking(): void {
    this.queue = [];
    try {
      this.source?.stop();
    } catch {
      /* already stopped */
    }
  }

  private async drain(): Promise<void> {
    this.speaking = true;
    while (this.queue.length) {
      const text = this.queue.shift()!;
      try {
        const response = await fetch('/v1/speech/speak', { method: 'POST', headers: { ...HEADERS, 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
        if (!response.ok) throw await problem(response);
        if (this.mode === 'recording' || this.mode === 'transcribing' || !this.speakReplies) continue; // the user started talking
        const buffer = await this.audio().decodeAudioData(await response.arrayBuffer());
        await this.play(buffer);
      } catch (e) {
        this.error = e instanceof ApiError ? e.message : 'Could not play the reply.';
      }
    }
    this.speaking = false;
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
          if (this.mode === 'playing') {
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
