package app.thursday.data

import app.thursday.domain.AgentForm
import app.thursday.domain.Event
import org.json.JSONArray
import org.json.JSONObject

/* Gateway shapes (docs/CONTRACTS.md), parsed with the platform's org.json. */

data class Project(val id: String, val name: String, val folder: String, val createdAt: String)
/** `direct`: every message in the chat goes straight to the main agent (kept on the PC, so every device agrees). */
data class Chat(val id: String, val title: String, val lastActivity: String, val direct: Boolean = false)
data class ChatMessage(
    val id: Long, val pos: Long?, val role: String, val text: String, val createdAt: String, val clientMessageId: String?,
    val direct: Boolean = false,
)
data class Pending(val clientMessageId: String, val text: String, val status: String, val error: String, val direct: Boolean = false)
data class Approval(
    val id: String, val taskId: String, val chatId: String, val tool: String, val summary: String,
    val arguments: Map<String, Any?>, val expiresAt: String,
)
/** A task and its events in order. A very long task has [omitted] events left out of the middle. */
data class TaskTrace(val task: TaskRow, val events: List<app.thursday.domain.Event>, val omitted: Int)

data class TaskRow(
    val id: String, val chatId: String?, val state: String, val pauseState: String, val instruction: String,
    val summary: String, val createdAt: String, val updatedAt: String, val chatTitle: String?,
    val projectId: String? = null, val projectName: String? = null,
)
data class Banner(val code: String, val text: String)
data class Status(val mainAgent: Boolean, val voiceAgent: Boolean, val queued: Int, val banners: List<Banner>, val streamPos: Long)
data class Device(val id: String, val name: String, val createdAt: String, val lastSeen: String?)
/** An agent's model settings. `form` is the editable part; a key is only ever reported as set or not. */
data class LlmSettings(
    val form: AgentForm, val apiKeySet: Boolean, val sendsOffPc: Boolean, val supportsLifecycle: Boolean,
    val loadedContext: Int?, val loaded: Boolean, val reachable: Boolean?, val installed: Boolean, val hearsAudio: Boolean,
    /** The (model, address) each other provider used last, brought back when the agent switches to it. */
    val remembered: Map<String, Pair<String?, String?>> = emptyMap(),
    /** The PC's graphics cards as (number, name), once llama.cpp has been asked; and how the loaded model was placed. */
    val cards: List<Pair<Int, String>> = emptyList(),
    val placement: String = "",
) {
    val provider get() = form.provider
    val model get() = form.model
}
data class ModelEntry(val key: String, val loaded: Boolean, val maxContext: Int?, val sizeBytes: Long?, val projector: String?)
data class ModelListing(val models: List<ModelEntry>, val error: String?)
data class Gpu(val index: Int, val name: String, val usedMb: Double, val totalMb: Double)
data class ServiceSample(val name: String, val up: Boolean, val latencyMs: Double?, val metrics: Map<String, Any?>)
/** The databases and logs one part of Thursday keeps on the PC, in bytes. */
data class StorageSample(val name: String, val bytes: Long)
data class MetricsSample(
    val ts: String, val cpu: Double, val ramUsedMb: Double, val ramTotalMb: Double, val rx: Double, val tx: Double,
    val gpus: List<Gpu>, val services: List<ServiceSample>, val storage: List<StorageSample> = emptyList(),
) {
    fun num(service: String, key: String): Double? = (services.firstOrNull { it.name == service }?.metrics?.get(key) as? Number)?.toDouble()
}
data class FolderRef(val name: String, val path: String)
/** `modelFolders`: where another program on the PC keeps its models (LM Studio), offered as shortcuts. */
data class FolderListing(
    val path: String, val parent: String?, val folders: List<FolderRef>, val home: String,
    val modelFolders: List<FolderRef> = emptyList(),
)
data class FileEntry(val name: String, val path: String, val isDir: Boolean, val size: Long?)
data class FilePreview(val path: String, val size: Long, val text: String?, val truncated: Boolean, val binary: Boolean)
data class LlmCall(val ts: String, val agent: String, val tokensPerSecond: Double?, val ttftSeconds: Double?, val inputTokens: Int?, val contextLength: Int?)
data class MonitorData(val latest: MetricsSample?, val history: List<MetricsSample>, val calls: List<LlmCall>)
data class Rule(val chatId: String, val chatTitle: String, val tool: String, val createdAt: String)
data class ToolServer(val projectId: String, val projectName: String, val alive: Boolean, val openSessions: Int)
data class CatalogTool(val name: String, val description: String, val asksFirst: Boolean)
data class ToolsOverview(val reachable: Boolean, val rules: List<Rule>, val servers: List<ToolServer>, val catalog: List<CatalogTool>)

/** A live-stream message. Stored events carry a position; replies and send states do not. */
sealed interface StreamMessage {
    data class Stored(val kind: String, val event: Event) : StreamMessage
    data class Delta(val chatId: String, val clientMessageId: String, val text: String) : StreamMessage
    data class Outgoing(
        val chatId: String, val clientMessageId: String, val status: String, val text: String?, val error: String?,
        val direct: Boolean = false,
    ) : StreamMessage
    data class Banners(val banners: List<Banner>) : StreamMessage
    data object CatalogChanged : StreamMessage
}

fun JSONObject.str(key: String): String? = if (isNull(key)) null else optString(key)

fun JSONObject.toMap(): Map<String, Any?> = keys().asSequence().associateWith { unwrap(opt(it)) }

fun JSONArray.toList(): List<Any?> = (0 until length()).map { unwrap(opt(it)) }

private fun unwrap(value: Any?): Any? = when (value) {
    JSONObject.NULL, null -> null
    is JSONObject -> value.toMap()
    is JSONArray -> value.toList()
    else -> value
}

/** JSON text to and from plain maps and lists, for showing stored request and response bodies. */
object Json {
    /** Maps, lists and values for JSON text; null when the text is not JSON. */
    fun parse(text: String): Any? = try {
        when (val value = org.json.JSONTokener(text).nextValue()) {
            is JSONObject -> value.toMap()
            is JSONArray -> value.toList()
            else -> null
        }
    } catch (_: org.json.JSONException) {
        null
    }

    /** A value indented for reading. Text that holds JSON is indented too; other text is returned as it is. */
    fun pretty(value: Any?): String = when (value) {
        null -> ""
        is Map<*, *> -> JSONObject(value).toString(2)
        is List<*> -> JSONArray(value).toString(2)
        is String -> when (val parsed = parse(value)) {
            null -> value
            else -> pretty(parsed)
        }
        else -> value.toString()
    }
}

inline fun <T> JSONArray?.mapObjects(block: (JSONObject) -> T): List<T> =
    if (this == null) emptyList() else (0 until length()).map { block(getJSONObject(it)) }

object Parse {
    fun project(o: JSONObject) = Project(o.getString("project_id"), o.getString("name"), o.optString("folder"), o.optString("created_at"))
    fun chat(o: JSONObject) = Chat(o.getString("chat_id"), o.optString("title"), o.optString("last_activity"), o.optBoolean("direct"))
    fun message(o: JSONObject) = ChatMessage(
        o.getLong("id"), if (o.isNull("pos")) null else o.optLong("pos"), o.getString("role"), o.optString("text"),
        o.optString("created_at"), o.str("client_message_id"), o.optBoolean("direct"),
    )
    fun pending(o: JSONObject) =
        Pending(o.getString("client_message_id"), o.optString("text"), o.optString("status"), o.optString("error"), o.optBoolean("direct"))
    fun approval(o: JSONObject) = Approval(
        o.getString("approval_id"), o.optString("task_id"), o.optString("chat_id"), o.optString("tool"), o.optString("summary"),
        o.optJSONObject("arguments")?.toMap() ?: emptyMap(), o.optString("expires_at"),
    )
    fun task(o: JSONObject) = TaskRow(
        o.getString("task_id"), o.str("chat_id"), o.optString("state"), o.optString("pause_state", "none"), o.optString("instruction"),
        o.optString("summary"), o.optString("created_at"), o.optString("updated_at"), o.str("chat_title"),
        o.str("project_id"), o.str("project_name"),
    )
    fun banner(o: JSONObject) = Banner(o.optString("code"), o.optString("text"))
    fun status(o: JSONObject) = Status(
        o.optBoolean("main_agent"), o.optBoolean("voice_agent"), o.optInt("queued_messages"),
        o.optJSONArray("banners").mapObjects(::banner), o.optLong("stream_pos"),
    )
    fun device(o: JSONObject) = Device(o.getString("device_id"), o.optString("name"), o.optString("created_at"), o.str("last_seen"))
    fun llm(o: JSONObject): LlmSettings {
        val loaded = o.optJSONObject("loaded")
        val load = o.optJSONObject("load")
        val inference = o.optJSONObject("inference")
        val local = o.optJSONObject("llamacpp")
        val form = AgentForm(
            provider = o.optString("provider"), baseUrl = o.optString("base_url"), model = o.optString("model"),
            contextLength = number(load, "context_length"), batchSize = number(load, "eval_batch_size"),
            moeCpuLayers = number(load, "moe_cpu_layers"), gpuLayers = load?.str("gpu_layers").orEmpty(),
            gpuSplit = load?.str("gpu_split").orEmpty(), gpuPriority = load?.str("gpu_priority").orEmpty(), flashAttention = toggle(load, "flash_attention"),
            kvOnGpu = toggle(load, "offload_kv_cache_to_gpu"), temperature = number(inference, "temperature"),
            topP = number(inference, "top_p"), maxOutputTokens = number(inference, "max_output_tokens"),
            reasoning = inference?.str("reasoning") ?: "default", modelsDir = local?.optString("models_dir").orEmpty(),
            gpu = number(local, "gpu"), compactAtTokens = number(o, "compact_at_tokens"),
            idleUnloadMinutes = number(o, "idle_unload_minutes").ifEmpty { "5" },
        )
        return LlmSettings(
            form, o.optBoolean("api_key_set"), o.optBoolean("sends_data_off_pc"), o.optBoolean("supports_lifecycle"),
            loaded?.let { if (it.isNull("context_length")) null else it.optInt("context_length") }, loaded != null,
            if (o.has("reachable") && !o.isNull("reachable")) o.optBoolean("reachable") else null,
            local?.optBoolean("installed") ?: false, o.optBoolean("hears_audio"),
            o.optJSONObject("remembered")?.let { kept ->
                kept.keys().asSequence().associateWith { name -> kept.optJSONObject(name).let { it?.str("model") to it?.str("base_url") } }
            } ?: emptyMap(),
            local?.optJSONArray("devices").mapObjects { it.optInt("index") to it.optString("name") },
            local?.optString("placement").orEmpty(),
        )
    }
    /** A number as the form shows it: "" when unset, and 1.0 written as 1 so it matches the listed choices. */
    private fun number(o: JSONObject?, key: String): String =
        if (o == null || o.isNull(key)) "" else o.get(key).toString().removeSuffix(".0")
    private fun toggle(o: JSONObject?, key: String): String =
        if (o == null || o.isNull(key)) "default" else if (o.optBoolean(key)) "on" else "off"
    fun models(o: JSONObject) = ModelListing(
        o.optJSONArray("models").mapObjects {
            ModelEntry(
                it.optString("key"), it.optBoolean("loaded"), if (it.isNull("max_context_length")) null else it.optInt("max_context_length"),
                if (it.isNull("size_bytes")) null else it.optLong("size_bytes"), it.str("projector"),
            )
        }.distinctBy { it.key },
        o.str("error"),
    )
    fun sample(o: JSONObject) = MetricsSample(
        o.optString("ts"), o.optDouble("cpu_percent"), o.optDouble("ram_used_mb"), o.optDouble("ram_total_mb"),
        o.optDouble("net_rx_bytes_per_s"), o.optDouble("net_tx_bytes_per_s"),
        o.optJSONArray("gpus").mapObjects { Gpu(it.optInt("index"), it.optString("name"), it.optDouble("vram_used_mb"), it.optDouble("vram_total_mb")) },
        o.optJSONArray("services").mapObjects {
            ServiceSample(it.optString("name"), it.optBoolean("up"), if (it.isNull("latency_ms")) null else it.optDouble("latency_ms"), it.optJSONObject("metrics")?.toMap() ?: emptyMap())
        },
        o.optJSONArray("storage").mapObjects { StorageSample(it.optString("name"), it.optLong("bytes")) },
    )
    fun tools(o: JSONObject) = ToolsOverview(
        o.optBoolean("main_agent_reachable"),
        o.optJSONArray("rules").mapObjects { Rule(it.optString("chat_id"), it.optString("chat_title"), it.optString("tool"), it.optString("created_at")) },
        o.optJSONArray("servers").mapObjects { ToolServer(it.optString("project_id"), it.optString("project_name"), it.optBoolean("alive"), it.optInt("open_sessions")) },
        o.optJSONArray("catalog").mapObjects { CatalogTool(it.optString("name"), it.optString("description"), it.optBoolean("asks_first")) },
    )
    fun event(pos: Long, o: JSONObject) = Event(
        pos, o.optString("source"), o.optString("ts"), o.str("chat_id"), o.str("task_id"), o.optString("type"),
        o.optJSONObject("payload")?.toMap() ?: emptyMap(),
    )

    fun stream(o: JSONObject): StreamMessage? = when (val kind = o.optString("kind")) {
        "chat_delta" -> StreamMessage.Delta(o.optString("chat_id"), o.optString("client_message_id"), o.optString("text"))
        "outgoing" -> StreamMessage.Outgoing(
            o.optString("chat_id"), o.optString("client_message_id"), o.optString("status"), o.str("text"), o.str("error"), o.optBoolean("direct"),
        )
        "status_banner" -> StreamMessage.Banners(o.optJSONArray("banners").mapObjects(::banner))
        "catalog_changed" -> StreamMessage.CatalogChanged
        "timeline_event", "task_state", "approval_requested", "approval_resolved", "notification" ->
            o.optJSONObject("event")?.let { StreamMessage.Stored(kind, event(o.optLong("pos"), it)) }
        else -> null
    }
}
