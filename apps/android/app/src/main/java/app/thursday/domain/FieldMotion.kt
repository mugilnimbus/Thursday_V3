package app.thursday.domain

import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

/*
 * The numbers behind the voice field's movement, kept apart from the drawing so they can be tested: audio bands,
 * easing, where things sit on the canvas, how the head is held in each state, the breeze, and the colours.
 * The same rules as the dashboard's fieldmotion.ts and its shader.
 */

const val FIELD_BANDS = 12

/** How strongly each state shows, 0..1. They cross-fade, so a change of state has no jump. */
class StateMix(var listen: Float = 0f, var think: Float = 0f, var speak: Float = 0f)

/** Move [from] toward [to]; [up] and [down] are speeds per second for rising and falling. */
fun approach(from: Float, to: Float, dt: Float, up: Float, down: Float = up): Float =
    from + (to - from) * (1 - exp(-dt * if (to > from) up else down))

fun smoothstep(a: Float, b: Float, v: Float): Float {
    val t = ((v - a) / (b - a)).coerceIn(0f, 1f)
    return t * t * (3 - 2 * t)
}

/** Speech-like bands when there is no real audio: syllables, pauses between phrases, and moving formants. */
fun speechBands(t: Float, loud: Float, out: FloatArray, random: () -> Float = { kotlin.random.Random.nextFloat() }) {
    val syllable = max(0f, sin(t * 23.2f + sin(t * 1.3f) * 2)).pow(0.7f)
    val phrase = if ((sin(t * 0.9f) + sin(t * 2.3f) * 0.3f + 1) / 2 > 0.12f) 1f else 0.08f
    val envelope = syllable * phrase * loud
    val f1 = 2 + sin(t * 2.1f) * 1.5f
    val f2 = 6.5f + sin(t * 1.7f + 1) * 2.2f
    for (i in out.indices) {
        val shape = exp(-((i - f1) * (i - f1)) / 3) + 0.7f * exp(-((i - f2) * (i - f2)) / 4) + 0.12f
        out[i] = min(1f, envelope * shape * (0.8f + random() * 0.4f))
    }
}

/** Bands from the microphone's loudness alone (the phone has no spectrum while recording): spread with a little movement. */
fun levelBands(level: Float, t: Float, out: FloatArray) {
    for (i in out.indices) out[i] = min(1f, level * (0.55f + 0.45f * sin(t * 9 + i * 0.9f)) * 1.4f)
}

/** The loudness of the tone at place [x] (0..1) along the line: low tones on the left, high on the right, blended between bands. */
fun bandAt(bands: FloatArray, x: Float): Float {
    val at = x.coerceIn(0f, 1f) * (bands.size - 1)
    val i = min(bands.size - 2, at.toInt())
    return bands[i] + (bands[i + 1] - bands[i]) * (at - i)
}

/** The mouth from the bands: low bands (vowels) open the jaw, high bands (s, ee) spread the lips. Returns open, wide. */
fun mouthTargets(bands: FloatArray): Pair<Float, Float> {
    val half = bands.size / 2
    var low = 0f
    var high = 0f
    for (i in bands.indices) if (i < half) low += bands[i] else high += bands[i]
    return min(1f, low / half * 1.9f) to min(1f, high / half * 2.4f)
}

/** How the head is held, in radians. Yaw turns it left and right, pitch tips it (positive looks down). */
class HeadPose(val yaw: Float, val pitch: Float)

fun headPose(mix: StateMix, t: Float, level: Float): HeadPose {
    // Thinking: slow, wide looks to the side, chin a little up. Speaking: a calm, slow sway; the head does not bob
    // with the words. Listening: turned and leaning slightly toward you, nodding gently when you are loud.
    val yaw = mix.think * sin(t * 0.45f) * 0.2f +
        mix.speak * sin(t * 0.55f) * 0.1f +
        mix.listen * (0.09f + sin(t * 0.5f) * 0.05f)
    val pitch = mix.think * (-0.07f + sin(t * 0.6f) * 0.04f) +
        mix.speak * sin(t * 0.7f + 1) * 0.03f +
        mix.listen * (0.06f + level * 0.05f)
    return HeadPose(yaw, pitch)
}

/** The mild breeze that carries loose particles: a direction (unit vector, y down) and a strength around 1. */
class Breeze(val x: Float, val y: Float, val strength: Float)

/** It blows to the right and a little upward, wanders slowly, comes in soft gusts, and lifts while thinking. */
fun breeze(t: Float, think: Float = 0f): Breeze {
    val angle = -0.26f + 0.2f * sin(t * 0.09f) - think * 0.3f
    return Breeze(cos(angle), sin(angle), 0.75f + 0.25f * sin(t * 0.31f + 1.7f * sin(t * 0.13f)))
}

/**
 * Where things sit, in pixels.
 * @param lineHeight height of the band along the bottom where the line lives
 * @param scale pixels per face unit; the face is about 2.4 units tall
 */
class FieldLayout(val lineHeight: Float, val scale: Float, val cx: Float, val cy: Float)

fun fieldLayout(width: Float, height: Float, density: Float): FieldLayout {
    val lineHeight = min(height, 72 * density)
    val scale = max(1f, min(min(280 * density, (height - lineHeight * 0.5f) * 0.31f), width * 0.33f))
    return FieldLayout(lineHeight, scale, width / 2, max(scale * 1.45f, (height - lineHeight * 0.6f) * 0.5f))
}

/** A colour that runs through four stops as t goes from 0 to 1. Stops and result are r, g, b in 0..1. */
private fun ramp(stops: Array<FloatArray>, t: Float, out: FloatArray) {
    val v = t.coerceIn(0f, 1f) * 3
    val i = min(2, v.toInt())
    val f = v - i
    for (c in 0..2) out[c] = stops[i][c] + (stops[i + 1][c] - stops[i][c]) * f
}

private val LISTEN = arrayOf(floatArrayOf(0.35f, 1f, 0.5f), floatArrayOf(0.1f, 0.95f, 0.85f), floatArrayOf(0.3f, 0.6f, 1f), floatArrayOf(0.66f, 0.45f, 1f))
private val THINK = arrayOf(floatArrayOf(0.35f, 0.55f, 1f), floatArrayOf(0.55f, 0.42f, 1f), floatArrayOf(0.8f, 0.42f, 1f), floatArrayOf(1f, 0.42f, 0.8f))
private val SPEAK = arrayOf(floatArrayOf(0.15f, 0.9f, 1f), floatArrayOf(0.45f, 0.5f, 1f), floatArrayOf(1f, 0.4f, 0.82f), floatArrayOf(1f, 0.66f, 0.35f))

/**
 * The face's colour at position [t] across it (0 left, 1 right) for the current blend of states: greens and blues
 * while listening; blue, violet and magenta while thinking; cyan through pink to orange while speaking.
 */
fun faceColour(mix: StateMix, t: Float, out: FloatArray) {
    val sum = max(mix.listen + mix.think + mix.speak, 0.001f)
    val a = FloatArray(3)
    out.fill(0f)
    ramp(LISTEN, t, a)
    for (c in 0..2) out[c] += a[c] * mix.listen / sum
    ramp(THINK, t, a)
    for (c in 0..2) out[c] += a[c] * mix.think / sum
    ramp(SPEAK, t, a)
    for (c in 0..2) out[c] += a[c] * mix.speak / sum
}

/** The part of the line's colour that comes from sound, at [t] along it: the listening and speaking colours, weighted. */
fun soundColour(mix: StateMix, t: Float, out: FloatArray) {
    val a = FloatArray(3)
    out.fill(0f)
    ramp(LISTEN, t, a)
    for (c in 0..2) out[c] += a[c] * mix.listen
    ramp(SPEAK, t, a)
    for (c in 0..2) out[c] += a[c] * mix.speak
}
