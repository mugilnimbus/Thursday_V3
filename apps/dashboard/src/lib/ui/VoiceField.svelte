<script lang="ts">
  import { VoiceFieldEngine, type FieldState } from './voicefield';

  let { state, analyser = null, sampleRate = 48_000, face = true }: { state: FieldState; analyser?: AnalyserNode | null; sampleRate?: number; face?: boolean } = $props();

  let canvas: HTMLCanvasElement;
  let engine: VoiceFieldEngine | null = null;
  const SAY: Record<FieldState, string> = {
    idle: '',
    listening: 'Listening',
    thinking: 'Voice agent is thinking',
    speaking: 'Voice agent is replying',
  };

  $effect(() => {
    try {
      engine = new VoiceFieldEngine(canvas);
    } catch {
      engine = null; // no WebGL: the text states still work
    }
    return () => engine?.destroy();
  });

  $effect(() => {
    engine?.set(state);
  });

  $effect(() => {
    engine?.setFace(face);
  });

  // Real sound (the microphone, or a reply being read aloud) drives the particles when there is some.
  $effect(() => {
    engine?.setAnalyser(analyser, sampleRate);
  });
</script>

<canvas bind:this={canvas} class="voicefield" aria-hidden="true"></canvas>
<span class="voice-state" role="status" aria-live="polite">{SAY[state]}</span>
