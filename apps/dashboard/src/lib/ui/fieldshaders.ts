/* The voice field's two WebGL programs. Every particle's position, size and colour is worked out here, on the
   GPU, from the numbers voicefield.ts sets each frame (the uniforms listed at the end). */

import { BANDS } from './fieldmotion';

export const VERTEX = `
precision highp float;
attribute vec3 aPos;     // face position / 4
attribute vec4 aLook;    // brightness, edge, jaw, mouth
attribute vec2 aNormal;  // surface direction x, y
attribute vec4 aRand;    // index, u, phase, speed
attribute vec4 aMore;    // radius, lane, band, delay
uniform vec2 uSize;      // canvas size in CSS pixels
uniform vec2 uCentre;    // centre of the face
uniform vec4 uRot;       // sin yaw, cos yaw, sin pitch, cos pitch
uniform vec3 uState;     // listening, thinking, speaking (0..1 each)
uniform float uBands[${BANDS}];
uniform float uDpr, uTime, uDrift, uLineCount, uLineH, uLineMid, uScale, uFace, uDot, uLevel, uOpen, uRound, uWide, uSide;
uniform vec3 uWind;      // direction of the breeze (x, y) and its strength now
varying vec4 vColor;     // colour, and brightness in alpha
varying float vSharp;
const float PI = 3.14159265;

// A colour that runs through four stops as t goes from 0 to 1.
vec3 ramp(vec3 a, vec3 b, vec3 c, vec3 d, float t) {
  t = clamp(t, 0.0, 1.0) * 3.0;
  return t < 1.0 ? mix(a, b, t) : t < 2.0 ? mix(b, c, t - 1.0) : mix(c, d, t - 2.0);
}
vec3 listenColour(float t) { return ramp(vec3(0.35, 1.0, 0.5), vec3(0.1, 0.95, 0.85), vec3(0.3, 0.6, 1.0), vec3(0.66, 0.45, 1.0), t); }
vec3 thinkColour(float t) { return ramp(vec3(0.35, 0.55, 1.0), vec3(0.55, 0.42, 1.0), vec3(0.8, 0.42, 1.0), vec3(1.0, 0.42, 0.8), t); }
vec3 speakColour(float t) { return ramp(vec3(0.15, 0.9, 1.0), vec3(0.45, 0.5, 1.0), vec3(1.0, 0.4, 0.82), vec3(1.0, 0.66, 0.35), t); }

void main() {
  float index = aRand.x, u = aRand.y, ph = aRand.z, sp = aRand.w;
  float r = aMore.x, lane = aMore.y, delay = aMore.w;
  float listen = uState.x, think = uState.y, speak = uState.z;
  float wave = max(listen, speak);

  // The line along the bottom: a ribbon the breeze carries to the right in slow waves. With sound, each
  // particle takes the loudness of the tone at its place (low on the left, high on the right).
  float xn = fract(u + uDrift * sp);
  float tone = xn * ${BANDS - 1}.0;
  int low = int(min(floor(tone), ${BANDS - 2}.0));
  float lineBand = mix(uBands[low], uBands[low + 1], tone - float(low));
  float taper = pow(sin(PI * xn), 0.8);
  float mid = uLineMid;
  float ribbon = (sin(xn * 7.0 - uTime * 0.7 + ph * 0.3) * 0.1 + sin(xn * 17.0 - uTime * 1.3 + ph) * 0.05) * uLineH * uWind.z
               + lane * uLineH * 0.07 * (1.0 + 0.4 * sin(uTime * 0.8 + ph));
  float amp = min(uLineH * 0.48, (0.1 + 1.3 * lineBand) * uLineH * 0.5);
  float pulse = (lane * 0.55 + sin(xn * 9.0 + uTime * 4.0 * sp + ph) * 0.45) * amp * taper;
  vec2 line = vec2(xn * uSize.x, mid + ribbon * (1.0 - 0.6 * wave) + pulse * wave);
  float band = uBands[int(aMore.z)];

  vec2 pos;
  vec3 tint;
  float value;
  float size;
  if (index < uLineCount) {
    vec3 violet = mix(vec3(0.5, 0.4, 1.0), vec3(0.85, 0.4, 1.0), u);
    tint = violet * (1.0 - listen - speak) + listenColour(xn) * listen + speakColour(xn) * speak;
    pos = line;
    // A slow shimmer runs along the line while the agent thinks.
    value = mix(0.3, 0.35 + 0.65 * min(1.0, uLevel * 1.6 + lineBand * 0.6), wave) * (1.0 + think * 0.6 * sin(xn * 6.0 - uTime * 2.0))
          * smoothstep(0.0, 0.02, xn) * smoothstep(1.0, 0.98, xn) * 1.1;
    size = mix(r * 4.5, r * 5.2 * (1.0 + lineBand * 1.3), wave);
    vSharp = 3.6;
  } else {
    vec3 f = aPos * 4.0;
    float b = aLook.x, edge = aLook.y, jaw = aLook.z, mouth = aLook.w;
    // Expression: the lips round or spread, the jaw drops; while listening the surface ripples with the sound.
    f.x *= 1.0 - mouth * (0.2 * uRound - 0.08 * uWide);
    f.y += jaw * uOpen * 0.105;
    f.z += listen * band * 0.04 * (1.0 - edge);
    // Turn the head around a point behind the face, then apply the camera's perspective.
    float zc = f.z + 0.45;
    float hx = f.x * uRot.y + zc * uRot.x;
    float hz = zc * uRot.y - f.x * uRot.x;
    float hy = f.y * uRot.w + hz * uRot.z;
    float depth = hz * uRot.w - f.y * uRot.z - 0.45;
    float persp = 1.0 / (1.0 - depth * 0.2);
    // The breeze. Loose particles are carried off downwind, wander a little, fade, and start again at home;
    // the looser a particle is, the further it goes. Ones on the upwind side travel less, so they do not
    // cloud the face.
    vec2 wind = uWind.xy;
    vec2 side = vec2(-wind.y, wind.x);
    float downwind = clamp(dot(f.xy, wind) / 1.5 * 0.5 + 0.5, 0.0, 1.0);
    float loose = edge * edge * mix(0.25, 1.0, delay * delay);
    float cycle = fract(uTime * 0.07 * sp + u);
    float travel = loose * (0.08 + 1.25 * pow(cycle, 1.3)) * (0.45 + 0.55 * downwind) * uWind.z + listen * band * 0.05 * edge;
    vec2 blown = wind * travel
               + side * sin(cycle * 6.0 + ph + uTime * 0.5) * 0.09 * loose * cycle
               + vec2(sin(f.y * 3.1 + uTime * 0.45 + ph), cos(f.x * 2.7 - uTime * 0.38 + ph * 1.3)) * 0.03 * loose;
    float life = mix(1.0, smoothstep(0.0, 0.12, cycle) * pow(1.0 - cycle, 1.4) * 1.6, min(1.0, loose * 3.0));
    // Arriving and leaving on the breeze: the downwind side of the face goes first, so what is blown away
    // does not cross what is still there. uSide says which way: in from upwind (-1) or away downwind (1).
    float order = (1.0 - downwind) * 0.65 + delay * 0.35;
    float arrive = smoothstep(order * 0.6, order * 0.6 + 0.4, uFace);
    float gone = 1.0 - arrive;
    blown += wind * pow(gone, 1.5) * (0.9 + 1.1 * lane * lane + 0.5 * delay) * uSide
           + side * (sin(gone * 5.0 + ph) * 0.2 * gone + lane * 0.22 * gone * gone)
           - vec2(0.0, 0.22 * gone * gone * (0.4 + delay));
    pos = uCentre + (vec2(hx, hy) * persp + blown) * uScale;
    // The face's own brightness; parts that turn away from us dim, parts that turn toward us brighten.
    vec3 n = vec3(aNormal, sqrt(max(0.0, 1.0 - dot(aNormal, aNormal))));
    float nz = (n.z * uRot.y - n.x * uRot.x) * uRot.w - n.y * uRot.z;
    float turn = pow(clamp(nz / max(n.z, 0.2), 0.3, 1.3), 0.8);
    value = pow(b, 1.8) * 1.5 * (1.0 + 0.7 * edge) * turn * life;
    value *= 1.0 + think * (-0.1 + 0.2 * sin(uTime * 1.6 - f.y * 3.0)) + listen * (-0.15 + 0.7 * band);
    // Colours run across the face and drift slowly; loose particles vary more.
    float hue = f.x * 0.42 + 0.5 + 0.17 * sin(uTime * 0.17 + f.y * 1.3) + (delay - 0.5) * 0.35 * edge;
    tint = (listenColour(hue) * listen + thinkColour(hue) * think + speakColour(hue) * speak) / max(listen + think + speak, 0.001);
    value = (1.0 - exp(-4.6 * value)) * 1.3 * pow(arrive, 1.3);
    size = uDot * 5.0 * (1.0 + 0.6 * edge);
    vSharp = 3.1;
  }
  float pixels = size * uDpr;
  if (pixels < 2.0) {       // a dot cannot be smaller than a couple of pixels: dim it instead
    value *= (pixels * pixels) / 4.0;
    pixels = 2.0;
  }
  vColor = vec4(tint, value);
  gl_PointSize = pixels;
  gl_Position = vec4(pos.x / uSize.x * 2.0 - 1.0, 1.0 - pos.y / uSize.y * 2.0, 0.0, 1.0);
}`;

export const FRAGMENT = `
precision mediump float;
varying vec4 vColor;
varying float vSharp;
uniform float uDark;
void main() {
  vec2 d = gl_PointCoord * 2.0 - 1.0;
  float r2 = dot(d, d);
  if (r2 > 1.0) discard;
  float a = vColor.a * exp(-r2 * vSharp);
  if (uDark > 0.5) {  // glowing dots that add up; the brightest turn white
    vec3 c = mix(vColor.rgb, vec3(1.0), smoothstep(1.0, 2.3, a));
    a = min(a, 1.0);
    gl_FragColor = vec4(c * a, a);
  } else {            // on a light page: darker, solid dots
    a = min(a, 1.0);
    gl_FragColor = vec4(vColor.rgb * 0.5 * a, a);
  }
}`;

export const UNIFORMS = ['uSize', 'uCentre', 'uRot', 'uState', 'uBands', 'uDpr', 'uTime', 'uLineCount', 'uLineH', 'uLineMid', 'uScale', 'uFace', 'uDot', 'uLevel', 'uOpen', 'uRound', 'uWide', 'uDark', 'uWind', 'uSide', 'uDrift'] as const;
export type UniformName = (typeof UNIFORMS)[number];
