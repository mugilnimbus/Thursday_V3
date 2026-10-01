package app.thursday

import app.thursday.domain.FACE_RECORD_BYTES
import app.thursday.domain.FIELD_BANDS
import app.thursday.domain.StateMix
import app.thursday.domain.approach
import app.thursday.domain.bandAt
import app.thursday.domain.breeze
import app.thursday.domain.faceColour
import app.thursday.domain.fieldLayout
import app.thursday.domain.headPose
import app.thursday.domain.mouthTargets
import app.thursday.domain.parseFaceCloud
import app.thursday.domain.speechBands
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.hypot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class FieldTest {
    private fun tiny(count: Int, declared: Int = count): ByteBuffer =
        ByteBuffer.allocate(16 + count * FACE_RECORD_BYTES).order(ByteOrder.LITTLE_ENDIAN).apply {
            putInt(0, 0x31434654)
            putInt(4, declared)
            putFloat(8, 0.0135f)
        }

    @Test
    fun readsTheHeaderAndOneRecordPerParticle() {
        val buffer = tiny(2)
        buffer.putShort(16 + 12, 8192) // second particle: x = 1 face unit
        buffer.putShort(16 + 14, -16384) // y = -2
        buffer.put(16 + 18, 255.toByte()) // b
        buffer.put(16 + 20, 128.toByte()) // jaw
        buffer.put(16 + 23, (-127).toByte()) // ny
        val cloud = parseFaceCloud(buffer.array())
        assertEquals(2, cloud.count)
        assertEquals(0.0135f, cloud.spacing, 1e-5f)
        assertEquals(1f, cloud.x[1], 1e-3f)
        assertEquals(-2f, cloud.y[1], 1e-3f)
        assertEquals(1f, cloud.b[1], 0f)
        assertEquals(0.5f, cloud.jaw[1], 0.01f)
        assertEquals(-1f, cloud.ny[1], 0f)
        assertEquals(0f, cloud.x[0], 0f)
    }

    @Test
    fun refusesFilesThatAreNotAFaceCloud() {
        assertThrows(IllegalArgumentException::class.java) { parseFaceCloud(ByteArray(4)) }
        assertThrows(IllegalArgumentException::class.java) { parseFaceCloud(ByteArray(64)) }
        assertThrows(IllegalArgumentException::class.java) { parseFaceCloud(tiny(2, 3).array()) }
    }

    @Test
    fun shippedFaceIsDenseWithAJawAndLooseParticlesAndAnyFirstPartIsAnEvenSample() {
        val bytes = File("src/main/assets/face-cloud.bin").readBytes()
        val all = parseFaceCloud(bytes)
        assertTrue(all.count in 12_000..40_000)
        val some = parseFaceCloud(bytes, 10_000)
        assertEquals(10_000, some.count)
        assertTrue(some.spacing > all.spacing) // fewer particles sit further apart
        assertEquals(all.x[42], some.x[42], 0f)
        val solid = (0 until all.count).count { all.edge[it] < 0.3f }
        val loose = (0 until all.count).count { all.edge[it] > 0.8f }
        assertTrue(solid > all.count * 0.6f)
        assertTrue(loose > all.count * 0.1f)
        val dropping = (0 until all.count).filter { all.jaw[it] > 0.6f }
        assertTrue(dropping.size > 500)
        assertTrue(dropping.all { all.y[it] > 0.5f }) // the jaw moves what is below the lips
        assertTrue((0 until all.count).filter { all.y[it] < 0.2f }.all { all.jaw[it] < 0.05f })
        fun upperShare(cloud: app.thursday.domain.FaceCloud) = (0 until cloud.count).count { cloud.y[it] < 0 }.toFloat() / cloud.count
        assertTrue(abs(upperShare(some) - upperShare(all)) < 0.04f)
    }

    @Test
    fun easesTowardATargetWithoutOvershooting() {
        assertEquals(0f, approach(0f, 1f, 0f, 10f), 0f)
        val up = approach(0f, 1f, 0.05f, 30f, 5f)
        assertTrue(up > 0.7f && up < 1f)
        assertTrue(1 - approach(1f, 0f, 0.05f, 30f, 5f) < 0.3f) // falling is slower than rising
    }

    @Test
    fun speechBandsAreBoundedWithSyllablesAndPauses() {
        val bands = FloatArray(FIELD_BANDS)
        var loudest = 0f
        var quiet = 0
        var t = 0f
        while (t < 12f) {
            speechBands(t, 1f, bands) { 0.5f }
            val peak = bands.max()
            assertTrue(peak <= 1f && bands.min() >= 0f)
            loudest = maxOf(loudest, peak)
            if (peak < 0.1f) quiet++
            t += 1f / 60
        }
        assertTrue(loudest > 0.8f)
        assertTrue(quiet > 60)
    }

    @Test
    fun lineTakesTheToneAtItsPlaceAndTheMouthFollowsLowAndHighBands() {
        val bands = FloatArray(FIELD_BANDS) { it / (FIELD_BANDS - 1f) }
        assertEquals(0f, bandAt(bands, 0f), 1e-6f)
        assertEquals(1f, bandAt(bands, 1f), 1e-6f)
        assertEquals(0.5f, bandAt(bands, 0.5f), 1e-5f) // blended between neighbouring bands
        val low = FloatArray(FIELD_BANDS).also { it.fill(0.5f, 0, FIELD_BANDS / 2) }
        val high = FloatArray(FIELD_BANDS).also { it.fill(0.5f, FIELD_BANDS / 2, FIELD_BANDS) }
        assertTrue(mouthTargets(low).first > 0.9f)
        assertEquals(0f, mouthTargets(low).second, 0f)
        assertEquals(0f, mouthTargets(high).first, 0f)
        assertEquals(1f, mouthTargets(high).second, 0f)
    }

    @Test
    fun headStaysWithinASmallTurnAndDoesNotBobWhileSpeaking() {
        var t = 0f
        while (t < 30f) {
            for (mix in listOf(StateMix(listen = 1f), StateMix(think = 1f), StateMix(speak = 1f))) {
                val pose = headPose(mix, t, 1f)
                assertTrue(abs(pose.yaw) < 0.25f) // under 15 degrees: the back of the head is never needed
                assertTrue(abs(pose.pitch) < 0.15f)
            }
            t += 0.1f
        }
        assertTrue(headPose(StateMix(think = 1f), 0f, 0f).pitch < 0) // chin up while thinking
        assertEquals(headPose(StateMix(speak = 1f), 2f, 0f).pitch, headPose(StateMix(speak = 1f), 2f, 1f).pitch, 0f)
    }

    @Test
    fun breezeIsMildSteadyAndBlowsRightAndUp() {
        var t = 0f
        while (t < 120f) {
            val wind = breeze(t)
            assertEquals(1f, hypot(wind.x, wind.y), 1e-5f)
            assertTrue(wind.x > 0.85f && wind.y < 0)
            assertTrue(wind.strength in 0.5f..1f)
            t += 0.5f
        }
        assertTrue(breeze(10f, 1f).y < breeze(10f, 0f).y) // lifts while thinking
    }

    @Test
    fun coloursAndLayoutFollowTheState() {
        val out = FloatArray(3)
        faceColour(StateMix(listen = 1f), 0f, out)
        assertTrue(out[1] > out[0] && out[1] > out[2]) // listening starts green
        faceColour(StateMix(speak = 1f), 1f, out)
        assertTrue(out[0] > out[2]) // speaking ends warm
        faceColour(StateMix(think = 0.2f), 0.5f, out)
        assertTrue(out[2] > 0.9f) // a faint state still has full colour: brightness is handled elsewhere
        val layout = fieldLayout(1220f, 2200f, 3f)
        assertEquals(610f, layout.cx, 0f)
        assertTrue(layout.scale * 2.4f < 2200f && layout.scale * 2.8f < 1220f)
    }
}
