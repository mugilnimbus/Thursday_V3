package app.thursday.domain

/**
 * A model call's request and response as labelled parts a person can read: who said what, the model's thinking, its
 * answer, its tool calls and the token counts. Newer traces store the response as an object; older ones hold the raw
 * token stream (cut at 20,000 characters), which is put together here from the pieces that survived.
 * Mirrors the dashboard's `traceBody.ts`.
 */
data class BodyPart(val label: String, val text: String, val code: Boolean = false)

object TraceBody {
    private val roles = mapOf("system" to "System", "developer" to "System", "user" to "User", "assistant" to "Assistant", "tool" to "Tool result")
    private val finalEvents = setOf("response.completed", "response.incomplete", "response.failed")
    const val CUT_STREAM = "Only the start of this response was kept; the rest of the stream was not stored."

    private fun obj(v: Any?): Map<*, *>? = v as? Map<*, *>
    private fun list(v: Any?): List<*> = v as? List<*> ?: emptyList<Any?>()

    /** Text of a message's content: a string, or a list of typed pieces of which the text ones are kept. */
    private fun contentText(content: Any?): String {
        if (content is String) return content
        return list(content).mapNotNull { piece ->
            val p = obj(piece) ?: return@mapNotNull null
            (p["text"] as? String) ?: when (p["type"]) {
                "input_audio" -> "[audio]"
                "input_image", "image_url" -> "[image]"
                else -> null
            }
        }.filter { it.isNotEmpty() }.joinToString("\n")
    }

    private fun itemParts(item: Any?, pretty: (Any?) -> String): List<BodyPart> {
        val it = obj(item) ?: return emptyList()
        when (it["type"]) {
            "function_call" -> return listOf(BodyPart("Tool call · ${it["name"] ?: ""}", pretty(it["arguments"]), true))
            "function_call_output" -> return listOf(BodyPart("Tool result", it["output"] as? String ?: pretty(it["output"]), true))
            "reasoning" -> {
                val text = contentText(it["content"]).ifEmpty { contentText(it["summary"]) }
                return if (text.isEmpty()) emptyList() else listOf(BodyPart("Thinking", text))
            }
        }
        val parts = mutableListOf<BodyPart>()
        val role = it["role"]?.toString() ?: "assistant"
        (it["reasoning_content"] as? String)?.takeIf { t -> t.isNotEmpty() }?.let { t -> parts += BodyPart("Thinking", t) }
        contentText(it["content"]).takeIf { t -> t.isNotEmpty() }?.let { t -> parts += BodyPart(roles[role] ?: role, t, role == "tool") }
        list(it["tool_calls"]).forEach { call ->
            val fn = obj(obj(call)?.get("function")) ?: emptyMap<Any?, Any?>()
            parts += BodyPart("Tool call · ${fn["name"] ?: ""}", pretty(fn["arguments"]), true)
        }
        return parts
    }

    /** What was sent: the conversation in order, then the model, settings and tool names. Null when it is not a chat request. */
    fun requestParts(body: Any?, pretty: (Any?) -> String): List<BodyPart>? {
        val b = obj(body) ?: return null
        val turns = (b["input"] as? List<*>) ?: (b["messages"] as? List<*>)
            ?: (b["input"] as? String)?.let { listOf(mapOf("role" to "user", "content" to it)) } ?: return null
        val parts = mutableListOf<BodyPart>()
        (b["instructions"] as? String)?.takeIf { it.isNotEmpty() }?.let { parts += BodyPart("System", it) }
        turns.forEach { parts += itemParts(it, pretty) }
        val settings = b.entries
            .filter { (k, v) -> k !in setOf("input", "messages", "instructions", "tools") && v != null && v !is Map<*, *> && v !is List<*> }
            .map { (k, v) -> "$k: $v" }.toMutableList()
        val tools = list(b["tools"]).mapNotNull { t -> obj(t)?.let { (it["name"] ?: obj(it["function"])?.get("name"))?.toString() } }.filter { it.isNotEmpty() }
        if (tools.isNotEmpty()) settings += "tools: ${tools.joinToString(", ")}"
        if (settings.isNotEmpty()) parts += BodyPart("Settings", settings.joinToString("\n"))
        return parts
    }

    private fun count(v: Any?): String = (v as? Number)?.toLong()?.toString() ?: "0"

    private fun usageText(usage: Any?): String {
        val u = obj(usage) ?: return ""
        val input = u["input_tokens"] ?: u["prompt_tokens"]
        val output = u["output_tokens"] ?: u["completion_tokens"]
        return if (input == null && output == null) "" else "${count(input)} in / ${count(output)} out"
    }

    private fun errorText(error: Any?): String = obj(error)?.get("message")?.toString() ?: error.toString()

    private fun objectParts(b: Map<*, *>, pretty: (Any?) -> String): List<BodyPart>? {
        val error = b["error"]
        val parts: MutableList<BodyPart> = when {
            b["output"] is List<*> -> list(b["output"]).flatMap { itemParts(it, pretty) }.toMutableList()
            b["choices"] is List<*> -> list(b["choices"]).flatMap { itemParts(obj(it)?.get("message"), pretty) }.toMutableList()
            error != null -> return listOf(BodyPart("Error", errorText(error)))
            else -> return null
        }
        if (error != null) parts += BodyPart("Error", errorText(error))
        if (b["status"] == "incomplete") parts += BodyPart("Cut short", "The response ended before it was complete; this is what arrived.")
        usageText(b["usage"]).takeIf { it.isNotEmpty() }?.let { parts += BodyPart("Tokens", it) }
        return parts
    }

    private class Piece(var label: String = "Assistant", var text: StringBuilder = StringBuilder(), var code: Boolean = false)

    private fun streamParts(stream: String, parse: (String) -> Any?, pretty: (Any?) -> String): List<BodyPart>? {
        val events = stream.lineSequence().filter { it.startsWith("data:") }.mapNotNull { obj(parse(it.drop(5).trim())) }.toList()
        if (events.isEmpty()) return null
        events.lastOrNull { it["type"] in finalEvents && it["response"] is Map<*, *> }?.let { return objectParts(it["response"] as Map<*, *>, pretty) }
        // No final event survived: join the pieces of each output item, in order.
        val items = sortedMapOf<Int, Piece>()
        fun at(index: Int) = items.getOrPut(index) { Piece() }
        for (event in events) {
            val type = event["type"]?.toString().orEmpty()
            list(event["choices"]).forEach { choice ->
                val delta = obj(obj(choice)?.get("delta")) ?: return@forEach
                (delta["reasoning_content"] as? String)?.let { at(-1).apply { label = "Thinking" }.text.append(it) }
                (delta["content"] as? String)?.let { at(0).text.append(it) }
                list(delta["tool_calls"]).forEach { piece ->
                    val p = obj(piece) ?: return@forEach
                    val fn = obj(p["function"]) ?: emptyMap<Any?, Any?>()
                    at(1 + ((p["index"] as? Number)?.toInt() ?: 0)).apply {
                        (fn["name"] as? String)?.takeIf { it.isNotEmpty() }?.let { label = "Tool call · $it" }
                        code = true
                        text.append(fn["arguments"] as? String ?: "")
                    }
                }
            }
            val index = (event["output_index"] as? Number)?.toInt() ?: continue
            val item = obj(event["item"])
            if (type == "response.output_item.added" && item != null) {
                if (item["type"] == "reasoning") at(index).label = "Thinking"
                if (item["type"] == "function_call") at(index).apply { label = "Tool call · ${item["name"] ?: ""}"; code = true }
            } else if (type.endsWith(".delta")) {
                (event["delta"] as? String)?.let { at(index).text.append(it) }
            }
        }
        val parts = items.values.filter { it.text.isNotEmpty() }.map { BodyPart(it.label, if (it.code) pretty(it.text.toString()) else it.text.toString(), it.code) }
        return parts + BodyPart("Cut short", CUT_STREAM)
    }

    /**
     * What came back. Null when the body is not a model response this screen understands (then the raw text is shown).
     * `parse` turns JSON text into maps and lists (null when it is not JSON); `pretty` indents a value or JSON text.
     */
    fun responseParts(body: Any?, parse: (String) -> Any?, pretty: (Any?) -> String): List<BodyPart>? = when (body) {
        is Map<*, *> -> objectParts(body, pretty)
        is String -> if ("data:" in body) streamParts(body, parse, pretty) else obj(parse(body))?.let { objectParts(it, pretty) }
        else -> null
    }
}
