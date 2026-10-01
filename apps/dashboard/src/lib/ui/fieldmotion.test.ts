import { describe, expect, it } from 'vitest';
import { approach, BANDS, breeze, fieldLayout, headPose, mouthTargets, spectrumBands, speechBands } from './fieldmotion';

describe('voice field motion', () => {
  it('eases toward a target without overshooting, at its own speed up and down', () => {
    expect(approach(0, 1, 0, 10)).toBe(0);
    const up = approach(0, 1, 0.05, 30, 5);
    const down = approach(1, 0, 0.05, 30, 5);
    expect(up).toBeGreaterThan(0.7);
    expect(up).toBeLessThan(1);
    expect(1 - down).toBeLessThan(0.3); // falling is slower than rising
    expect(approach(0.4, 0.4, 1, 10)).toBe(0.4);
  });

  it('makes speech-like bands: bounded, loud in syllables, quiet between phrases', () => {
    const bands = new Float32Array(BANDS);
    let loudest = 0;
    let quietFrames = 0;
    for (let t = 0; t < 12; t += 1 / 60) {
      speechBands(t, 1, bands, () => 0.5);
      const peak = Math.max(...bands);
      expect(peak).toBeLessThanOrEqual(1);
      expect(Math.min(...bands)).toBeGreaterThanOrEqual(0);
      loudest = Math.max(loudest, peak);
      if (peak < 0.1) quietFrames++;
    }
    expect(loudest).toBeGreaterThan(0.8);
    expect(quietFrames).toBeGreaterThan(60); // pauses exist
    speechBands(3, 0, bands);
    expect(Math.max(...bands)).toBe(0);
  });

  it('reads speech bands out of a spectrum', () => {
    const spectrum = new Uint8Array(1024); // bins of about 23 Hz at 48 kHz
    const bands = new Float32Array(BANDS);
    spectrumBands(spectrum, 48_000, bands);
    expect(Math.max(...bands)).toBe(0);
    for (let bin = 8; bin < 14; bin++) spectrum[bin] = 255; // energy around 250 Hz
    spectrumBands(spectrum, 48_000, bands);
    const peak = bands.indexOf(Math.max(...bands));
    expect(peak).toBeGreaterThanOrEqual(2);
    expect(peak).toBeLessThanOrEqual(4);
    expect(bands[BANDS - 1]).toBe(0);
  });

  it('opens the mouth on low bands and spreads it on high bands', () => {
    const low = new Float32Array(BANDS).fill(0.5, 0, BANDS / 2);
    const high = new Float32Array(BANDS).fill(0.5, BANDS / 2);
    expect(mouthTargets(low).open).toBeGreaterThan(0.9);
    expect(mouthTargets(low).wide).toBe(0);
    expect(mouthTargets(high).open).toBe(0);
    expect(mouthTargets(high).wide).toBe(1);
    expect(mouthTargets(new Float32Array(BANDS))).toEqual({ open: 0, wide: 0 });
  });

  it('holds the head differently in each state, always within a small turn', () => {
    const none = { listen: 0, think: 0, speak: 0 };
    expect(headPose(none, 5, 0)).toEqual({ yaw: 0, pitch: 0 });
    for (let t = 0; t < 30; t += 0.1) {
      for (const mix of [{ ...none, listen: 1 }, { ...none, think: 1 }, { ...none, speak: 1 }]) {
        const pose = headPose(mix, t, 1);
        expect(Math.abs(pose.yaw)).toBeLessThan(0.25); // under 15 degrees: the back of the head is never needed
        expect(Math.abs(pose.pitch)).toBeLessThan(0.15);
      }
    }
    expect(headPose({ ...none, think: 1 }, 0, 0).pitch).toBeLessThan(0); // chin up while thinking
    expect(headPose({ ...none, listen: 1 }, 0, 0).pitch).toBeGreaterThan(0); // leaning in while listening
    // While speaking the head only sways slowly: loudness does not move it.
    expect(headPose({ ...none, speak: 1 }, 2, 1)).toEqual(headPose({ ...none, speak: 1 }, 2, 0));
    expect(Math.abs(headPose({ ...none, speak: 1 }, 2.1, 0).yaw - headPose({ ...none, speak: 1 }, 2, 0).yaw)).toBeLessThan(0.01);
  });

  it('blows a mild, steady breeze to the right and a little upward', () => {
    for (let t = 0; t < 120; t += 0.5) {
      const wind = breeze(t);
      expect(Math.hypot(wind.x, wind.y)).toBeCloseTo(1, 6);
      expect(wind.x).toBeGreaterThan(0.85); // always mostly to the right
      expect(wind.y).toBeLessThan(0); // and upward (y grows downward)
      expect(wind.strength).toBeGreaterThanOrEqual(0.5);
      expect(wind.strength).toBeLessThanOrEqual(1);
      const next = breeze(t + 1 / 60);
      expect(Math.abs(next.strength - wind.strength)).toBeLessThan(0.01); // gusts are soft
    }
    expect(breeze(10, 1).y).toBeLessThan(breeze(10, 0).y); // lifts while thinking
  });

  it('fits the face above the line on any screen', () => {
    for (const [width, height] of [[360, 520], [820, 700], [1600, 1300], [300, 180]]) {
      const layout = fieldLayout(width, height);
      expect(layout.lineHeight).toBeLessThanOrEqual(height);
      expect(layout.cx).toBe(width / 2);
      expect(layout.scale * 2.4).toBeLessThanOrEqual(height); // the face is about 2.4 units tall
      expect(layout.scale * 2 * 1.4).toBeLessThanOrEqual(width * 0.8); // and not wider than the canvas
      expect(layout.lineCount).toBeGreaterThanOrEqual(90);
      expect(layout.lineCount).toBeLessThanOrEqual(280);
    }
    expect(fieldLayout(1600, 1300).scale).toBe(280); // capped on large screens
  });
});
