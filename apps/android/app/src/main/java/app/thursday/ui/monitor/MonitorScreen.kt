package app.thursday.ui.monitor

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.data.LlmCall
import app.thursday.data.MetricsSample
import app.thursday.data.Parse
import app.thursday.domain.ChartShape
import app.thursday.domain.TimedValue
import app.thursday.domain.ago
import app.thursday.domain.buildChart
import app.thursday.domain.epochMillis
import app.thursday.domain.formatContext
import app.thursday.domain.slots
import app.thursday.domain.spanText
import app.thursday.domain.tileColumns
import app.thursday.domain.waitText
import app.thursday.graph
import app.thursday.ui.clock
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Dot
import app.thursday.ui.common.Gauge
import app.thursday.ui.common.Panel
import app.thursday.ui.common.SectionTitle
import app.thursday.ui.common.Seg
import app.thursday.ui.common.Spark
import app.thursday.ui.common.TopBar
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.time.Instant

private val SPAN = mapOf("15m" to 900_000L, "1h" to 3_600_000L, "24h" to 86_400_000L, "7d" to 604_800_000L)
private val NAMES = mapOf("gateway" to "Gateway", "voice_agent" to "Voice agent", "main_agent" to "Main agent")
private val STORAGE = mapOf(
    "gateway" to "Gateway · chats and events", "main_agent" to "Main agent · tasks and saved steps",
    "voice_agent" to "Voice agent · conversations", "tool_server" to "Tool server · call logs", "logs" to "Log files",
)

/**
 * PC and service health. Live values arrive every second over a socket held only while this screen shows.
 * Every graph covers the chosen period on a real time axis; a break in a line means no measurements then.
 * In a wide pane (a tablet, a phone on its side) the tiles and panels go two to a row.
 */
@Composable
fun MonitorScreen(activity: MainActivity) {
    val graph = activity.graph
    val p = LocalPalette.current
    var range by remember { mutableStateOf("1h") }
    var history by remember { mutableStateOf<List<MetricsSample>>(emptyList()) }
    var calls by remember { mutableStateOf<List<LlmCall>>(emptyList()) }
    var latest by remember { mutableStateOf<MetricsSample?>(null) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val approvals by graph.live.approvals.collectAsStateWithLifecycle()

    LaunchedEffect(range) {
        while (true) {
            runCatching { graph.api.monitor(range) }.onSuccess { d ->
                history = d.history
                calls = d.calls
                if (d.latest != null) latest = d.latest
            }
            delay(20_000) // picks up new model calls; live samples arrive on the socket
        }
    }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(1000) } }
    DisposableEffect(Unit) {
        var socket: WebSocket? = null
        var stopped = false
        fun open() {
            val request = graph.api.metricsRequest() ?: return
            socket = graph.api.client.newWebSocket(request, object : WebSocketListener() {
                override fun onMessage(webSocket: WebSocket, text: String) {
                    val o = runCatching { JSONObject(text) }.getOrNull() ?: return
                    if (o.optString("kind") != "metrics") return
                    val sample = Parse.sample(o.getJSONObject("sample"))
                    latest = sample
                    val since = System.currentTimeMillis() - (SPAN[range] ?: 3_600_000L)
                    history = (history.filter { epochMillis(it.ts) >= since } + sample).takeLast(4000)
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    if (!stopped) graph.scope.launch {
                        delay(3000)
                        if (!stopped) open()
                    }
                }
            })
        }
        open()
        onDispose {
            stopped = true
            socket?.close(1000, null)
        }
    }

    val from = now - (SPAN[range] ?: 3_600_000L)
    val timed = remember(history) { history.map { epochMillis(it.ts) to it } }
    fun chart(zero: Boolean = false, pick: (MetricsSample) -> Double?): ChartShape =
        buildChart(slots(timed.mapNotNull { (t, s) -> pick(s)?.let { TimedValue(t, it) } }, from, now), zero = zero)
    fun callChart(agent: String, pick: (LlmCall) -> Double?): ChartShape =
        buildChart(slots(calls.filter { it.agent == agent }.mapNotNull { c -> pick(c)?.let { TimedValue(epochMillis(c.ts), it) } }, from, now), zero = true, sparse = true)
    fun span(c: ChartShape, fmt: (Double) -> String): String = when {
        c.min == null || c.max == null -> "no data in this period"
        fmt(c.min) == fmt(c.max) -> "steady at ${fmt(c.min)}"
        else -> "${fmt(c.min)} to ${fmt(c.max)}"
    }
    fun hue(f: Double): Color = when { f >= 0.9 -> p.alert; f >= 0.75 -> p.warm; else -> p.calm }

    val s = latest
    val age = s?.let { ((now - epochMillis(it.ts)) / 1000).coerceAtLeast(0) }
    val used = s?.gpus?.sumOf { it.usedMb } ?: 0.0
    val total = s?.gpus?.sumOf { it.totalMb } ?: 0.0
    val down = s?.services?.filter { !it.up }?.map { NAMES[it.name] ?: it.name } ?: emptyList()

    // What the Monitor shows, as slots that the layout below puts one or two to a row. A slot is drawn only while
    // its row is on screen, so the graph of a tile that is scrolled away is not worked out.
    val hardware = buildList {
        s?.gpus?.forEach { gpu ->
            add(Slot("gpu${gpu.index}") { place ->
                val f = if (gpu.totalMb > 0) gpu.usedMb / gpu.totalMb else 0.0
                val c = chart { it.gpus.getOrNull(gpu.index)?.usedMb }
                Tile("GPU ${gpu.index}", "${gpu.name} · VRAM", "%.0f / %.0f GB".format(gpu.usedMb / 1024, gpu.totalMb / 1024), hue(f), c, span(c) { "%.1f GB".format(it / 1024) }, place)
            })
        }
        if (s != null) {
            add(Slot("ram") { place ->
                val c = chart { if (it.ramTotalMb > 0) it.ramUsedMb * 100 / it.ramTotalMb else null }
                Tile("RAM", "of %.0f GB".format(s.ramTotalMb / 1024), "${Math.round(s.ramUsedMb * 100 / s.ramTotalMb)}%", hue(s.ramUsedMb / s.ramTotalMb), c, span(c) { "${Math.round(it)}%" }, place)
            })
            add(Slot("cpu") { place ->
                val c = chart(zero = true) { it.cpu }
                Tile("CPU", "", "${Math.round(s.cpu)}%", hue(s.cpu / 100), c, c.max?.let { "peak ${Math.round(it)}%" } ?: "no data in this period", place)
            })
            add(Slot("network") { place ->
                val c = chart(zero = true) { it.rx + it.tx }
                Tile("Network", "down · up", "${rate(s.rx)} · ${rate(s.tx)}", p.info, c, c.max?.let { "peak ${rate(it)}" } ?: "no data in this period", place)
            })
        }
    }
    val models = buildList {
        listOf("main" to "Main", "voice" to "Voice").forEach { (agent, label) ->
            add(Slot(agent) { place ->
                val mine = calls.filter { it.agent == agent }
                val last = mine.lastOrNull()
                val caption = if (last == null) "no calls in ${spanText(range)}"
                else "last call ${ago(now - epochMillis(last.ts))} · ${mine.size} ${if (mine.size == 1) "call" else "calls"}, one dot each"
                Tile(label, "tokens/s", last?.tokensPerSecond?.let { "${Math.round(it)}" } ?: "—", p.info, callChart(agent) { it.tokensPerSecond }, caption, place)
            })
            add(Slot("$agent first token") { place ->
                // From sending the request to the first text or tool call back; the last call that has one.
                val wait = calls.lastOrNull { it.agent == agent && it.ttftSeconds != null }?.ttftSeconds
                val waits = callChart(agent) { it.ttftSeconds }
                Tile(label, "time to first token", wait?.let(::waitText) ?: "—", p.calm, waits,
                    if (waits.max == null) "no calls in ${spanText(range)}" else "${span(waits, ::waitText)} · one dot per call", place)
            })
        }
        add(Slot("context") { place ->
            fun last(agent: String) = calls.lastOrNull { it.agent == agent }
            fun pct(agent: String) = last(agent)?.let { c -> if (c.inputTokens != null && (c.contextLength ?: 0) > 0) "${Math.round(c.inputTokens * 100.0 / c.contextLength!!)}%" else null } ?: "—"
            val main = last("main")?.contextLength
            val voice = last("voice")?.contextLength
            Tile("Context in use", "main · voice", "${pct("main")} · ${pct("voice")}", p.accent, null,
                if (main != null || voice != null) "${formatContext(main)} and ${formatContext(voice)} windows" else "no model calls in ${spanText(range)}", place)
        })
    }
    val panels = listOf(
        Slot("services") { place ->
            Panel(place) {
                Txt("Services", weight = FontWeight.SemiBold)
                listOf("gateway", "voice_agent", "main_agent").forEach { name ->
                    val svc = s?.services?.firstOrNull { it.name == name }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Dot(if (svc?.up == true) "ok" else if (s != null) "bad" else "")
                        Txt(" ${NAMES[name]}", Modifier.weight(1f))
                        Caption(if (svc?.up == true) svc.latencyMs?.let { if (it < 1) "<1 ms" else "${Math.round(it)} ms" } ?: "" else if (s != null) "not running" else "—")
                    }
                }
            }
        },
        Slot("waiting") { place ->
            Panel(place) {
                Txt("Waiting and queued", weight = FontWeight.SemiBold)
                Caption("Approvals waiting: ${approvals.size}")
                Caption("Messages queued: ${s?.num("gateway", "queued_messages")?.toInt() ?: "—"}")
                Caption("Events not yet delivered: ${((s?.num("main_agent", "outbox_backlog") ?: 0.0) + (s?.num("voice_agent", "outbox_backlog") ?: 0.0)).toInt()}")
                Caption("PC kept awake: ${when (s?.services?.firstOrNull { it.name == "main_agent" }?.metrics?.get("keeping_awake")) { true -> "Yes"; false -> "No"; else -> "—" }}")
            }
        },
        Slot("stored") { place ->
            // The size is measured about once a minute, so the newest sample that has it is the one shown.
            val stored = (s?.storage?.takeIf { it.isNotEmpty() } ?: history.lastOrNull { it.storage.isNotEmpty() }?.storage).orEmpty()
            Panel(place) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Txt("Stored data", Modifier.weight(1f), weight = FontWeight.SemiBold)
                    Txt(if (stored.isEmpty()) "—" else bytesText(stored.sumOf { it.bytes }), weight = FontWeight.SemiBold)
                }
                stored.forEach { part ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Caption(STORAGE[part.name] ?: part.name, Modifier.weight(1f))
                        Caption(bytesText(part.bytes), color = p.text)
                    }
                }
                Caption("Databases and logs on the PC. How long working data is kept is chosen in the dashboard's settings, under General.")
            }
        },
    )

    Column(Modifier.fillMaxSize()) {
        TopBar("Monitor")
        BoxWithConstraints(Modifier.fillMaxSize()) {
            // One to a row on a phone held upright; two where the pane is wide enough (a tablet, a phone on its side).
            val columns = tileColumns(maxWidth.value)
            LazyColumn(contentPadding = PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s3)) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Dot(if (age == null) "bad" else if (age < 15) "ok" else "warn")
                        Caption(if (age == null) " No data" else " Updated $age s ago", Modifier.weight(1f))
                        Seg(listOf("15m" to "15m", "1h" to "1h", "24h" to "24h", "7d" to "7d"), range, { range = it })
                    }
                }
                item {
                    val story: @Composable ColumnScope.() -> Unit = {
                        Caption("Right now")
                        Txt(
                            when {
                                s == null -> "No measurements yet."
                                down.isNotEmpty() -> "${down.joinToString(" and ")} ${if (down.size > 1) "are" else "is"} not running."
                                else -> "Everything is running."
                            },
                            size = Type.title, weight = FontWeight.SemiBold,
                        )
                        if (total > 0 && used / total >= 0.85) Txt("GPU memory is nearly full, so a larger context will not fit until a model is unloaded.", color = p.alert, weight = FontWeight.SemiBold)
                    }
                    Panel(Modifier.fillMaxWidth()) {
                        if (columns > 1) {
                            // Room beside the words: the gauge goes there, as on the dashboard.
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(Space.s3), content = story)
                                if (total > 0) Gauge(used / total, "GPU memory", hue(used / total))
                            }
                        } else {
                            story()
                            if (total > 0) Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { Gauge(used / total, "GPU memory", hue(used / total)) }
                        }
                    }
                }
                item {
                    SectionTitle("Hardware")
                    Caption("Graphs show ${spanText(range)}: ${clock(Instant.ofEpochMilli(from).toString())} to ${clock(Instant.ofEpochMilli(now).toString())}. A break in a line means no measurements then.")
                }
                rows(hardware, columns)
                item { SectionTitle("Models") }
                rows(models, columns)
                rows(panels, columns)
            }
        }
    }
}

/** One thing the Monitor shows. [draw] is given the place it has in its row. */
private class Slot(val key: String, val draw: @Composable (Modifier) -> Unit)

/**
 * The slots, [columns] to a row: equally wide, and each as tall as the tallest in its row. One left over at the end
 * takes the whole row.
 */
private fun LazyListScope.rows(slots: List<Slot>, columns: Int) {
    slots.chunked(columns).forEach { row ->
        item(key = row.first().key) {
            if (row.size == 1) row.first().draw(Modifier.fillMaxWidth())
            else Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(Space.s3)) {
                row.forEach { it.draw(Modifier.weight(1f).fillMaxHeight()) }
            }
        }
    }
}

/** A size as people read it: 154 MB, 1.2 GB. */
private fun bytesText(bytes: Long): String = when {
    bytes >= 1_000_000_000 -> "%.1f GB".format(java.util.Locale.US, bytes / 1e9)
    bytes >= 1_000_000 -> "${Math.round(bytes / 1e6)} MB"
    bytes >= 1_000 -> "${Math.round(bytes / 1e3)} kB"
    else -> "$bytes B"
}

private fun rate(bytes: Double): String = when {
    bytes >= 1_048_576 -> "%.1f MB/s".format(bytes / 1_048_576)
    bytes >= 1024 -> "${Math.round(bytes / 1024)} kB/s"
    else -> "${Math.round(bytes)} B/s"
}

/**
 * A state tile: label, value, the range seen in the period, and an edge-to-edge graph along the bottom (also when
 * the tile is taller than it needs to be, beside a taller one).
 */
@Composable
private fun Tile(label: String, sub: String, value: String, color: Color, chart: ChartShape?, caption: String, modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    Column(
        modifier.clip(RoundedCornerShape(Radius.lg))
            .background(Brush.verticalGradient(listOf(color.copy(alpha = 0.16f), p.bg)))
            .border(1.dp, color.copy(alpha = 0.55f), RoundedCornerShape(Radius.lg)),
    ) {
        Column(Modifier.padding(start = Space.s4, end = Space.s4, top = Space.s3, bottom = if (chart == null) Space.s3 else 0.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row { Txt(label, size = Type.caption, weight = FontWeight.SemiBold, maxLines = 1); if (sub.isNotEmpty()) Caption("  $sub", maxLines = 1) }
            Txt(value, size = Type.large, weight = FontWeight.SemiBold)
            Caption(caption)
        }
        if (chart != null) {
            Spacer(Modifier.weight(1f))
            Spark(chart, color)
        }
    }
}
