package app.thursday.ui.chat

import android.graphics.BlendMode as NativeBlendMode
import android.graphics.Paint
import android.provider.Settings
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.platform.LocalContext
import app.thursday.domain.Breeze
import app.thursday.domain.FIELD_BANDS
import app.thursday.domain.FaceCloud
import app.thursday.domain.FieldLayout
import app.thursday.domain.HeadPose
import app.thursday.domain.StateMix
import app.thursday.domain.approach
import app.thursday.domain.bandAt
import app.thursday.domain.breeze
import app.thursday.domain.faceColour
import app.thursday.domain.fieldLayout
import app.thursday.domain.headPose
import app.thursday.domain.levelBands
import app.thursday.domain.mouthTargets
import app.thursday.domain.parseFaceCloud
import app.thursday.domain.smoothstep
import app.thursday.domain.soundColour
import app.thursday.domain.speechBands
import app.thursday.ui.theme.LocalPalette
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.random.Random
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val LINE_PARTICLES = 140
private const val FACE_PARTICLES = 10_000 // the phone draws about half of the face cloud, a little larger
private const val HUES = 12 // the face is drawn in batches of one colour and brightness each
private const val LEVELS = 6
private const val BUCKETS = HUES * LEVELS * 2 // two dot sizes: the solid face and the loose particles

/** What carries over from one frame to the next. */
private class FieldMemory {
    val bands = FloatArray(FIELD_BANDS)
    val target = FloatArray(FIELD_BANDS)
    val mix = StateMix()
    var faceMix = 0f // 0 = no face, 1 = fully there
    var side = -1f // the face comes in from upwind (-1) or is blown away downwind (1)
    var mouthOpen = 0f
    var mouthWide = 0f
    var clock = 0f // seconds of animation
    var drift = 0f // how far the breeze has carried the line, in screen widths
    var last = 0L
}

private class LineParticle(val u: Float, val ph: Float, val sp: Float, val r: Float, val lane: Float)

/** The face cloud with each particle's fixed random numbers and the scratch space for drawing it. */
private class FaceDraw(val cloud: FaceCloud) {
    val n = cloud.count
    val u = FloatArray(n)
    val ph = FloatArray(n)
    val sp = FloatArray(n)
    val lane = FloatArray(n)
    val delay = FloatArray(n)
    val band = IntArray(n)
    val base = FloatArray(n) // the particle's own brightness
    val nz = FloatArray(n) // how much the surface faces the viewer
    val loose = FloatArray(n) // how far the breeze carries it
    val sx = FloatArray(n)
    val sy = FloatArray(n)
    val bucket = ShortArray(n)
    val counts = IntArray(BUCKETS)
    val starts = IntArray(BUCKETS + 1)
    val cursor = IntArray(BUCKETS)
    val points = FloatArray(n * 2)
    val colours = Array(HUES) { FloatArray(3) }

    init {
        val random = Random(3)
        for (i in 0 until n) {
            u[i] = random.nextFloat()
            ph[i] = random.nextFloat() * 6.283f
            sp[i] = 0.6f + random.nextFloat() * 0.8f
            lane[i] = random.nextFloat() * 2 - 1
            delay[i] = random.nextFloat()
            band[i] = i % FIELD_BANDS
            val edge = cloud.edge[i]
            base[i] = cloud.b[i].pow(1.8f) * 1.5f * (1 + 0.7f * edge)
            nz[i] = sqrt(max(0f, 1 - cloud.nx[i] * cloud.nx[i] - cloud.ny[i] * cloud.ny[i]))
            loose[i] = edge * edge * (0.25f + 0.75f * delay[i] * delay[i])
        }
    }
}

/**
 * Voice agent presence, like the dashboard. It fills the conversation area behind the messages.
 *
 * The line along the bottom is always there: a ribbon of particles carried by a mild breeze. While you talk or the
 * agent speaks it pulses with the sound, low tones on the left and high tones on the right, taller when louder.
 *
 * The face (which [showFace] turns off) gathers while the agent listens, thinks or speaks. Listening: greens and
 * blues, leaning slightly toward you. Thinking: blue, violet and magenta, looking slowly from side to side.
 * Speaking: cyan through pink to orange; jaw and lips move with the words while the head stays calm. Loose particles
 * around the head are carried off on the breeze, and the face itself arrives on it and is blown away by it when the
 * agent goes idle.
 *
 * The face is the cloud in assets/face-cloud.bin. Until the voice stage streams audio, a speech-like envelope drives
 * the speaking mouth. Frames stop when the screen is not composed, and people who turn animations off get stills.
 */
@Composable
fun VoiceField(state: Voice, level: Float = 0f, showFace: Boolean = true, modifier: Modifier = Modifier) {
    val dark = LocalPalette.current.dark
    val context = LocalContext.current
    val still = remember { Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }
    val line = remember {
        val random = Random(5)
        List(LINE_PARTICLES) { LineParticle(random.nextFloat(), random.nextFloat() * 6.283f, 0.6f + random.nextFloat() * 0.8f, 0.6f + random.nextFloat() * 1.5f, random.nextFloat() * 2 - 1) }
    }
    val memory = remember { FieldMemory() }
    // The line works at once; the face joins when its file has been read. Without it, the line carries on alone.
    val face by produceState<FaceDraw?>(null) {
        value = withContext(Dispatchers.Default) {
            runCatching { FaceDraw(parseFaceCloud(context.assets.open("face-cloud.bin").use { it.readBytes() }, FACE_PARTICLES)) }.getOrNull()
        }
    }
    val dots = remember {
        Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeCap = Paint.Cap.ROUND
            blendMode = NativeBlendMode.PLUS // dots of light add up
        }
    }
    var frame by remember { mutableLongStateOf(0L) }
    if (!still) LaunchedEffect(Unit) { while (true) withFrameNanos { frame = it } }

    Canvas(modifier.fillMaxSize()) {
        val now = frame
        val m = memory
        val dt = if (still) 1f else if (m.last == 0L) 0.016f else min(0.05f, (now - m.last) / 1e9f)
        m.last = now
        if (!still) m.clock += dt
        val t = m.clock

        // Audio bands: fast attack, slow release.
        when {
            still -> m.target.fill(0f)
            state == Voice.SPEAKING -> speechBands(t, 1f, m.target)
            state == Voice.LISTENING -> levelBands(level, t, m.target)
            else -> m.target.fill(0f)
        }
        var loud = 0f
        for (i in 0 until FIELD_BANDS) {
            val d = m.target[i] - m.bands[i]
            m.bands[i] += d * if (d > 0) 0.55f else 0.14f
            loud += m.bands[i] / FIELD_BANDS
        }

        // States cross-fade; the face arrives on the breeze over a couple of seconds and leaves the same way.
        val mix = m.mix
        mix.listen = approach(mix.listen, if (state == Voice.LISTENING) 1f else 0f, dt, 5f)
        mix.think = approach(mix.think, if (state == Voice.THINKING) 1f else 0f, dt, 5f)
        mix.speak = approach(mix.speak, if (state == Voice.SPEAKING) 1f else 0f, dt, 5f)
        val cloud = face
        val faceOn = showFace && state != Voice.IDLE && cloud != null
        if (m.faceMix <= 0f && faceOn) m.side = -1f else if (m.faceMix >= 1f && !faceOn) m.side = 1f
        m.faceMix = if (still) (if (faceOn) 1f else 0f) else (m.faceMix + if (faceOn) dt * 0.6f else -dt * 0.5f).coerceIn(0f, 1f)
        val (open, wide) = mouthTargets(m.bands)
        m.mouthOpen = approach(m.mouthOpen, if (state == Voice.SPEAKING) open else 0f, dt, 22f, 12f)
        m.mouthWide = approach(m.mouthWide, if (state == Voice.SPEAKING) wide else 0f, dt, 20f, 10f)
        val wind = breeze(t, mix.think)
        if (!still) m.drift += dt * 0.02f * wind.strength

        val layout = fieldLayout(size.width, size.height, density)
        if (cloud != null && m.faceMix > 0f) {
            if (!dark) drawBackdrop(layout, m.faceMix)
            drawFace(cloud, m, layout, headPose(mix, t, loud), wind, t, dots)
        }
        drawLine(line, m, layout, wind, t, loud, dark)
    }
}

/** On a light page the face, which is made of light, gets a dark backdrop of its own. */
private fun DrawScope.drawBackdrop(layout: FieldLayout, faceMix: Float) {
    val shade = Color(0xFF0A0A12).copy(alpha = faceMix.pow(0.6f) * 0.94f)
    val centre = Offset(layout.cx, layout.cy)
    val radius = layout.scale * 2.05f
    drawCircle(Brush.radialGradient(0f to shade, 0.52f to shade, 1f to shade.copy(alpha = 0f), center = centre, radius = radius), radius, centre)
}

/**
 * The line along the bottom: a ribbon the breeze carries to the right in slow waves. With sound it pulses: each
 * particle takes the loudness of the tone at its place along the line (low on the left, high on the right).
 */
private fun DrawScope.drawLine(line: List<LineParticle>, m: FieldMemory, layout: FieldLayout, wind: Breeze, t: Float, loud: Float, dark: Boolean) {
    val mix = m.mix
    val wave = max(mix.listen, mix.speak)
    val rest = max(0f, 1 - mix.listen - mix.speak)
    val lineH = layout.lineHeight
    val mid = size.height - lineH / 2
    val sound = FloatArray(3)
    val shade = if (dark) 1f else 0.6f // darker dots on a light page
    for (p in line) {
        val xn = (p.u + m.drift * p.sp) % 1f
        val band = bandAt(m.bands, xn)
        val taper = sin(PI.toFloat() * xn).pow(0.8f)
        val ribbon = (sin(xn * 7 - t * 0.7f + p.ph * 0.3f) * 0.1f + sin(xn * 17 - t * 1.3f + p.ph) * 0.05f) * lineH * wind.strength +
            p.lane * lineH * 0.07f * (1 + 0.4f * sin(t * 0.8f + p.ph))
        val amp = min(lineH * 0.48f, (0.1f + 1.3f * band) * lineH * 0.5f)
        val pulse = (p.lane * 0.55f + sin(xn * 9 + t * 4 * p.sp + p.ph) * 0.45f) * amp * taper
        val centre = Offset(xn * size.width, mid + ribbon * (1 - 0.6f * wave) + pulse * wave)
        soundColour(mix, xn, sound)
        val colour = Color(
            ((0.5f + 0.35f * p.u) * rest + sound[0]).coerceIn(0f, 1f) * shade,
            (0.4f * rest + sound[1]).coerceIn(0f, 1f) * shade,
            (rest + sound[2]).coerceIn(0f, 1f) * shade,
        )
        // A slow shimmer runs along the line while the agent thinks.
        val alpha = (0.3f + (0.05f + 0.65f * min(1f, loud * 1.6f + band * 0.6f)) * wave) *
            (1 + mix.think * 0.6f * sin(xn * 6 - t * 2)) * smoothstep(0f, 0.02f, xn) * smoothstep(1f, 0.98f, xn)
        // A sharp dot with a faint halo: a wide soft blob alone reads as blur on a phone screen.
        val core = p.r * (1f + (0.15f + band * 1.3f) * wave) * 1.05f * density
        val shown = (if (dark) alpha else alpha + 0.15f).coerceIn(0f, 1f)
        val blend = if (dark) BlendMode.Plus else BlendMode.SrcOver
        drawCircle(Brush.radialGradient(listOf(colour.copy(alpha = shown * 0.3f), colour.copy(alpha = 0f)), centre, core * 2.6f), core * 2.6f, centre, blendMode = blend)
        drawCircle(colour.copy(alpha = min(1f, shown * 1.5f)), core, centre, blendMode = blend)
    }
}

/**
 * The face. Every particle is placed and lit here (the dashboard does the same sums on the GPU), then the particles
 * are drawn in batches that share a colour and brightness, so ten thousand dots cost a few hundred draw calls.
 */
private fun DrawScope.drawFace(d: FaceDraw, m: FieldMemory, layout: FieldLayout, pose: HeadPose, wind: Breeze, t: Float, dots: Paint) {
    val c = d.cloud
    val mix = m.mix
    val listen = mix.listen
    val think = mix.think
    val sinYaw = sin(pose.yaw)
    val cosYaw = cos(pose.yaw)
    val sinPitch = sin(pose.pitch)
    val cosPitch = cos(pose.pitch)
    val windX = wind.x
    val windY = wind.y
    val acrossX = -wind.y // at right angles to the breeze
    val acrossY = wind.x
    val faceMix = m.faceMix
    val formed = faceMix >= 1f
    val jawDrop = m.mouthOpen * 0.105f
    val lipPull = 0.2f * m.mouthOpen * (1 - m.mouthWide) - 0.08f * m.mouthWide
    val lively = think > 0.01f || listen > 0.01f
    val scale = layout.scale
    val width = size.width
    val height = size.height
    d.counts.fill(0)

    for (i in 0 until d.n) {
        val edge = c.edge[i]
        val delay = d.delay[i]
        val band = m.bands[d.band[i]]
        // Expression: the lips round or spread, the jaw drops; while listening the surface ripples with the sound.
        val fx = c.x[i] * (1 - c.mouth[i] * lipPull)
        val fy = c.y[i] + c.jaw[i] * jawDrop
        val fz = c.z[i] + listen * band * 0.04f * (1 - edge)
        // Turn the head around a point behind the face, then apply the camera's perspective.
        val zc = fz + 0.45f
        val hx = fx * cosYaw + zc * sinYaw
        val hz = zc * cosYaw - fx * sinYaw
        val hy = fy * cosPitch + hz * sinPitch
        val persp = 1 / (1 - (hz * cosPitch - fy * sinPitch - 0.45f) * 0.2f)
        // The breeze: loose particles are carried off downwind, wander a little, fade, and start again at home.
        val downwind = ((fx * windX + fy * windY) / 1.5f * 0.5f + 0.5f).coerceIn(0f, 1f)
        var blownX = 0f
        var blownY = 0f
        var life = 1f
        val loose = d.loose[i]
        if (loose > 0.002f) {
            val ph = d.ph[i]
            val cycle = (t * 0.07f * d.sp[i] + d.u[i]) % 1f
            val travel = loose * (0.08f + 1.25f * cycle.pow(1.3f)) * (0.45f + 0.55f * downwind) * wind.strength + listen * band * 0.05f * edge
            val wander = sin(cycle * 6 + ph + t * 0.5f) * 0.09f * loose * cycle
            blownX = windX * travel + acrossX * wander + sin(fy * 3.1f + t * 0.45f + ph) * 0.03f * loose
            blownY = windY * travel + acrossY * wander + cos(fx * 2.7f - t * 0.38f + ph * 1.3f) * 0.03f * loose
            life = 1 + (smoothstep(0f, 0.12f, cycle) * (1 - cycle).pow(1.4f) * 1.6f - 1) * min(1f, loose * 3)
        }
        // Arriving and leaving on the breeze: the downwind side of the face goes first.
        var arrive = 1f
        if (!formed) {
            val order = (1 - downwind) * 0.65f + delay * 0.35f
            arrive = smoothstep(order * 0.6f, order * 0.6f + 0.4f, faceMix)
            if (arrive <= 0f) {
                d.bucket[i] = -1
                continue
            }
            val gone = 1 - arrive
            val lane = d.lane[i]
            val far = gone.pow(1.5f) * (0.9f + 1.1f * lane * lane + 0.5f * delay) * m.side
            val sway = sin(gone * 5 + d.ph[i]) * 0.2f * gone + lane * 0.22f * gone * gone
            blownX += windX * far + acrossX * sway
            blownY += windY * far + acrossY * sway - 0.22f * gone * gone * (0.4f + delay)
        }
        val x = layout.cx + (hx * persp + blownX) * scale
        val y = layout.cy + (hy * persp + blownY) * scale
        if (x < 0 || x > width || y < 0 || y > height) {
            d.bucket[i] = -1
            continue
        }
        // The face's own brightness; parts that turn away from us dim, parts that turn toward us brighten.
        val nz = d.nz[i]
        val turned = (nz * cosYaw - c.nx[i] * sinYaw) * cosPitch - c.ny[i] * sinPitch
        var value = d.base[i] * (turned / max(nz, 0.2f)).coerceIn(0.3f, 1.3f).pow(0.8f) * life
        if (lively) value *= 1 + think * (-0.1f + 0.2f * sin(t * 1.6f - fy * 3)) + listen * (-0.15f + 0.7f * band)
        value = (1 - exp(-4.6f * value)) * 1.3f
        if (!formed) value *= arrive.pow(1.3f)
        if (value < 0.04f) {
            d.bucket[i] = -1
            continue
        }
        // Colours run across the face and drift slowly; loose particles vary more.
        val hue = (fx * 0.42f + 0.5f + 0.17f * sin(t * 0.17f + fy * 1.3f) + (delay - 0.5f) * 0.35f * edge).coerceIn(0f, 1f)
        val batch = (((hue * (HUES - 1) + 0.5f).toInt() * LEVELS + min(LEVELS - 1, (value / 1.3f * LEVELS).toInt())) shl 1) or (if (edge > 0.5f) 1 else 0)
        d.sx[i] = x
        d.sy[i] = y
        d.bucket[i] = batch.toShort()
        d.counts[batch]++
    }

    // Group the points by batch.
    d.starts[0] = 0
    for (b in 0 until BUCKETS) {
        d.starts[b + 1] = d.starts[b] + d.counts[b]
        d.cursor[b] = d.starts[b]
    }
    for (i in 0 until d.n) {
        val b = d.bucket[i].toInt()
        if (b < 0) continue
        val at = d.cursor[b]++ * 2
        d.points[at] = d.sx[i]
        d.points[at + 1] = d.sy[i]
    }

    for (h in 0 until HUES) faceColour(mix, h / (HUES - 1f), d.colours[h])
    val dot = max(1.5f, 0.66f * c.spacing * scale) // a little smaller than the gap between neighbours, so dots stay apart
    drawIntoCanvas { canvas ->
        val native = canvas.nativeCanvas
        for (b in 0 until BUCKETS) {
            val count = d.counts[b]
            if (count == 0) continue
            val rgb = d.colours[(b shr 1) / LEVELS]
            val brightness = ((b shr 1) % LEVELS + 0.6f) / LEVELS * 1.3f
            val white = smoothstep(0.95f, 2.1f, brightness) // the brightest dots turn toward white
            dots.color = android.graphics.Color.argb(
                min(1f, brightness * 0.9f),
                rgb[0] + (1 - rgb[0]) * white, rgb[1] + (1 - rgb[1]) * white, rgb[2] + (1 - rgb[2]) * white,
            )
            dots.strokeWidth = if (b and 1 == 1) dot * 1.5f else dot
            native.drawPoints(d.points, d.starts[b] * 2, count * 2, dots)
        }
    }
}
