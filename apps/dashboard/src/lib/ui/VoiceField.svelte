<script lang="ts">
  import { VoiceFieldEngine, type FieldParts, type FieldState } from './voicefield';

  let {
    state,
    analyser = null,
    sampleRate = 48_000,
    face = true,
    lineCentre = null,
    parts = 'both',
  }: {
    state: FieldState;
    analyser?: AnalyserNode | null;
    sampleRate?: number;
    face?: boolean;
    /** How far above the bottom of the field the middle of the particle line runs; null rests it on the bottom. */
    lineCentre?: number | null;
    /** What this canvas shows: a chat puts the face behind its messages and the line over them, on two canvases. */
    parts?: FieldParts;
  } = $props();

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
      engine = new VoiceFieldEngine(canvas, parts);
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

  $effect(() => {
    engine?.setLineCentre(lineCentre);
  });

  // Real sound (the microphone, or a reply being read aloud) drives the particles when there is some.
  $effect(() => {
    engine?.setAnalyser(analyser, sampleRate);
  });
</script>

<canvas bind:this={canvas} class="voicefield" class:line={parts === 'line'} aria-hidden="true"></canvas>
{#if parts !== 'line'}<span class="voice-state" role="status" aria-live="polite">{SAY[state]}</span>{/if}
