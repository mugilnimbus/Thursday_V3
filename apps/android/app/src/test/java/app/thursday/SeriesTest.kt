package app.thursday

import app.thursday.domain.TimedValue
import app.thursday.domain.ago
import app.thursday.domain.buildChart
import app.thursday.domain.slots
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SeriesTest {
    @Test
    fun samplesArePlacedByTimeWithEmptySlotsForGaps() {
        val points = listOf(TimedValue(0, 10.0), TimedValue(50, 20.0), TimedValue(950, 40.0), TimedValue(999, 60.0))
        assertEquals(listOf(15.0, null, null, null, null, null, null, null, null, 50.0), slots(points, 0, 1000, 10))
        assertEquals(listOf(null, null), slots(listOf(TimedValue(-5, 1.0), TimedValue(5000, 1.0)), 0, 1000, 2))
    }

    @Test
    fun aGapBreaksTheLine() {
        assertEquals(2, buildChart(listOf(1.0, 2.0, 3.0, null, null, 4.0, 5.0)).runs.size)
    }

    @Test
    fun occasionalEventsAreJoinedAndMarked() {
        val chart = buildChart(listOf(80.0, null, null, 100.0, null, 90.0), sparse = true)
        assertEquals(1, chart.runs.size)
        assertEquals(3, chart.dots.size)
    }

    @Test
    fun levelsFitTheirOwnRangeSoChangesShow() {
        val values = listOf(10_000.0, 10_100.0, 10_050.0)
        fun spread(run: List<Pair<Float, Float>>) = run.maxOf { it.second } - run.minOf { it.second }
        val fitted = buildChart(values)
        val fromZero = buildChart(values, zero = true, ceiling = 12_288.0)
        assertTrue(spread(fitted.runs[0]) > spread(fromZero.runs[0]) * 10)
        assertEquals(10_000.0, fitted.min!!, 0.0)
    }

    @Test
    fun oneSampleIsADotAndNoDataIsEmpty() {
        assertEquals(1, buildChart(listOf(null, 5.0, null)).dots.size)
        assertNull(buildChart(listOf(null, null)).max)
    }

    @Test
    fun agesReadNaturally() {
        assertEquals(listOf("5 s ago", "3 min ago", "2 h ago"), listOf(ago(5000), ago(180_000), ago(7_200_000)))
    }
}
