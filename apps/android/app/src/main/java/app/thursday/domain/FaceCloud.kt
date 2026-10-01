package app.thursday.domain

import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.min
import kotlin.math.sqrt

/*
 * The face as a cloud of particles, read from assets/face-cloud.bin (the same file the dashboard ships).
 *
 * The file holds one 12-byte record per particle after a 16-byte header:
 *   header  "TFC1", count (uint32), spacing between neighbours in face units (float32), reserved (uint32)
 *   record  x, y, z (int16, face units / 4 * 32767)   position; z is toward the viewer
 *           b, edge, jaw, mouth (uint8, 0..255)        brightness; how loose the particle is (1 = drifting around
 *                                                      the head); how much it drops with the jaw; how close it is
 *                                                      to the lips
 *           nx, ny (int8, -127..127)                   which way the surface faces at this spot
 * Face units: x from about -1 (left) to 1 (right), y from -1.2 (top of the head) to 1.2 (chin).
 * The records are in a shuffled order, so any first part of the file is an even sample of the whole face: a phone
 * reads fewer of them and draws them a little larger.
 */

const val FACE_RECORD_BYTES = 12
private const val HEADER_BYTES = 16
private const val MAGIC = 0x31434654 // "TFC1" read as a little-endian int

/**
 * @param count particles held here (may be fewer than the file has)
 * @param spacing distance between neighbouring particles in face units, for the particles held here
 */
class FaceCloud(
    val count: Int,
    val spacing: Float,
    val x: FloatArray, val y: FloatArray, val z: FloatArray,
    val b: FloatArray, val edge: FloatArray, val jaw: FloatArray, val mouth: FloatArray,
    val nx: FloatArray, val ny: FloatArray,
)

/** Reads the first [limit] particles of a face cloud file. Throws [IllegalArgumentException] if it is not one. */
fun parseFaceCloud(bytes: ByteArray, limit: Int = Int.MAX_VALUE): FaceCloud {
    require(bytes.size >= HEADER_BYTES) { "face cloud: file is too short" }
    val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
    require(buffer.getInt(0) == MAGIC) { "face cloud: not a face cloud file" }
    val total = buffer.getInt(4)
    val spacing = buffer.getFloat(8)
    require(total >= 0 && bytes.size == HEADER_BYTES + total * FACE_RECORD_BYTES) { "face cloud: size does not match its particle count" }
    require(spacing > 0) { "face cloud: bad spacing" }
    val count = min(total, limit)
    val cloud = FaceCloud(
        count, if (count > 0) spacing * sqrt(total.toFloat() / count) else spacing,
        FloatArray(count), FloatArray(count), FloatArray(count),
        FloatArray(count), FloatArray(count), FloatArray(count), FloatArray(count),
        FloatArray(count), FloatArray(count),
    )
    for (i in 0 until count) {
        val at = HEADER_BYTES + i * FACE_RECORD_BYTES
        cloud.x[i] = buffer.getShort(at) / 32767f * 4
        cloud.y[i] = buffer.getShort(at + 2) / 32767f * 4
        cloud.z[i] = buffer.getShort(at + 4) / 32767f * 4
        cloud.b[i] = (buffer.get(at + 6).toInt() and 0xFF) / 255f
        cloud.edge[i] = (buffer.get(at + 7).toInt() and 0xFF) / 255f
        cloud.jaw[i] = (buffer.get(at + 8).toInt() and 0xFF) / 255f
        cloud.mouth[i] = (buffer.get(at + 9).toInt() and 0xFF) / 255f
        cloud.nx[i] = buffer.get(at + 10) / 127f
        cloud.ny[i] = buffer.get(at + 11) / 127f
    }
    return cloud
}
