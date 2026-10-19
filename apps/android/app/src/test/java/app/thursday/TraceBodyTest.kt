package app.thursday

import app.thursday.domain.BodyPart
import app.thursday.domain.TraceBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TraceBodyTest {
    /** Stands in for the JSON helpers: arguments are shown as they are, and stream lines are looked up by their text. */
    private val pretty: (Any?) -> String = { it?.toString() ?: "" }
    private fun stream(vararg events: Map<String, Any?>): Pair<String, (String) -> Any?> {
        val lines = events.mapIndexed { i, e -> "e$i" to e }.toMap()
        return lines.keys.joinToString("") { "event: x\ndata: $it\n\n" } to { text: String -> lines[text] }
    }

    @Test
    fun `a request is the conversation in order, then the settings and tool names`() {
        val parts = TraceBody.requestParts(
            mapOf(
                "model" to "google/gemma", "stream" to true,
                "input" to listOf(
                    mapOf("role" to "system", "content" to "You are the main agent."),
                    mapOf("role" to "user", "content" to "Clean up the logs"),
                    mapOf("type" to "reasoning", "content" to listOf(mapOf("type" to "reasoning_text", "text" to "List first."))),
                    mapOf("type" to "function_call", "name" to "fs_list", "arguments" to "{\"path\":\".\"}"),
                    mapOf("type" to "function_call_output", "output" to "a.log\nb.log"),
                    mapOf("type" to "message", "role" to "assistant", "content" to listOf(mapOf("type" to "output_text", "text" to "Two logs found."))),
                ),
                "tools" to listOf(mapOf("type" to "function", "name" to "fs_list"), mapOf("type" to "function", "name" to "fs_delete")),
            ),
            pretty,
        )!!
        assertEquals(listOf("System", "User", "Thinking", "Tool call · fs_list", "Tool result", "Assistant", "Settings"), parts.map { it.label })
        assertEquals(BodyPart("Tool result", "a.log\nb.log", true), parts[4])
        assertEquals("model: google/gemma\nstream: true\ntools: fs_list, fs_delete", parts.last().text)
        assertNull(TraceBody.requestParts(mapOf("anything" to 1), pretty))
        assertNull(TraceBody.requestParts("text", pretty))
    }

    @Test
    fun `a stored response is thinking, answer, tool calls and tokens`() {
        val parts = TraceBody.responseParts(
            mapOf(
                "status" to "completed",
                "output" to listOf(
                    mapOf("type" to "reasoning", "content" to listOf(mapOf("text" to "Read the file."))),
                    mapOf("type" to "message", "role" to "assistant", "content" to listOf(mapOf("type" to "output_text", "text" to "Reading it now."))),
                    mapOf("type" to "function_call", "name" to "fs_read", "arguments" to "{\"path\":\"main.py\"}"),
                ),
                "usage" to mapOf("input_tokens" to 3000, "output_tokens" to 240),
            ),
            { null }, pretty,
        )
        assertEquals(
            listOf(
                BodyPart("Thinking", "Read the file."),
                BodyPart("Assistant", "Reading it now."),
                BodyPart("Tool call · fs_read", "{\"path\":\"main.py\"}", true),
                BodyPart("Tokens", "3000 in / 240 out"),
            ),
            parts,
        )
    }

    @Test
    fun `a chat completion and a response that ended early are both read`() {
        val chat = TraceBody.responseParts(
            mapOf(
                "choices" to listOf(mapOf("message" to mapOf(
                    "role" to "assistant", "reasoning_content" to "hm", "content" to "Hello",
                    "tool_calls" to listOf(mapOf("function" to mapOf("name" to "fs_read", "arguments" to "{}"))),
                ))),
                "usage" to mapOf("prompt_tokens" to 5, "completion_tokens" to 3),
            ),
            { null }, pretty,
        )!!
        assertEquals(listOf("Thinking", "Assistant", "Tool call · fs_read", "Tokens"), chat.map { it.label })
        assertEquals("5 in / 3 out", chat.last().text)
        val cut = TraceBody.responseParts(mapOf("status" to "incomplete", "output" to listOf(mapOf("type" to "reasoning", "content" to listOf(mapOf("text" to "So")))), "usage" to null), { null }, pretty)!!
        assertEquals(listOf("Thinking", "Cut short"), cut.map { it.label })
    }

    @Test
    fun `an old raw token stream is put back together, and its final event wins when it survived`() {
        val response = mapOf("status" to "completed", "output" to listOf(mapOf("type" to "message", "role" to "assistant", "content" to listOf(mapOf("text" to "Hi there")))))
        val (whole, parseWhole) = stream(
            mapOf("type" to "response.output_text.delta", "output_index" to 0, "delta" to "Hi "),
            mapOf("type" to "response.completed", "response" to response),
        )
        assertEquals(listOf(BodyPart("Assistant", "Hi there")), TraceBody.responseParts(whole, parseWhole, pretty))

        val (cut, parseCut) = stream(
            mapOf("type" to "response.created", "response" to mapOf("output" to emptyList<Any>())),
            mapOf("type" to "response.output_item.added", "output_index" to 0, "item" to mapOf("type" to "reasoning")),
            mapOf("type" to "response.reasoning_text.delta", "output_index" to 0, "delta" to "The user wants "),
            mapOf("type" to "response.reasoning_text.delta", "output_index" to 0, "delta" to "a change."),
            mapOf("type" to "response.output_item.added", "output_index" to 1, "item" to mapOf("type" to "function_call", "name" to "fs_read")),
            mapOf("type" to "response.function_call_arguments.delta", "output_index" to 1, "delta" to "{\"path\":\"a.py\"}"),
        )
        assertEquals(
            listOf(
                BodyPart("Thinking", "The user wants a change."),
                BodyPart("Tool call · fs_read", "{\"path\":\"a.py\"}", true),
                BodyPart("Cut short", TraceBody.CUT_STREAM),
            ),
            TraceBody.responseParts(cut + "data: {...[truncated 69043 characters]", parseCut, pretty),
        )
    }

    @Test
    fun `chat completion chunks are joined, and other bodies are left to the raw view`() {
        fun chunk(delta: Map<String, Any?>) = mapOf("choices" to listOf(mapOf("delta" to delta)))
        val (chunks, parse) = stream(
            chunk(mapOf("reasoning_content" to "hm ")),
            chunk(mapOf("content" to "Hel")),
            chunk(mapOf("content" to "lo")),
            chunk(mapOf("tool_calls" to listOf(mapOf("index" to 0, "function" to mapOf("name" to "fs_read", "arguments" to "{\"pa"))))),
            chunk(mapOf("tool_calls" to listOf(mapOf("index" to 0, "function" to mapOf("arguments" to "th\":\"a\"}"))))),
        )
        assertEquals(
            listOf(BodyPart("Thinking", "hm "), BodyPart("Assistant", "Hello"), BodyPart("Tool call · fs_read", "{\"path\":\"a\"}", true)),
            TraceBody.responseParts(chunks + "data: [DONE]\n\n", parse, pretty)!!.take(3),
        )
        assertNull(TraceBody.responseParts("Bad gateway", { null }, pretty))
        assertEquals(listOf(BodyPart("Error", "model not loaded")), TraceBody.responseParts("{}", { mapOf("error" to mapOf("message" to "model not loaded")) }, pretty))
    }
}
