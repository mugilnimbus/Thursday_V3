package app.thursday.ui.trace

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.thursday.MainActivity
import app.thursday.data.ApiException
import app.thursday.data.StreamMessage
import app.thursday.data.TaskRow
import app.thursday.domain.Event
import app.thursday.domain.epochMillis
import app.thursday.domain.groupTasks
import app.thursday.graph
import app.thursday.ui.Nav
import app.thursday.ui.Screen
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Chip
import app.thursday.ui.common.Dot
import app.thursday.ui.common.Field
import app.thursday.ui.common.LineIcon
import app.thursday.ui.common.MarkdownText
import app.thursday.ui.common.Panel
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

@Composable
fun TraceScreen(activity: MainActivity, nav: Nav, taskId: String?) {
    if (taskId == null) TaskList(activity, nav) else TaskDetail(activity, nav, taskId)
}

@Composable
private fun TaskList(activity: MainActivity, nav: Nav) {
    val api = activity.graph.api
    var filter by remember { mutableStateOf("all") }
    var q by remember { mutableStateOf("") }
    var tasks by remember { mutableStateOf<List<TaskRow>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var groupBy by remember { mutableStateOf(activity.graph.prefs.traceGroup) }
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
            item { Seg(listOf("all" to "All", "running" to "Running", "failed" to "Failed"), filter, { filter = it }) }
            item {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                    Caption("Group by")
                    Seg(listOf("chat" to "Chat", "project" to "Project", "none" to "Nothing"), groupBy, { groupBy = it; activity.graph.prefs.traceGroup = it })
                }
            }
            error?.let { item { Caption(it, color = LocalPalette.current.danger) } }
            groupTasks(tasks ?: emptyList(), groupBy).forEach { group ->
                if (group.label.isNotEmpty()) item(key = "g" + group.key) {
                    Row(
                        Modifier.fillMaxWidth().clickable { closed = if (group.key in closed) closed - group.key else closed + group.key }.padding(top = Space.s2, bottom = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(Space.s2),
                    ) {
                        LineIcon("chev", p.muted, 14.dp, Modifier.rotate(if (group.key in closed) 0f else 90f))
                        Txt(group.label, Modifier.weight(1f), color = p.muted, size = Type.caption, weight = FontWeight.SemiBold, maxLines = 1)
                        Caption("${group.tasks.size}")
                    }
                }
                if (group.key !in closed) items(group.tasks, key = { it.id }) { t ->
                    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).clickable { nav.push(Screen.Trace(t.id)) }.padding(Space.s3)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                            Dot(DOT[t.state] ?: "")
                            Txt(t.instruction.ifEmpty { "Task" }, weight = FontWeight.Medium, maxLines = 2)
                        }
                        Caption("${STATE[t.state] ?: t.state}${if (groupBy != "chat") t.chatTitle?.let { " · $it" } ?: "" else ""} · ${relativeTime(t.createdAt)}", Modifier.padding(start = 16.dp))
                    }
                }
            }
            if (tasks?.isEmpty() == true) item { Caption(if (q.isBlank()) "No tasks yet. Ask for something in a chat and its trace appears here." else "No tasks match.") }
        }
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
private fun TaskDetail(activity: MainActivity, nav: Nav, taskId: String) {
    val graph = activity.graph
    val p = LocalPalette.current
    var data by remember { mutableStateOf<Pair<TaskRow, List<Event>>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableStateOf(0) }
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
        TopBar("Trace", onBack = { nav.back() })
        val d = data
        LazyColumn(contentPadding = PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s3)) {
            error?.let { item { Caption(it, color = p.danger) } }
            if (d == null) return@LazyColumn
            val (task, events) = d
            val llm = events.filter { it.type == "llm_call" && it.payload["agent"] == "main" }
            val tokens = llm.sumOf { ((it.payload["usage"] as? Map<*, *>)?.let { u -> ((u["input_tokens"] as? Number)?.toInt() ?: 0) + ((u["output_tokens"] as? Number)?.toInt() ?: 0) }) ?: 0 }
            val seconds = ((if (task.state in setOf("completed", "failed", "canceled")) epochMillis(task.updatedAt) else System.currentTimeMillis()) - epochMillis(events.firstOrNull()?.ts ?: task.createdAt)) / 1000.0
            item {
                Panel {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Txt(task.instruction.ifEmpty { "Task" }, Modifier.weight(1f), size = Type.title, weight = FontWeight.SemiBold)
                        Chip(STATE[task.state] ?: task.state, when (task.state) { "completed" -> p.success; "failed" -> p.danger; "input_required" -> p.warning; else -> p.accentBright })
                    }
                    Caption("%.1f s total · %d LLM calls · %d tool calls · %.1fk tokens".format(seconds, llm.size, events.count { it.type == "tool_call" && it.payload["status"] !in setOf("requested", "running") }, tokens / 1000.0))
                }
            }
            items(steps(events), key = { it.no }) { step -> StepCard(step) }
            if (task.summary.isNotEmpty()) item {
                Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.lg)).border(1.dp, p.success, RoundedCornerShape(Radius.lg)).padding(Space.s3)) {
                    Column {
                        MarkdownText(task.summary)
                        Caption("Final result, sent to the voice agent")
                    }
                }
            }
        }
    }
}

@Composable
private fun StepCard(step: Step) {
    val p = LocalPalette.current
    var open by remember { mutableStateOf(false) }
    val llm = step.llm ?: emptyMap()
    step.compaction?.let { Caption("Earlier turns summarised · ${it["estimated_tokens_before"]} → ${it["estimated_tokens_after"]} tokens", Modifier.padding(bottom = Space.s2)) }
    Panel(padding = Space.s3) {
        Row(Modifier.clickable { open = !open }, verticalAlignment = Alignment.CenterVertically) {
            Txt("${step.no}", Modifier.padding(end = Space.s3), weight = FontWeight.SemiBold, size = Type.caption)
            Column(Modifier.weight(1f)) {
                Txt(if (step.tools.isEmpty()) "Answer" else step.tools.joinToString(", ") { it.name }, weight = FontWeight.SemiBold)
                val usage = llm["usage"] as? Map<*, *>
                Caption(listOfNotNull(
                    (llm["ttft_seconds"] as? Number)?.let { "%.2f s to first token".format(it.toDouble()) },
                    (llm["tokens_per_second"] as? Number)?.let { "${Math.round(it.toDouble())} tok/s" },
                    usage?.let { "${it["input_tokens"]} in / ${it["output_tokens"]} out" },
                ).joinToString(" · "))
            }
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
        }
    }
}

