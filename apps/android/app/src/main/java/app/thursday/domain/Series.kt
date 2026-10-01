package app.thursday.domain

/*
 * Timed samples to chart shapes, mirroring apps/dashboard/src/features/monitor/series.ts.
 * The x axis is time, so a stretch with no samples shows as a break in the line. Values are averaged
 * into equal time slots. The y axis starts at zero for loads, or fits the data for levels (memory).
 */

data class TimedValue(val t: Long, val v: Double)

/** Runs of connected points (x and y as fractions 0..1, y measured from the top) and lone points. */
data class ChartShape(val runs: List<List<Pair<Float, Float>>>, val dots: List<Pair<Float, Float>>, val min: Double?, val max: Double?)

const val SLOTS = 90

fun slots(points: List<TimedValue>, from: Long, to: Long, count: Int = SLOTS): List<Double?> {
    val sum = DoubleArray(count)
    val n = IntArray(count)
    val width = (to - from).toDouble() / count
    for (p in points) {
        if (p.t < from || p.t > to || !p.v.isFinite()) continue
        val i = minOf(count - 1, ((p.t - from) / width).toInt())
        sum[i] += p.v
        n[i] += 1
    }
    return List(count) { if (n[it] > 0) sum[it] / n[it] else null }
}

fun buildChart(values: List<Double?>, zero: Boolean = false, ceiling: Double? = null, sparse: Boolean = false): ChartShape {
    val present = values.filterNotNull()
    if (present.isEmpty()) return ChartShape(emptyList(), emptyList(), null, null)
    val min = present.min()
    val max = present.max()
    val low: Double
    var high: Double
    if (zero) {
        low = 0.0
        high = ceiling ?: maxOf(max * 1.1, 1e-9)
    } else {
        val pad = maxOf((max - min) * 0.15, kotlin.math.abs(max) * 0.02, 1e-9)
        low = maxOf(0.0, min - pad)
        high = if (ceiling != null) minOf(ceiling, max + pad) else max + pad
        if (high <= low) high = low + 1
    }
    fun x(i: Int) = if (values.size == 1) 0.5f else i.toFloat() / (values.size - 1)
    fun y(v: Double) = (1 - (v.coerceIn(low, high) - low) / (high - low)).toFloat()

    val runs = mutableListOf<List<Pair<Float, Float>>>()
    var run = mutableListOf<Pair<Float, Float>>()
    values.forEachIndexed { i, v ->
        if (v == null) {
            if (!sparse && run.isNotEmpty()) {
                runs += run
                run = mutableListOf()
            }
        } else run += x(i) to y(v)
    }
    if (run.isNotEmpty()) runs += run
    val lines = runs.filter { it.size > 1 }
    val dots = runs.filter { it.size == 1 }.map { it[0] } + if (sparse) lines.flatten() else emptyList()
    return ChartShape(lines, dots, min, max)
}

fun ago(ms: Long): String {
    val s = maxOf(0, ms / 1000)
    return when {
        s < 60 -> "$s s ago"
        s < 3600 -> "${Math.round(s / 60.0)} min ago"
        s < 86_400 -> "${Math.round(s / 3600.0)} h ago"
        else -> "${Math.round(s / 86_400.0)} d ago"
    }
}

fun spanText(range: String): String = when (range) {
    "15m" -> "the last 15 minutes"
    "1h" -> "the last hour"
    "24h" -> "the last 24 hours"
    "7d" -> "the last 7 days"
    else -> range
}
