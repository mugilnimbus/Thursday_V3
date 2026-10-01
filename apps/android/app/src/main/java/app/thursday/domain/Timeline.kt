package app.thursday.domain

import java.time.OffsetDateTime

/*
 * Turn raw gateway events into what the screens show: task cards and agent stats.
 * Pure Kotlin (no Android, no JSON library), mirroring apps/dashboard/src/lib/state/timeline.ts.
 */

data class Event(
    val pos: Long,
    val source: String,
    val ts: String,
    val chatId: String?,
    val taskId: String?,
    val type: String,
    val payload: Map<String, Any?>,
)

enum class Tone { OK, WARN, RUN, BAD, INFO }

data class TaskLine(val text: String, val tone: Tone, val seconds: Double)

data class TaskView(
    val taskId: String,
    val instruction: String,
    val state: String,
    val pauseState: String,
    val step: Int,
    val summary: String,
    val lines: List<TaskLine>,
    val firstPos: Long,
) {
    val terminal: Boolean get() = state in TERMINAL
}

val TERMINAL = setOf("completed", "failed", "canceled")

fun epochMillis(iso: String): Long =
    runCatching { OffsetDateTime.parse(iso).toInstant().toEpochMilli() }.getOrDefault(0L)

private const val ARG_LIMIT = 60
private val HIDDEN_ARGS = setOf("content", "diff", "new_string", "old_string")

fun shortArgs(args: Any?): String {
    val map = args as? Map<*, *> ?: return ""
    val text = map.entries.filter { it.key !in HIDDEN_ARGS }.joinToString(" ") { (_, v) -> v as? String ?: v.toString() }
    return if (text.length > ARG_LIMIT) text.take(ARG_LIMIT - 1) + "…" else text
}

fun firstLine(text: Any?): String {
    val line = (text?.toString() ?: "").lineSequence().firstOrNull { it.isNotBlank() }?.trim() ?: ""
    return if (line.length > 80) line.take(79) + "…" else line
}

fun summarize(tool: String, result: Any?): String {
    val lines = (result?.toString() ?: "").lines().filter { it.isNotBlank() }
    if (tool == "fs.list" && lines.size > 1) return "${lines.size} entries"
    return firstLine(result) + if (lines.size > 1) " …" else ""
}

private val OUTCOME = mapOf("allowed" to "you allowed it", "denied" to "you said no", "timed_out" to "no answer in time", "canceled" to "cancelled")

private class Builder(val taskId: String, val firstPos: Long, val startMs: Long) {
    var instruction = ""
    var state = "submitted"
    var pauseState = "none"
    var step = 0
    var summary = ""
    val lines = mutableListOf<TaskLine>()
    fun build() = TaskView(taskId, instruction, state, pauseState, step, summary, lines.toList(), firstPos)
}

fun buildTasks(events: List<Event>): Map<String, TaskView> {
    val tasks = LinkedHashMap<String, Builder>()
    for (e in events) {
        val id = e.taskId ?: continue
        val task = tasks.getOrPut(id) { Builder(id, e.pos, epochMillis(e.ts)) }
        val seconds = maxOf(0.0, (epochMillis(e.ts) - task.startMs) / 1000.0)
        val p = e.payload
        when (e.type) {
            "delegation" -> if (e.source == "main" || task.instruction.isEmpty()) {
                task.instruction = p["instruction"]?.toString() ?: task.instruction
                if (e.source == "main") task.lines += TaskLine("Delegated “${task.instruction}”", Tone.OK, seconds)
            }
            "task_state" -> {
                task.state = p["state"]?.toString() ?: task.state
                task.pauseState = p["pause_state"]?.toString() ?: task.pauseState
                (p["summary"] as? String)?.takeIf { it.isNotEmpty() }?.let { task.summary = it }
                when (task.state) {
                    "completed" -> task.lines += TaskLine("Done", Tone.OK, seconds)
                    "failed" -> task.lines += TaskLine("Failed: ${firstLine(p["summary"])}", Tone.BAD, seconds)
                    "canceled" -> task.lines += TaskLine("Stopped", Tone.BAD, seconds)
                }
                if (p["pause_state"] == "paused" && task.state == "working") task.lines += TaskLine("Paused", Tone.WARN, seconds)
            }
            "llm_call" -> if (p["agent"] == "main") {
                if (p["status"] == "ok") task.step = maxOf(task.step, (p["step"] as? Number)?.toInt() ?: 0)
                if (p["status"].toString().startsWith("error")) task.lines += TaskLine("Model call failed (${p["status"]}), retrying", Tone.BAD, seconds)
            }
            "tool_call" -> {
                val status = p["status"].toString()
                if (status != "requested" && status != "running") {
                    val tone = when (status) { "ok" -> Tone.OK; "unknown" -> Tone.WARN; else -> Tone.BAD }
                    val tool = p["tool"].toString()
                    val result = if (status == "unknown") "outcome unknown after a restart" else summarize(tool, p["result"])
                    task.lines += TaskLine("$tool ${shortArgs(p["arguments"])} → $result".trim(), tone, seconds)
                }
            }
            "approval_requested" -> task.lines += TaskLine("Asked: ${p["summary"]}", Tone.WARN, seconds)
            "approval_resolved" -> {
                val outcome = p["outcome"].toString()
                val rule = if (p["by"] == "allow_always_rule") " (always allowed)" else ""
                task.lines += TaskLine("Approval: ${OUTCOME[outcome] ?: outcome}$rule", if (outcome == "allowed") Tone.OK else Tone.WARN, seconds)
            }
            "compaction" -> task.lines += TaskLine("Summarised earlier turns to fit the context", Tone.INFO, seconds)
        }
    }
    return tasks.mapValues { it.value.build() }
}

/** The line shown with a pulsing dot while a task still works. */
fun liveLine(task: TaskView): TaskLine? = when {
    task.terminal -> null
    task.state == "input_required" -> TaskLine("Waiting for your approval…", Tone.WARN, 0.0)
    task.pauseState == "paused" -> null
    task.pauseState == "pausing" -> TaskLine("Finishing this step, then pausing…", Tone.RUN, 0.0)
    else -> TaskLine("Working…", Tone.RUN, 0.0)
}

data class AgentStats(val tokensPerSecond: Int?, val contextPercent: Int?, val contextLength: Int?)

fun agentStats(events: List<Event>, agent: String): AgentStats {
    val e = events.lastOrNull { it.type == "llm_call" && it.payload["agent"] == agent && it.payload["status"] == "ok" }
        ?: return AgentStats(null, null, null)
    val length = (e.payload["context_length"] as? Number)?.toInt()
    val input = ((e.payload["usage"] as? Map<*, *>)?.get("input_tokens") as? Number)?.toInt()
    val tps = (e.payload["tokens_per_second"] as? Number)?.toDouble()
    return AgentStats(
        tps?.let { Math.round(it).toInt() },
        if (length != null && length > 0 && input != null) minOf(100, Math.round(input * 100.0 / length).toInt()) else null,
        length,
    )
}

fun formatContext(length: Int?): String = when {
    length == null || length == 0 -> "unknown"
    length >= 1000 -> "${Math.round(length / 1000.0)}k"
    else -> length.toString()
}
