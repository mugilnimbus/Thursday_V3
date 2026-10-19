package app.thursday.domain

/**
 * The editable part of an agent's model settings, the values each provider accepts, and the minimal change to send.
 * An empty string (or "default") means "leave the engine's default"; it is sent as null. Mirrors the dashboard.
 */
data class AgentForm(
    val provider: String = "lmstudio",
    val baseUrl: String = "",
    val model: String = "",
    val contextLength: String = "",
    val batchSize: String = "",
    val moeCpuLayers: String = "",
    val gpuLayers: String = "",
    val gpuSplit: String = "",
    val gpuPriority: String = "",
    val flashAttention: String = "default",
    val kvOnGpu: String = "default",
    val temperature: String = "",
    val topP: String = "",
    val maxOutputTokens: String = "",
    val reasoning: String = "default",
    val modelsDir: String = "",
    val gpu: String = "",
    val compactAtTokens: String = "",
    val idleUnloadMinutes: String = "5",
)

data class ProviderKind(val label: String, val lifecycle: Boolean, val endpoint: Boolean, val folders: Boolean)

object AgentChoices {
    const val TOKEN_STEP = 1024

    val providers = linkedMapOf(
        "lmstudio" to ProviderKind("LM Studio", lifecycle = true, endpoint = true, folders = false),
        "llamacpp" to ProviderKind("Built-in", lifecycle = true, endpoint = false, folders = true),
        "openai_compatible" to ProviderKind("OpenAI-style", lifecycle = false, endpoint = true, folders = false),
    )

    fun kind(provider: String): ProviderKind = providers[provider] ?: providers.getValue("openai_compatible")

    private val contextSizes = listOf(2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576)
    private val batchSizes = listOf(64, 128, 256, 512, 1024, 2048, 4096)
    private val moeLayers = listOf(1, 2, 4, 8, 12, 16, 24, 32, 48, 64)
    private val gpuLayers = listOf(8, 16, 24, 32, 48, 64)
    private val gpuSplits = listOf("1,1" to "Even (1 : 1)", "2,1" to "2 : 1", "1,2" to "1 : 2", "3,1" to "3 : 1", "1,3" to "1 : 3")
    private val idleMinutes = listOf(1, 2, 5, 10, 15, 30, 60)
    private val temperatures = (0..20).map { if (it % 10 == 0) "${it / 10}" else "${it / 10}.${it % 10}" }
    private val topPs = listOf("0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "0.95", "1")
    private val tokenLimits = listOf(256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
    private val efforts = listOf("none", "minimal", "low", "medium", "high", "xhigh")
    private const val STUDIO = "LM Studio's"
    private const val OWN = "Model's own"
    private const val LMSTUDIO_DEFAULT_ADDRESS = "http://localhost:1234"

    /** What the engine does when nothing is chosen. LM Studio keeps its own per-model settings, which it does not report. */
    private val defaults = mapOf(
        "llamacpp" to mapOf(
            "context_length" to "8,192 tokens", "eval_batch_size" to "2048", "moe_cpu_layers" to "None", "gpu_layers" to "As many as fit", "gpu_split" to "By free memory", "gpu_priority" to "Spread over cards", "flash_attention" to "Automatic",
            "offload_kv_cache_to_gpu" to "On the GPU", "gpu" to "All cards", "temperature" to "0.8", "top_p" to "0.95",
            "max_output_tokens" to "No limit", "reasoning" to OWN,
        ),
        "lmstudio" to mapOf(
            "context_length" to STUDIO, "eval_batch_size" to STUDIO, "flash_attention" to STUDIO, "offload_kv_cache_to_gpu" to STUDIO,
            "temperature" to STUDIO, "top_p" to STUDIO, "max_output_tokens" to "No limit", "reasoning" to OWN,
        ),
        "openai_compatible" to mapOf("temperature" to "1", "top_p" to "1", "max_output_tokens" to "Model's maximum", "reasoning" to OWN),
    )

    private fun tokens(v: Int) = "%,d tokens".format(java.util.Locale.US, v)

    /**
     * The values a setting can take for this provider, default first, as (value, label). `current` stays in the list
     * even when it is not a usual value. `maxContext` is the chosen model's limit, when known.
     */
    fun choices(
        field: String, provider: String, current: String, maxContext: Int? = null, cards: List<Pair<Int, String>> = emptyList(),
    ): List<Pair<String, String>> {
        val known = cards.ifEmpty { (0..3).map { it to "" } }
        if (field == "idle_unload_minutes") {
            // No "default" entry: the box always shows the time in force. 0 keeps the model loaded.
            val times = listOf("0" to "Never") + idleMinutes.map { "$it" to if (it == 1) "1 minute" else "$it minutes" }
            return if (times.any { it.first == current }) times else times + (current to "$current minutes (saved)")
        }
        val empty = if (field in setOf("flash_attention", "offload_kv_cache_to_gpu", "reasoning")) "default" else ""
        // The value comes first, so a narrow box cuts off "(default)" and never the value itself.
        val first = empty to "${defaults[provider]?.get(field) ?: "Not set"} (default)"
        val rest: List<Pair<String, String>> = when (field) {
            "context_length" -> contextSizes.filter { maxContext == null || it <= maxContext }.map { "$it" to tokens(it) }
            "eval_batch_size" -> batchSizes.map { "$it" to "$it" }
            "moe_cpu_layers" -> moeLayers.map { "$it" to if (it == 1) "1 layer" else "$it layers" }
            "flash_attention" -> listOf("on" to "On", "off" to "Off")
            "offload_kv_cache_to_gpu" -> listOf("on" to "On the GPU", "off" to "In system memory")
            "gpu" -> known.map { "${it.first}" to "Only ${cardLabel(it)}" }
            "gpu_priority" -> known.map { "${it.first}" to "Fill ${cardLabel(it)} first" }
            "gpu_layers" -> listOf("all" to "All layers") + gpuLayers.map { "$it" to "$it layers" } + ("0" to "None (CPU only)")
            "gpu_split" -> gpuSplits
            "temperature" -> temperatures.map { it to it }
            "top_p" -> topPs.map { it to it }
            "max_output_tokens" -> tokenLimits.map { "$it" to tokens(it) }
            "reasoning" -> if (provider == "llamacpp") listOf("off" to "Off (faster)", "on" to "On") else efforts.map { it to it }
            else -> emptyList()
        }
        val all = listOf(first) + rest
        return if (current != empty && all.none { it.first == current }) all + (current to "$current (saved)") else all
    }

    /** A card's number with its name, shortened: "card 0 (RTX 3080 Ti)". */
    private fun cardLabel(card: Pair<Int, String>): String {
        val name = card.second.replace(Regex("^(NVIDIA|AMD|Intel)(\\(R\\))?\\s+(GeForce\\s+|Radeon\\s+)?", RegexOption.IGNORE_CASE), "")
        return "card ${card.first}" + if (name.isEmpty()) "" else " ($name)"
    }

    private fun whole(s: String): Any? = s.trim().toIntOrNull()
    private fun real(s: String): Any? = s.trim().toDoubleOrNull()
    private fun toggle(s: String): Any? = if (s == "default") null else s == "on"

    /** Only what differs; a cleared value is present with null. Nested under "load" and "inference" like the API. */
    fun changes(before: AgentForm, after: AgentForm): Map<String, Any?> {
        val out = linkedMapOf<String, Any?>()
        if (after.provider != before.provider) out["provider"] = after.provider
        // An emptied address is not sent, as an emptied model is not: the built-in llama.cpp has no address, and the
        // PC drops the old provider's one by itself when the provider changes. The PC refuses an empty address.
        if (after.baseUrl.trim() != before.baseUrl && after.baseUrl.isNotBlank()) out["base_url"] = after.baseUrl.trim()
        if (after.model.trim() != before.model && after.model.isNotBlank()) out["model"] = after.model.trim()
        val load = linkedMapOf<String, Any?>()
        if (after.contextLength != before.contextLength) load["context_length"] = whole(after.contextLength)
        if (after.batchSize != before.batchSize) load["eval_batch_size"] = whole(after.batchSize)
        if (after.moeCpuLayers != before.moeCpuLayers) load["moe_cpu_layers"] = whole(after.moeCpuLayers)
        if (after.flashAttention != before.flashAttention) load["flash_attention"] = toggle(after.flashAttention)
        if (after.kvOnGpu != before.kvOnGpu) load["offload_kv_cache_to_gpu"] = toggle(after.kvOnGpu)
        if (after.gpuLayers != before.gpuLayers) load["gpu_layers"] = after.gpuLayers.ifEmpty { null }
        if (after.gpuSplit != before.gpuSplit) load["gpu_split"] = after.gpuSplit.ifEmpty { null }
        if (after.gpuPriority != before.gpuPriority) load["gpu_priority"] = after.gpuPriority.ifEmpty { null }
        if (load.isNotEmpty()) out["load"] = load
        val inference = linkedMapOf<String, Any?>()
        if (after.temperature != before.temperature) inference["temperature"] = real(after.temperature)
        if (after.topP != before.topP) inference["top_p"] = real(after.topP)
        if (after.maxOutputTokens != before.maxOutputTokens) inference["max_output_tokens"] = whole(after.maxOutputTokens)
        if (after.reasoning != before.reasoning) inference["reasoning"] = after.reasoning.takeIf { it != "default" }
        if (inference.isNotEmpty()) out["inference"] = inference
        if (after.modelsDir.trim() != before.modelsDir) out["models_dir"] = after.modelsDir.trim().ifEmpty { null }
        if (after.gpu != before.gpu) out["gpu"] = whole(after.gpu)
        if (after.compactAtTokens.trim() != before.compactAtTokens) out["compact_at_tokens"] = whole(after.compactAtTokens)
        if (after.idleUnloadMinutes != before.idleUnloadMinutes) out["idle_unload_minutes"] = real(after.idleUnloadMinutes)
        return out
    }

    /** The part of the form that decides which models can be listed; the list belongs to what is saved. */
    fun listingChanged(saved: AgentForm, form: AgentForm): Boolean =
        form.provider != saved.provider || form.baseUrl.trim() != saved.baseUrl || form.modelsDir.trim() != saved.modelsDir

    /**
     * Why the form cannot be saved, or null. While the provider, address or folder differ from what is saved, the
     * model list on screen is not this provider's, so a model cannot be demanded yet.
     */
    fun validate(form: AgentForm, saved: AgentForm? = null): String? {
        val local = form.provider == "llamacpp"
        if (!local && !Regex("^https?://\\S+$").matches(form.baseUrl.trim())) return "The endpoint must start with http:// or https://."
        if (!local && form.model.isBlank() && !(saved != null && listingChanged(saved, form))) return "Choose or enter a model."
        val limit = form.compactAtTokens.trim()
        if (limit.isNotEmpty()) {
            val value = limit.toIntOrNull()
            if (value == null || value < TOKEN_STEP || value > 2_000_000 || value % TOKEN_STEP != 0) {
                return "The context limit must be a multiple of $TOKEN_STEP tokens."
            }
        }
        return null
    }

    /**
     * The form switched to another provider. A model name or address from one provider means nothing to another,
     * so the form shows what that provider used last (or what is saved, when switching back), or nothing.
     * `remembered` maps a provider to its (model, address).
     */
    fun switchProvider(form: AgentForm, saved: AgentForm, remembered: Map<String, Pair<String?, String?>>, next: String): AgentForm {
        if (next == form.provider) return form
        val kept = if (next == saved.provider) saved.model to saved.baseUrl else remembered[next] ?: (null to null)
        return form.copy(
            provider = next,
            model = kept.first.orEmpty(),
            baseUrl = kept.second ?: if (next == "lmstudio") LMSTUDIO_DEFAULT_ADDRESS else "",
        )
    }

    /** The model to select by itself once a list arrives: the only one there is, when nothing valid is chosen. */
    fun onlyChoice(form: AgentForm, models: List<String>): String? {
        if (models.size != 1 || models[0] == form.model) return null
        return if (kind(form.provider).folders || form.model.isBlank()) models[0] else null
    }

    /** The context limit one step up or down, staying a multiple of 1024; stepping below the first step clears it. */
    fun stepTokens(current: String, up: Boolean, start: Int = 8 * TOKEN_STEP): String {
        val now = current.trim().toIntOrNull() ?: return if (up) "$start" else ""
        val floor = now / TOKEN_STEP * TOKEN_STEP
        val next = if (up) floor + TOKEN_STEP else if (now == floor) floor - TOKEN_STEP else floor
        return if (next < TOKEN_STEP) "" else "${next.coerceAtMost(2_000_000 / TOKEN_STEP * TOKEN_STEP)}"
    }

    /** What the agent does when no context limit is chosen, in words. */
    fun contextDefault(agent: String, provider: String, loadedContext: Int?): String = when {
        agent == "voice" -> "the last 60 messages"
        loadedContext != null -> "${(loadedContext * 0.9).toInt() / TOKEN_STEP * TOKEN_STEP}"
        provider == "openai_compatible" -> "no limit"
        else -> "90% of the window"
    }

    fun sizeText(bytes: Long?): String = when {
        bytes == null || bytes <= 0 -> ""
        bytes >= 1_000_000_000 -> "%.1f GB".format(java.util.Locale.US, bytes / 1e9)
        else -> "${Math.round(bytes / 1e6)} MB"
    }
}
