/* Voice agent presence: particles that form a face and move with the audio.

   The line along the bottom is always there: a ribbon of particles that a mild breeze carries to the right
   in slow waves. With sound it pulses: each particle takes the loudness of the tone at its place along the
   line (low tones on the left, high on the right), so the line shows both how loud and how high the sound is.

   The face (which setFace turns off) gathers while the agent listens, thinks or speaks.
   Listening: greens and blues, turned and leaning slightly toward you; its surface ripples with your voice.
   Thinking: indigo, violet and magenta, eyes closed, looking slowly from side to side, with a glow moving
     up it.
   Speaking: cyan through violet and pink to a warm orange; the jaw and lips follow the audio (low bands
     open the mouth, high bands spread it) while the head stays calm.
   Loose particles around the head are carried off on the breeze, fade, and start again. The face arrives
   on that breeze and, going back to idle, is blown away by it, the downwind side first. Colours drift
   slowly across the face.

   The face is a cloud of about 19,000 particles (facecloud.ts) drawn in one WebGL call: every particle's
   position, brightness and colour is worked out on the GPU from a handful of numbers set each frame
   (fieldmotion.ts), so the cost does not depend on how lively the animation is. The canvas is see-through
   and sits behind the messages.

   Audio comes from a Web Audio AnalyserNode when one is attached (the microphone while listening, the
   voice agent's speech while speaking); otherwise a speech-like envelope drives it.

   Rendering stops while the canvas is off screen or the tab is hidden, and draws single still frames for
   people who ask for reduced motion. */

import { loadFaceCloud, RECORD_BYTES, type FaceCloud } from './facecloud';
import { approach, BANDS, breeze, fieldLayout, headPose, mouthTargets, spectrumBands, speechBands, type FieldState, type StateMix } from './fieldmotion';
import { FRAGMENT, UNIFORMS, VERTEX, type UniformName } from './fieldshaders';

export type { FieldState } from './fieldmotion';

/** Particles of the line that exist before (or without) the face. */
const LINE_PARTICLES = 280;
/** On small or slow devices the face uses this many particles at most. */
const SMALL_SCREEN_PARTICLES = 9000;
const RANDOM_FLOATS = 8;

/** Small seeded generator, so the line looks the same on every load. */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type FieldParts = 'both' | 'face' | 'line';

export class VoiceFieldEngine {
  private gl: WebGLRenderingContext;
  private program: WebGLProgram | null = null;
  private uniforms = {} as Record<UniformName, WebGLUniformLocation | null>;
  private buffers: WebGLBuffer[] = [];
  private cloud: FaceCloud | null = null;
  private count = 0; // particles on the GPU
  private bands = new Float32Array(BANDS);
  private target = new Float32Array(BANDS);
  private mix: StateMix = { listen: 0, think: 0, speak: 0 };
  private faceMix = 0;
  private side = -1; // the face comes in from upwind (-1) or is blown away downwind (1)
  private faceEnabled = true;
  private drift = 0; // how far the breeze has carried the line, in screen widths
  private mouthOpen = 0;
  private mouthWide = 0;
  private clock = 0; // seconds of animation; stands still while nothing is drawn
  private backdrop = ''; // the CSS background behind the face on a light page
  private width = 0;
  private height = 0;
  private dpr = 1;
  private state: FieldState = 'idle';
  private raf = 0;
  private visible = true;
  private lineCentre: number | null = null;
  private last = 0;
  private dead = false;
  private analyser: { node: AnalyserNode; data: Uint8Array<ArrayBuffer>; rate: number } | null = null;
  private reduce = matchMedia('(prefers-reduced-motion: reduce)');
  private resizeObserver: ResizeObserver;
  private intersection: IntersectionObserver;
  private readonly onVisibility = () => this.kick();
  private readonly onLost = (event: Event) => {
    event.preventDefault(); // allow the context to come back
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.program = null;
  };
  private readonly onRestored = () => {
    this.build();
    this.kick();
  };

  /** `parts` says what this canvas shows. A chat uses two: the face behind the messages, the line over them. */
  constructor(
    private canvas: HTMLCanvasElement,
    private parts: FieldParts = 'both',
  ) {
    const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false });
    if (!gl) throw new Error('WebGL is not available');
    this.gl = gl;
    canvas.addEventListener('webglcontextlost', this.onLost);
    canvas.addEventListener('webglcontextrestored', this.onRestored);
    this.build();
    this.resizeObserver = new ResizeObserver(() => {
      this.resize();
      this.kick();
    });
    this.resizeObserver.observe(canvas);
    this.intersection = new IntersectionObserver(([entry]) => {
      this.visible = entry.isIntersecting;
      if (this.visible) this.kick();
    });
    this.intersection.observe(canvas);
    document.addEventListener('visibilitychange', this.onVisibility);
    // The line works at once; the face joins when its file has arrived. Without it, the line carries on alone.
    if (parts === 'line') return;
    loadFaceCloud().then(
      (cloud) => {
        if (this.dead) return;
        this.cloud = cloud;
        if (this.program) this.upload();
        this.kick();
      },
      () => undefined,
    );
  }

  destroy(): void {
    this.dead = true;
    cancelAnimationFrame(this.raf);
    this.resizeObserver.disconnect();
    this.intersection.disconnect();
    document.removeEventListener('visibilitychange', this.onVisibility);
    this.canvas.removeEventListener('webglcontextlost', this.onLost);
    this.canvas.removeEventListener('webglcontextrestored', this.onRestored);
    for (const buffer of this.buffers) this.gl.deleteBuffer(buffer);
    if (this.program) this.gl.deleteProgram(this.program);
  }

  set(state: FieldState): void {
    this.state = state;
    this.kick();
  }

  /** Show or hide the face. The line stays either way. */
  setFace(enabled: boolean): void {
    this.faceEnabled = enabled;
    this.kick();
  }

  /** Where the line runs: how far its middle is above the bottom of the field (null: resting on the bottom). */
  setLineCentre(pixels: number | null): void {
    this.lineCentre = pixels;
    this.kick();
  }

  /** Attach live audio (or null to fall back to the built-in speech envelope). */
  setAnalyser(node: AnalyserNode | null, sampleRate = 48_000): void {
    this.analyser = node ? { node, data: new Uint8Array(new ArrayBuffer(node.frequencyBinCount)), rate: sampleRate } : null;
  }

  /** Compile the shaders and (re)create everything that lives on the GPU. */
  private build(): void {
    const gl = this.gl;
    const shader = (type: number, source: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, source);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) throw new Error(`voice field shader: ${gl.getShaderInfoLog(s)}`);
      return s;
    };
    const program = gl.createProgram()!;
    gl.attachShader(program, shader(gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(program, shader(gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS) && !gl.isContextLost()) throw new Error(`voice field program: ${gl.getProgramInfoLog(program)}`);
    gl.useProgram(program);
    this.program = program;
    for (const name of UNIFORMS) this.uniforms[name] = gl.getUniformLocation(program, name);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.clearColor(0, 0, 0, 0);
    this.upload();
    this.resize();
  }

  /** Put the particles on the GPU: the face's records as they are, plus a few random numbers for each. */
  private upload(): void {
    const gl = this.gl;
    const program = this.program!;
    for (const buffer of this.buffers) gl.deleteBuffer(buffer);
    this.count = this.cloud?.count ?? LINE_PARTICLES;
    const records = this.cloud?.records ?? new Uint8Array(this.count * RECORD_BYTES);
    const random = seeded(3);
    const rand = new Float32Array(this.count * RANDOM_FLOATS);
    for (let i = 0; i < this.count; i++) {
      rand.set([i, random(), random() * 6.283, 0.6 + random() * 0.8, 0.6 + random() * 1.5, random() * 2 - 1, i % BANDS, random()], i * RANDOM_FLOATS);
    }
    const attribute = (name: string, size: number, type: number, normalized: boolean, stride: number, offset: number) => {
      const location = gl.getAttribLocation(program, name);
      if (location < 0) return;
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, size, type, normalized, stride, offset);
    };
    const face = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, face);
    gl.bufferData(gl.ARRAY_BUFFER, records, gl.STATIC_DRAW);
    attribute('aPos', 3, gl.SHORT, true, RECORD_BYTES, 0);
    attribute('aLook', 4, gl.UNSIGNED_BYTE, true, RECORD_BYTES, 6);
    attribute('aNormal', 2, gl.BYTE, true, RECORD_BYTES, 10);
    const extra = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, extra);
    gl.bufferData(gl.ARRAY_BUFFER, rand, gl.STATIC_DRAW);
    attribute('aRand', 4, gl.FLOAT, false, RANDOM_FLOATS * 4, 0);
    attribute('aMore', 4, gl.FLOAT, false, RANDOM_FLOATS * 4, 16);
    this.buffers = [face, extra];
  }

  private resize(): void {
    this.dpr = Math.min(2, devicePixelRatio || 1);
    this.width = this.canvas.clientWidth;
    this.height = this.canvas.clientHeight;
    if (!this.width || !this.height) return;
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
    this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
  }

  private kick(): void {
    if (!this.raf && this.visible && !document.hidden && this.program) this.raf = requestAnimationFrame((now) => this.frame(now));
  }

  private frame(now: number): void {
    this.raf = 0;
    const { gl, state, uniforms: u } = this;
    if (!this.visible || document.hidden || !this.width || !this.program || gl.isContextLost()) return;
    const still = this.reduce.matches; // reduced motion: jump to the new state and draw one frame
    const dt = still ? 1 : Math.min(0.05, (now - (this.last || now)) / 1000);
    this.last = now;
    if (!still) this.clock += dt;
    const t = this.clock;

    // Audio bands: fast attack, slow release.
    if (!still && (state === 'speaking' || state === 'listening')) {
      if (this.analyser) {
        this.analyser.node.getByteFrequencyData(this.analyser.data);
        spectrumBands(this.analyser.data, this.analyser.rate, this.target);
      } else speechBands(state === 'listening' ? t * 0.8 : t, state === 'listening' ? 0.7 : 1, this.target);
    } else this.target.fill(0);
    let level = 0;
    for (let i = 0; i < BANDS; i++) {
      const d = this.target[i] - this.bands[i];
      this.bands[i] += d * (d > 0 ? 0.55 : 0.14);
      level += this.bands[i] / BANDS;
    }

    // States cross-fade; the face arrives on the breeze over a couple of seconds and leaves the same way.
    const mix = this.mix;
    mix.listen = approach(mix.listen, state === 'listening' ? 1 : 0, dt, 5);
    mix.think = approach(mix.think, state === 'thinking' ? 1 : 0, dt, 5);
    mix.speak = approach(mix.speak, state === 'speaking' ? 1 : 0, dt, 5);
    const faceOn = this.parts !== 'line' && this.faceEnabled && state !== 'idle' && this.cloud !== null;
    if (this.faceMix <= 0 && faceOn) this.side = -1;
    else if (this.faceMix >= 1 && !faceOn) this.side = 1;
    this.faceMix = still ? (faceOn ? 1 : 0) : Math.min(1, Math.max(0, this.faceMix + (faceOn ? dt * 0.6 : -dt * 0.5)));
    const mouth = mouthTargets(this.bands);
    this.mouthOpen = approach(this.mouthOpen, state === 'speaking' ? mouth.open : 0, dt, 22, 12);
    this.mouthWide = approach(this.mouthWide, state === 'speaking' ? mouth.wide : 0, dt, 20, 10);
    const pose = headPose(mix, t, level);
    const wind = breeze(t, mix.think);
    if (!still) this.drift += dt * 0.02 * wind.strength;

    const layout = fieldLayout(this.width, this.height, this.lineCentre);
    // Small or slow devices draw fewer, larger particles: any first part of the cloud is an even sample.
    const small = this.width < 520 || (navigator.hardwareConcurrency ?? 8) <= 4;
    const used = small ? Math.min(this.count, SMALL_SCREEN_PARTICLES) : this.count;
    const spacing = (this.cloud?.spacing ?? 0.0135) * Math.sqrt(this.count / used);
    const dark = document.documentElement.dataset.theme !== 'white';

    gl.uniform2f(u.uSize, this.width, this.height);
    gl.uniform2f(u.uCentre, layout.cx, layout.cy);
    gl.uniform4f(u.uRot, Math.sin(pose.yaw), Math.cos(pose.yaw), Math.sin(pose.pitch), Math.cos(pose.pitch));
    gl.uniform3f(u.uState, mix.listen, mix.think, mix.speak);
    gl.uniform1fv(u.uBands, this.bands);
    gl.uniform1f(u.uDpr, this.dpr);
    gl.uniform1f(u.uTime, t);
    gl.uniform1f(u.uLineCount, Math.min(layout.lineCount, used));
    gl.uniform1f(u.uLineH, layout.lineHeight);
    gl.uniform1f(u.uLineMid, layout.lineMid);
    gl.uniform1f(u.uScale, layout.scale);
    gl.uniform1f(u.uFace, this.faceMix);
    gl.uniform1f(u.uDot, 0.3 * spacing * layout.scale);
    gl.uniform1f(u.uLevel, level);
    gl.uniform1f(u.uOpen, this.mouthOpen);
    gl.uniform1f(u.uRound, this.mouthOpen * (1 - this.mouthWide));
    gl.uniform1f(u.uWide, this.mouthWide);
    gl.uniform3f(u.uWind, wind.x, wind.y, wind.strength);
    gl.uniform1f(u.uSide, this.side);
    gl.uniform1f(u.uDrift, this.drift);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const lineCount = Math.min(layout.lineCount, used);
    // The line: glowing on a dark page, solid dots on a light one.
    gl.uniform1f(u.uDark, dark ? 1 : 0);
    if (dark) gl.blendFunc(gl.ONE, gl.ONE);
    else gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    if (this.parts !== 'face') gl.drawArrays(gl.POINTS, 0, lineCount);
    // The face is made of light, so it always glows: on a light page it gets a dark backdrop of its own.
    if (this.faceMix > 0 && used > lineCount) {
      gl.uniform1f(u.uDark, 1);
      gl.blendFunc(gl.ONE, gl.ONE);
      gl.drawArrays(gl.POINTS, lineCount, used - lineCount);
    }
    const shade = dark || this.faceMix <= 0 ? '' : `rgba(10, 10, 18, ${(this.faceMix ** 0.6 * 0.94).toFixed(3)})`;
    const backdrop = shade
      ? `radial-gradient(ellipse ${Math.round(layout.scale * 2.1)}px ${Math.round(layout.scale * 1.95)}px at ${Math.round(layout.cx)}px ${Math.round(layout.cy)}px, ${shade} 0%, ${shade} 52%, rgba(10, 10, 18, 0) 100%)`
      : '';
    if (backdrop !== this.backdrop) {
      this.backdrop = backdrop;
      this.canvas.style.background = backdrop;
    }

    // A canvas that holds only the face has nothing to draw while the face is away: it rests until something changes.
    const resting = this.parts === 'face' && this.faceMix <= 0 && !faceOn;
    if (!still && !resting) this.raf = requestAnimationFrame((n) => this.frame(n));
  }
}
