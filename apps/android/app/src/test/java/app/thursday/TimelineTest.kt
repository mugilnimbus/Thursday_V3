package app.thursday

import app.thursday.domain.Event
import app.thursday.domain.Tone
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

    private fun call(key: String, status: String, tool: String = "fs.read", extra: Map<String, Any?> = emptyMap()) =
        ev("tool_call", mapOf("call_key" to key, "tool" to tool, "arguments" to mapOf("path" to "$key.txt"), "status" to status) + extra)

    @Test
    fun aToolCallShowsWhenRequestedAndSettlesGreenOrRedWhenItEnds() {
        val working = ev("task_state", mapOf("state" to "working"))
        fun lines(vararg events: Event) = buildTasks(listOf(working) + events).getValue("t1").lines
        val request = call("k1", "requested")
        assertEquals(listOf("fs.read k1.txt" to Tone.RUN), lines(request).map { it.text to it.tone })
        assertEquals(listOf("fs.read k1.txt → hello" to Tone.OK), lines(request, call("k1", "ok", extra = mapOf("result" to "hello"))).map { it.text to it.tone })
        assertEquals(listOf("fs.read k1.txt → no such file" to Tone.BAD), lines(request, call("k1", "error", extra = mapOf("result" to "no such file"))).map { it.text to it.tone })
        assertEquals(Tone.WARN, lines(request, call("k1", "unknown")).single().tone)
    }

    @Test
    fun oneLinePerCallInTheOrderTheyWereRequested() {
        val task = buildTasks(
            listOf(
                ev("task_state", mapOf("state" to "working")),
                call("a", "requested"), call("b", "requested"),
                call("a", "running"), call("b", "ok", extra = mapOf("result" to "B")), call("a", "ok", extra = mapOf("result" to "A")),
            ),
        ).getValue("t1")
        assertEquals(listOf("fs.read a.txt → A", "fs.read b.txt → B"), task.lines.map { it.text })
    }

    @Test
    fun aResultWithoutItsRequestStillShows() {
        val task = buildTasks(listOf(call("z", "ok", extra = mapOf("result" to "Z")))).getValue("t1")
        assertEquals(listOf("fs.read z.txt → Z" to Tone.OK), task.lines.map { it.text to it.tone })
    }

    @Test
    fun aCallIsNotLeftPulsingOnceTheTaskHasEnded() {
        val task = buildTasks(listOf(call("k", "requested", "shell"), ev("task_state", mapOf("state" to "canceled")))).getValue("t1")
        assertEquals("shell k.txt → did not finish" to Tone.WARN, task.lines.first().let { it.text to it.tone })
    }

    @Test
    fun aTaskSentStraightToTheMainAgentIsPlacedWhereTheVoiceAgentAnnouncedIt() {
        // The main agent announces the task first; the voice agent publishes the user's message and its own delegation after.
        val main = ev("delegation", mapOf("instruction" to "hii"))
        val voice = ev("delegation", mapOf("instruction" to "hii", "by" to "direct"), source = "voice")
        val direct = buildTasks(listOf(main, voice)).getValue("t1")
        assertEquals(voice.pos, direct.directPos)
        assertEquals("the main agent's event is still where the task began", main.pos, direct.firstPos)
        val normal = buildTasks(listOf(main, ev("delegation", mapOf("instruction" to "hii"), source = "voice"))).getValue("t1")
        assertNull(normal.directPos)
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
        assertEquals(true, (stats.contextTokens ?: 0) > 0)
        assertNull(agentStats(flow, "voice").contextTokens)
    }

    @Test
    fun contextIsWordedAsTokensInUseAndTheWindow() {
        assertEquals("4412/16384", app.thursday.domain.contextText(4412, 16384))
        assertEquals("loaded, not asked anything in this chat yet", "–/16384", app.thursday.domain.contextText(null, 16384))
        assertEquals("an endpoint that does not report its window", "900 tokens", app.thursday.domain.contextText(900, null))
        assertEquals("", app.thursday.domain.contextText(null, null))
    }
}
