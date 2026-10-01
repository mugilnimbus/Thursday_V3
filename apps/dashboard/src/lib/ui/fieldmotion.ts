/* The numbers behind the voice field's movement, kept apart from the drawing so they can be tested:
   audio bands, easing, where things sit on the canvas, and how the head is held in each state. */

export type FieldState = 'idle' | 'listening' | 'thinking' | 'speaking';

export const BANDS = 12;

/** How strongly each state shows, 0..1. They cross-fade, so a change of state has no jump. */
export interface StateMix {
  listen: number;
  think: number;
  speak: number;
}

/** Move `from` toward `to`; `up` and `down` are speeds per second for rising and falling. */
export function approach(from: number, to: number, dt: number, up: number, down = up): number {
  return from + (to - from) * (1 - Math.exp(-dt * (to > from ? up : down)));
}

/** Speech-like bands when there is no real audio: syllables, pauses between phrases, and moving formants. */
export function speechBands(t: number, loud: number, out: Float32Array, random: () => number = Math.random): void {
  const syllable = Math.max(0, Math.sin(t * 23.2 + Math.sin(t * 1.3) * 2)) ** 0.7;
  const phrase = (Math.sin(t * 0.9) + Math.sin(t * 2.3) * 0.3 + 1) / 2 > 0.12 ? 1 : 0.08;
  const envelope = syllable * phrase * loud;
  const f1 = 2 + Math.sin(t * 2.1) * 1.5;
  const f2 = 6.5 + Math.sin(t * 1.7 + 1) * 2.2;
  for (let i = 0; i < out.length; i++) {
    const shape = Math.exp(-((i - f1) ** 2) / 3) + 0.7 * Math.exp(-((i - f2) ** 2) / 4) + 0.12;
    out[i] = Math.min(1, envelope * shape * (0.8 + random() * 0.4));
  }
}

/** Log-spaced bands from 90 Hz to about 4 kHz, where speech lives, from an analyser's byte spectrum. */
export function spectrumBands(spectrum: Uint8Array, sampleRate: number, out: Float32Array): void {
  const binHz = sampleRate / 2 / spectrum.length;
  for (let i = 0; i < out.length; i++) {
    const low = 90 * 45 ** (i / out.length);
    const high = 90 * 45 ** ((i + 1) / out.length);
    let sum = 0;
    let n = 0;
    for (let bin = Math.floor(low / binHz); bin <= Math.ceil(high / binHz) && bin < spectrum.length; bin++) {
      sum += spectrum[bin];
      n++;
    }
    out[i] = Math.max(0, Math.min(1, ((n ? sum / n : 0) / 255 - 0.18) * 2.2));
  }
}

/** The mouth from the bands: low bands (vowels) open the jaw, high bands (s, ee) spread the lips. */
export function mouthTargets(bands: Float32Array): { open: number; wide: number } {
  const half = bands.length / 2;
  let low = 0;
  let high = 0;
  for (let i = 0; i < bands.length; i++) {
    if (i < half) low += bands[i];
    else high += bands[i];
  }
  return { open: Math.min(1, (low / half) * 1.9), wide: Math.min(1, (high / half) * 2.4) };
}

/** How the head is held, in radians. Yaw turns it left and right, pitch tips it (positive looks down). */
export function headPose(mix: StateMix, t: number, level: number): { yaw: number; pitch: number } {
  // Thinking: slow, wide looks to the side, chin a little up. Speaking: a calm, slow sway; the head does not
  // bob with the words. Listening: turned and leaning slightly toward you, nodding gently when you are loud.
  const yaw =
    mix.think * Math.sin(t * 0.45) * 0.2 +
    mix.speak * Math.sin(t * 0.55) * 0.1 +
    mix.listen * (0.09 + Math.sin(t * 0.5) * 0.05);
  const pitch =
    mix.think * (-0.07 + Math.sin(t * 0.6) * 0.04) +
    mix.speak * Math.sin(t * 0.7 + 1) * 0.03 +
    mix.listen * (0.06 + level * 0.05);
  return { yaw, pitch };
}

/** The mild breeze that carries loose particles: a direction (unit vector, y down) and a strength around 1.
    It blows to the right and a little upward, wanders slowly, comes in soft gusts, and lifts while thinking. */
export function breeze(t: number, think = 0): { x: number; y: number; strength: number } {
  const angle = -0.26 + 0.2 * Math.sin(t * 0.09) - think * 0.3;
  return { x: Math.cos(angle), y: Math.sin(angle), strength: 0.75 + 0.25 * Math.sin(t * 0.31 + 1.7 * Math.sin(t * 0.13)) };
}

export interface FieldLayout {
  /** Height of the band along the bottom where the line lives. */
  lineHeight: number;
  /** How many particles make up the line. */
  lineCount: number;
  /** Pixels per face unit; the face is about 2.4 units tall. */
  scale: number;
  /** Centre of the face. */
  cx: number;
  cy: number;
}

export function fieldLayout(width: number, height: number): FieldLayout {
  const lineHeight = Math.min(height, Math.max(64, Math.min(104, 44 + width * 0.032)));
  const scale = Math.max(1, Math.min(280, (height - lineHeight * 0.5) * 0.31, width * 0.28));
  return {
    lineHeight,
    lineCount: Math.round(Math.min(280, Math.max(90, width / 3))),
    scale,
    cx: width / 2,
    cy: Math.max(scale * 1.45, (height - lineHeight * 0.6) * 0.5),
  };
}
