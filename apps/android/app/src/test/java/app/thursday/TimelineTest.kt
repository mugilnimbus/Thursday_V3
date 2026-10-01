package app.thursday

import app.thursday.domain.Event
import app.thursday.domain.agentStats
import app.thursday.domain.buildTasks
import app.thursday.domain.liveLine
import app.thursday.domain.shortArgs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TimelineTest {
    private var pos = 0L
    private fun ev(type: String, payload: Map<String, Any?>, source: String = "main"): Event {
        pos += 1
        return Event(pos, source, "2026-10-01T12:00:%02d+00:00".format(pos), "c", "t1", type, payload)
    }

    private val flow = listOf(
        ev("delegation", mapOf("instruction" to "Delete old.log")),
        ev("task_state", mapOf("state" to "working", "pause_state" to "none")),
        ev("llm_call", mapOf("agent" to "main", "step" to 1, "status" to "ok", "usage" to mapOf("input_tokens" to 900), "context_length" to 32000, "tokens_per_second" to 61.7)),
        ev("tool_call", mapOf("call_key" to "t1:1:0", "tool" to "fs.list", "arguments" to mapOf("path" to "logs"), "status" to "requested")),
        ev("tool_call", mapOf("call_key" to "t1:1:0", "tool" to "fs.list", "arguments" to mapOf("path" to "logs"), "status" to "ok", "result" to "a.log\nold.log")),
        ev("approval_requested", mapOf("approval_id" to "ap1", "tool" to "fs.delete", "summary" to "Delete file: old.log")),
        ev("approval_resolved", mapOf("approval_id" to "ap1", "outcome" to "allowed", "by" to "gateway")),
        ev("tool_call", mapOf("call_key" to "t1:2:0", "tool" to "fs.delete", "arguments" to mapOf("path" to "old.log"), "status" to "ok", "result" to "deleted file old.log")),
        ev("task_state", mapOf("state" to "completed", "pause_state" to "none", "summary" to "Deleted old.log.")),
    )

    @Test
    fun taskCardReadsAsAStory() {
        val task = buildTasks(flow).getValue("t1")
        assertEquals("Delete old.log", task.instruction)
        assertEquals("completed", task.state)
        assertEquals("Deleted old.log.", task.summary)
        assertEquals(
            listOf(
                "Delegated “Delete old.log”",
                "fs.list logs → 2 entries",
                "Asked: Delete file: old.log",
                "Approval: you allowed it",
                "fs.delete old.log → deleted file old.log",
                "Done",
            ),
            task.lines.map { it.text },
        )
        assertEquals(4.0, task.lines[1].seconds, 0.001)
        assertNull(liveLine(task))
    }

    @Test
    fun liveLineWhileWaiting() {
        val waiting = buildTasks(flow.take(6) + ev("task_state", mapOf("state" to "input_required"))).getValue("t1")
        assertEquals("Waiting for your approval…", liveLine(waiting)?.text)
    }

    @Test
    fun argumentsStayShortAndHideContents() {
        assertEquals("a.txt", shortArgs(mapOf("path" to "a.txt", "content" to "x".repeat(500))))
        assertEquals(60, shortArgs(mapOf("command" to "y".repeat(100))).length)
    }

    @Test
    fun statsUseTheLatestSuccessfulCall() {
        val stats = agentStats(flow, "main")
        assertEquals(62, stats.tokensPerSecond)
        assertEquals(3, stats.contextPercent)
        assertNull(agentStats(flow, "voice").contextPercent)
    }
}
