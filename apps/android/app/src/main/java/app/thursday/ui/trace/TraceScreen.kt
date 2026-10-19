package app.thursday.ui.trace

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.thursday.MainActivity
import app.thursday.data.ApiException
import app.thursday.data.Json
import app.thursday.data.StreamMessage
import app.thursday.data.TaskRow
import app.thursday.data.TaskTrace
import app.thursday.domain.BodyPart
import app.thursday.domain.Event
import app.thursday.domain.TraceBody
import app.thursday.domain.epochMillis
import app.thursday.domain.groupTasks
import app.thursday.domain.orderSteps
import app.thursday.graph
import app.thursday.ui.Nav
import app.thursday.ui.Screen
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Chip
import app.thursday.ui.common.CopyButton
import app.thursday.ui.common.Dot
import app.thursday.ui.common.Field
import app.thursday.ui.common.LineIcon
import app.thursday.ui.common.Look
import app.thursday.ui.common.MarkdownText
import app.thursday.ui.common.Panel
import app.thursday.ui.common.SectionTitle
import app.thursday.ui.common.Seg
import app.thursday.ui.common.TopBar
import app.thursday.ui.common.Txt
import app.thursday.ui.relativeTime
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.delay

private val STATE = mapOf("completed" to "Completed", "failed" to "Failed", "canceled" to "Stopped", "input_required" to "Waiting for approval", "working" to "Working", "submitted" to "Starting")
private val DOT = mapOf("completed" to "ok", "failed" to "bad", "input_required" to "warn", "working" to "run", "submitted" to "run")

/**
 * The task list (`taskId` null) or one task's trace. On a wide window the two sit side by side: `open` is the task
 * shown beside the list, which is marked there, and `besideList` says a trace is that one and needs no way back.
 */
@Composable
fun TraceScreen(activity: MainActivity, nav: Nav, taskId: String?, open: String? = null, besideList: Boolean = false) {
    if (taskId == null) TaskList(activity, nav, open) else TaskDetail(activity, nav, taskId, besideList)
}

@Composable
private fun TaskList(activity: MainActivity, nav: Nav, open: String?) {
    val api = activity.graph.api
    var filter by remember { mutableStateOf("all") }
    var q by remember { mutableStateOf("") }
    var tasks by remember { mutableStateOf<List<TaskRow>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var groupBy by remember { mutableStateOf(activity.graph.prefs.traceGroup) }
    var newestFirst by remember { mutableStateOf(activity.graph.prefs.traceNewestFirst) }
    var closed by remember { mutableStateOf(setOf<String>()) }
    val p = LocalPalette.current
    LaunchedEffect(filter, q) {
        delay(if (q.isBlank()) 0 else 250)
        while (true) {
            try {
                tasks = api.tasks(filter, q)
                error = null
            } catch (e: ApiException) {
                error = e.message
            }
            delay(15_000)
        }
    }
    Column(Modifier.fillMaxSize()) {
        TopBar("Trace")
        LazyColumn(contentPadding = PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s2)) {
            item { Field(q, { q = it }, placeholder = "Search tasks") }
            // What to show and how to arrange it: one panel, one choice on each line, the choices under one another.
            item {
                Panel(Modifier.fillMaxWidth(), padding = Space.s3) {
                    Choice("Show", listOf("all" to "All", "running" to "Running", "failed" to "Failed"), filter) { filter = it }
                    Choice("Group by", listOf("chat" to "Chat", "project" to "Project", "none" to "Nothing"), groupBy) {
                        groupBy = it
                        activity.graph.prefs.traceGroup = it
                    }
                    Choice("Order", listOf("new" to "Newest first", "old" to "Oldest first"), if (newestFirst) "new" else "old") {
                        newestFirst = it == "new"
                        activity.graph.prefs.traceNewestFirst = newestFirst
                    }
                }
            }
            error?.let { item { Caption(it, color = LocalPalette.current.danger) } }
            groupTasks(tasks ?: emptyList(), groupBy, newestFirst).forEach { group ->
                if (group.label.isNotEmpty()) item(key = "g" + group.key) {
                    Row(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.sm)).clickable { closed = if (group.key in closed) closed - group.key else closed + group.key }
                            .padding(start = Space.s1, end = Space.s1, top = Space.s3, bottom = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(Space.s2),
                    ) {
                        SectionTitle(group.label, Modifier.weight(1f))
                        Caption(if (group.tasks.size == 1) "1 task" else "${group.tasks.size} tasks")
                        LineIcon("chev", p.muted, 14.dp, Modifier.rotate(if (group.key in closed) 0f else 90f))
                    }
                }
                if (group.key !in closed) items(group.tasks, key = { it.id }) { t ->
                    TaskLine(t, marked = t.id == open, showChat = groupBy != "chat") {
                        if (nav.stack.first() is Screen.Trace) nav.open(Screen.Trace(t.id)) else nav.push(Screen.Trace(t.id))
                    }
                }
            }
            if (tasks?.isEmpty() == true) item { Caption(if (q.isBlank()) "No tasks yet. Ask for something in a chat and its trace appears here." else "No tasks match.") }
        }
    }
}

/** One line of the list's choices: its name on the left and the ways to choose beside it, lined up with the other lines. */
@Composable
private fun Choice(label: String, options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Caption(label, Modifier.width(62.dp), maxLines = 1)
        Seg(options, selected, onSelect)
    }
}

/** One task in the list: how it ended, what was asked, and when. The task open beside the list is marked. */
@Composable
private fun TaskLine(task: TaskRow, marked: Boolean, showChat: Boolean, onClick: () -> Unit) {
    val p = LocalPalette.current
    val shape = RoundedCornerShape(Radius.md)
    Row(
        Modifier.fillMaxWidth().clip(shape).background(if (marked) p.accentSoft else Color.Transparent).border(1.dp, if (marked) p.accent else p.border, shape)
            .clickable(onClick = onClick).padding(horizontal = Space.s3, vertical = Space.s2),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Space.s3),
    ) {
        Dot(DOT[task.state] ?: "")
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Txt(task.instruction.ifEmpty { "Task" }, maxLines = 2)
            Caption(listOfNotNull(STATE[task.state] ?: task.state, task.chatTitle.takeIf { showChat }, relativeTime(task.createdAt)).joinToString(" · "), maxLines = 1)
        }
        LineIcon("chev", p.muted, 16.dp)
    }
}

/** One figure about a task, under its name. */
@Composable
private fun Figure(label: String, value: String, modifier: Modifier) {
    val p = LocalPalette.current
    val shape = RoundedCornerShape(Radius.md)
    Column(modifier.clip(shape).border(1.dp, p.border, shape).padding(horizontal = Space.s3, vertical = Space.s2)) {
        Caption(label, maxLines = 1)
        Txt(value, weight = FontWeight.SemiBold, maxLines = 1)
    }
}

private data class Step(val no: Int, val llm: Map<String, Any?>?, val tools: MutableList<Tool> = mutableListOf(), var compaction: Map<String, Any?>? = null)
private data class Tool(val key: String, val name: String, val args: Any?, var status: String, var result: String = "", var seconds: Double? = null, var approval: String? = null)

private fun steps(events: List<Event>): List<Step> {
    val steps = sortedMapOf<Int, Step>()
    val tools = HashMap<String, Tool>()
    var pendingCompaction: Map<String, Any?>? = null
    for (e in events) {
        val p = e.payload
        when (e.type) {
            "compaction" -> pendingCompaction = p
            "llm_call" -> if (p["agent"] == "main") {
                val no = (p["step"] as? Number)?.toInt() ?: 1
                val existing = steps[no]
                val step = if (existing == null || p["status"] == "ok") Step(no, p, existing?.tools ?: mutableListOf(), existing?.compaction) else existing
                if (pendingCompaction != null) { step.compaction = pendingCompaction; pendingCompaction = null }
                steps[no] = step
            }
            "tool_call" -> {
                val key = p["call_key"].toString()
                val no = key.split(":").getOrNull(1)?.toIntOrNull() ?: 1
                val tool = tools.getOrPut(key) { Tool(key, p["tool"].toString(), p["arguments"], p["status"].toString()).also { steps.getOrPut(no) { Step(no, null) }.tools += it } }
                tool.status = p["status"].toString()
                p["result"]?.let { tool.result = it.toString() }
                (p["seconds"] as? Number)?.let { tool.seconds = it.toDouble() }
            }
            "approval_requested" -> tools.values.lastOrNull { it.name == p["tool"] && it.approval == null }?.approval = "Asked: ${p["summary"]}"
            "approval_resolved" -> (tools[p["call_key"].toString()] ?: tools.values.lastOrNull { it.name == p["tool"] })?.let {
                it.approval = "Approval: ${p["outcome"]}${if (p["by"] == "allow_always_rule") " by an always rule" else ""}"
            }
        }
    }
    return steps.values.toList()
}

@Composable
private fun TaskDetail(activity: MainActivity, nav: Nav, taskId: String, besideList: Boolean) {
    val graph = activity.graph
    val p = LocalPalette.current
    var data by remember { mutableStateOf<TaskTrace?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableStateOf(0) }
    var lastFirst by remember { mutableStateOf(graph.prefs.traceStepsLastFirst) }
    LaunchedEffect(taskId, reload) {
        try {
            data = graph.api.task(taskId)
            error = null
        } catch (e: ApiException) {
            error = e.message
        }
    }
    LaunchedEffect(taskId) {
        graph.stream.messages.collect { m -> if (m is StreamMessage.Stored && m.event.taskId == taskId) { delay(500); reload++ } }
    }
    Column(Modifier.fillMaxSize()) {
        TopBar("Trace", onBack = if (besideList) null else ({ nav.back() }))
        val d = data
        LazyColumn(contentPadding = PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s3)) {
            error?.let { item { Caption(it, color = p.danger) } }
            if (d == null) return@LazyColumn
            val (task, events) = d
            val llm = events.filter { it.type == "llm_call" && it.payload["agent"] == "main" }
            val tokens = llm.sumOf { ((it.payload["usage"] as? Map<*, *>)?.let { u -> ((u["input_tokens"] as? Number)?.toInt() ?: 0) + ((u["output_tokens"] as? Number)?.toInt() ?: 0) }) ?: 0 }
            val seconds = ((if (task.state in setOf("completed", "failed", "canceled")) epochMillis(task.updatedAt) else System.currentTimeMillis()) - epochMillis(events.firstOrNull()?.ts ?: task.createdAt)) / 1000.0
            // The task at a glance: how it ended and where it ran, what was asked, and its figures side by side.
            item {
                Panel(Modifier.fillMaxWidth()) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                        Chip(STATE[task.state] ?: task.state, when (task.state) { "completed" -> p.success; "failed" -> p.danger; "input_required" -> p.warning; else -> p.accentBright })
                        Caption(
                            listOfNotNull(listOfNotNull(task.projectName, task.chatTitle).joinToString(" › ").ifEmpty { null }, relativeTime(task.createdAt)).joinToString(" · "),
                            Modifier.weight(1f), maxLines = 1,
                        )
                    }
                    Txt(task.instruction.ifEmpty { "Task" }, size = Type.title, weight = FontWeight.SemiBold, maxLines = 6)
                    val figures = listOf(
                        "Total time" to "%.1f s".format(seconds),
                        "Model calls" to "${llm.size}",
                        "Tool calls" to "${events.count { it.type == "tool_call" && it.payload["status"] !in setOf("requested", "running") }}",
                        "Tokens" to "%.1fk".format(tokens / 1000.0),
                    )
                    BoxWithConstraints {
                        // Four in a row where there is room, two rows of two on a narrow screen.
                        val inARow = if (maxWidth < 420.dp) 2 else 4
                        Column(verticalArrangement = Arrangement.spacedBy(Space.s2)) {
                            figures.chunked(inARow).forEach { row ->
                                Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) { row.forEach { (label, value) -> Figure(label, value, Modifier.weight(1f)) } }
                            }
                        }
                    }
                }
            }
            val all = steps(events)
            val result: @Composable () -> Unit = {
                Column(verticalArrangement = Arrangement.spacedBy(Space.s2)) {
                    Row(Modifier.padding(start = Space.s1), verticalAlignment = Alignment.CenterVertically) {
                        SectionTitle("Result", Modifier.weight(1f))
                        CopyButton(task.summary, what = "result")
                    }
                    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.lg)).border(1.dp, p.success, RoundedCornerShape(Radius.lg)).padding(Space.s3)) {
                        MarkdownText(task.summary)
                    }
                    Caption("Sent to the voice agent as the task's final result.", Modifier.padding(start = Space.s1))
                }
            }
            if (all.isNotEmpty()) item {
                Row(Modifier.padding(start = Space.s1, top = Space.s2), verticalAlignment = Alignment.CenterVertically) {
                    SectionTitle(if (all.size == 1) "1 step" else "${all.size} steps", Modifier.weight(1f))
                    if (all.size > 1) Btn(if (lastFirst) "Last to first" else "First to last", { lastFirst = !lastFirst; graph.prefs.traceStepsLastFirst = lastFirst }, look = Look.PLAIN, small = true)
                }
            }
            if (d.omitted > 0) item {
                Caption("This task is very long. Its start and its end are shown; ${d.omitted} events in between are left out.", Modifier.padding(start = Space.s1))
            }
            // Last to first reads from the result back to the start, so the result moves to the top.
            if (lastFirst && task.summary.isNotEmpty()) item { result() }
            items(orderSteps(all, lastFirst) { it.copy(tools = it.tools.asReversed().toMutableList()) }, key = { it.no }) { step -> StepCard(step, lastFirst) }
            if (!lastFirst && task.summary.isNotEmpty()) item { result() }
        }
    }
}

@Composable
private fun StepCard(step: Step, markerBelow: Boolean = false) {
    val p = LocalPalette.current
    var open by remember { mutableStateOf(false) }
    val llm = step.llm ?: emptyMap()
    val marker: @Composable () -> Unit = {
        step.compaction?.let { Caption("Earlier turns summarised · ${it["estimated_tokens_before"]} → ${it["estimated_tokens_after"]} tokens", Modifier.padding(vertical = Space.s2)) }
    }
    if (!markerBelow) marker()
    Panel(padding = Space.s3) {
        Row(Modifier.fillMaxWidth().clickable { open = !open }, verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.padding(end = Space.s3).size(26.dp).clip(CircleShape).background(p.accentFill), contentAlignment = Alignment.Center) {
                Txt("${step.no}", color = p.accentBright, size = 12.sp, weight = FontWeight.SemiBold)
            }
            Column(Modifier.weight(1f)) {
                Txt(if (step.tools.isEmpty()) "Answer" else step.tools.joinToString(", ") { it.name }, weight = FontWeight.SemiBold)
                val usage = llm["usage"] as? Map<*, *>
                Caption(listOfNotNull(
                    (llm["ttft_seconds"] as? Number)?.let { "%.2f s to first token".format(it.toDouble()) },
                    (llm["tokens_per_second"] as? Number)?.let { "${Math.round(it.toDouble())} tok/s" },
                    usage?.get("input_tokens")?.let { "$it in / ${usage["output_tokens"] ?: 0} out" },
                ).joinToString(" · "))
            }
            LineIcon("chev", p.muted, 16.dp, Modifier.rotate(if (open) 90f else 0f))
        }
        if (open) {
            (llm["text"] as? String)?.takeIf { it.isNotBlank() }?.let { Caption(it, color = p.muted) }
            step.tools.forEach { tool ->
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).background(p.bg).border(1.dp, p.border, RoundedCornerShape(Radius.md)).padding(Space.s2), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(Space.s2), verticalAlignment = Alignment.CenterVertically) {
                        Chip(tool.status, when (tool.status) { "ok" -> p.success; "unknown" -> p.warning; "requested", "running" -> p.accentBright; else -> p.danger })
                        Txt(tool.name, mono = true, size = Type.caption, weight = FontWeight.SemiBold)
                        tool.seconds?.let { Caption("%.2f s".format(it)) }
                    }
                    Txt(tool.args.toString(), mono = true, size = 12.sp, color = p.muted, maxLines = 4)
                    tool.approval?.let { Caption(it, color = p.warning) }
                    if (tool.result.isNotEmpty()) Txt(tool.result.take(2000), mono = true, size = 12.sp, maxLines = 20)
                }
            }
            if (step.llm != null) Bodies(llm)
        }
    }
    if (markerBelow) marker()
}

/** The request sent and the response received for one model call, as labelled parts; "Raw" shows them as stored. */
@Composable
private fun Bodies(llm: Map<String, Any?>) {
    var which by remember { mutableStateOf("request") }
    var raw by remember { mutableStateOf(false) }
    val stored = llm[if (which == "request") "request_body" else "response_body"]
    val parts = remember(stored, which) {
        if (stored == null) null else if (which == "request") TraceBody.requestParts(stored, Json::pretty) else TraceBody.responseParts(stored, Json::parse, Json::pretty)
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Seg(listOf("request" to "Request", "response" to "Response"), which, { which = it })
        Box(Modifier.weight(1f))
        if (parts != null) Btn(if (raw) "Readable" else "Raw", { raw = !raw }, look = Look.PLAIN, small = true)
    }
    when {
        stored == null -> Caption("Not captured.")
        parts == null || raw -> PartView(BodyPart("Stored body", remember(stored) { Json.pretty(stored) }, code = true))
        parts.isEmpty() -> Caption("Nothing in this $which.")
        else -> parts.forEach { PartView(it) }
    }
    Caption("Headers are never stored. Very long texts are cut and marked.")
}

private const val PART_PREVIEW_LINES = 8
private const val PART_PREVIEW_CHARS = 600

/** One labelled part. Long ones start folded so a whole conversation fits on a phone; a tap opens or folds it. */
@Composable
private fun PartView(part: BodyPart) {
    val p = LocalPalette.current
    val long = part.text.length > PART_PREVIEW_CHARS || part.text.count { it == '\n' } >= PART_PREVIEW_LINES
    var open by remember(part) { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().let { if (long) it.clickable { open = !open } else it }, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
            Txt(part.label.uppercase(), color = p.muted, size = 12.sp, weight = FontWeight.SemiBold)
            if (long) Caption(if (open) "tap to fold" else "tap to show all · ${"%,d".format(part.text.length)} characters", color = p.accentBright)
        }
        val shown = if (long && !open) part.text.take(PART_PREVIEW_CHARS) else part.text
        val lines = if (long && !open) PART_PREVIEW_LINES else Int.MAX_VALUE
        if (part.code) {
            Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).background(p.bg).border(1.dp, p.border, RoundedCornerShape(Radius.md)).padding(Space.s2)) {
                Txt(shown, mono = true, size = 12.sp, maxLines = lines)
            }
        } else {
            Txt(shown, size = Type.caption, maxLines = lines)
        }
    }
}
