package app.thursday.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import app.thursday.MainActivity
import app.thursday.data.GatewayApi
import app.thursday.domain.AgentChoices
import app.thursday.domain.AgentForm
import app.thursday.domain.formatContext
import app.thursday.graph
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Chip
import app.thursday.ui.common.Dot
import app.thursday.ui.common.Field
import app.thursday.ui.common.FolderBrowser
import app.thursday.ui.common.Look
import app.thursday.ui.common.Panel
import app.thursday.ui.common.Pick
import app.thursday.ui.common.Seg
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * One agent's model settings. The page only draws [AgentPageState] and passes on what is tapped; what can be saved,
 * loaded or chosen is decided there.
 */
@Composable
internal fun AgentPage(activity: MainActivity, agent: String, title: String, onBack: () -> Unit) {
    val api = activity.graph.api
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    val state = remember(agent) { AgentPageState(agent, title, GatewayAgentSettings(api)) { activity.guard.confirm(it) } }
    LaunchedEffect(state) { state.open() }

    val s = state.settings
    if (s == null) {
        SettingsPage(title, onBack) { Caption(state.error ?: "Loading…", color = if (state.error != null) p.danger else p.muted) }
        return
    }
    val form = state.form
    val saved = state.saved
    val kind = state.kind
    val listing = state.listing
    val chosen = state.chosen
    val busy = state.busy
    val problem = state.problem
    val edit: ((AgentForm) -> AgentForm) -> Unit = { change -> state.form = change(state.form) }
    val pick: @Composable (Modifier, String, String, String, (String) -> Unit) -> Unit = { modifier, field, label, value, set ->
        Pick(label, state.choices(field, value), value, set, modifier)
    }

    SettingsPage(
        title, onBack,
        save = { scope.launch { state.save() } },
        saveEnabled = state.canSave,
        saveLabel = if (busy == "save") "Saving…" else "Save",
    ) {
        if (state.dirty) Caption(problem ?: "Not saved yet. Going back discards these changes.", color = if (problem != null) p.danger else p.warning)

        // What is running now, and the buttons that load or free the hardware.
        Panel {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Txt(saved.model.substringAfterLast('/').ifEmpty { "No model chosen" }, weight = FontWeight.SemiBold, maxLines = 1)
                    Caption(AgentChoices.kind(saved.provider).label + if (s.sendsOffPc) " · leaves the PC" else " · on the PC")
                }
                when {
                    busy == "load" || busy == "reload" -> Chip("loading…", p.accentBright)
                    s.reachable == false -> Chip(if (s.provider == "llamacpp") "not set up" else "unreachable", p.danger)
                    !s.supportsLifecycle -> Chip("remote", p.muted)
                    s.loaded -> Chip("loaded · ${formatContext(s.loadedContext)}", p.success)
                    else -> Chip("off", p.muted)
                }
            }
            if (s.supportsLifecycle && form.provider == saved.provider) {
                Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                    if (s.loaded) Btn("Unload", { scope.launch { state.unload() } }, Modifier.weight(1f), enabled = busy.isEmpty())
                    else Btn("Load", { scope.launch { state.load() } }, Modifier.weight(1f), look = Look.PRIMARY, enabled = state.canLoad)
                    Btn("Reload", { scope.launch { state.reload() } }, Modifier.weight(1f), enabled = state.canReload)
                }
                if (!s.loaded) Caption("Nothing is in memory until the model is loaded or first used.")
            }
            if (s.hearsAudio) Caption("This model can hear speech.", color = p.success)
            state.error?.let { Caption(it, color = p.danger) }
        }

        Group("Provider") {
            Seg(AgentChoices.providers.map { it.key to it.value.label }, form.provider, state::switchProvider)
            when (form.provider) {
                "llamacpp" -> Caption("The PC starts llama.cpp itself when the model is loaded and stops it on unload. Nothing leaves the PC.")
                "openai_compatible" -> Caption("A cloud endpoint, or a llama.cpp server you run yourself.")
                else -> Caption("LM Studio running on the PC.")
            }
            if (kind.folders) {
                if (s.provider == "llamacpp" && !s.installed) {
                    Caption("llama.cpp is not installed on the PC yet. Run \"uv run thursday setup\" there.", color = p.danger)
                }
                Field(form.modelsDir, { edit { f -> f.copy(modelsDir = it) } }, label = "Models folder on the PC", placeholder = "The folder with your .gguf files", mono = true)
                if (state.browsing) {
                    FolderBrowser(form.modelsDir, { api.folders(it) }, state::chooseFolder, { state.browsing = false })
                } else {
                    Btn("Browse the PC", { state.browsing = true }, small = true)
                }
            } else {
                Field(form.baseUrl, { edit { f -> f.copy(baseUrl = it) } }, label = "Endpoint", mono = true)
                if (!LOCAL_ENDPOINT.containsMatchIn(form.baseUrl.trim())) {
                    Txt("Everything in this agent's context leaves the PC.", color = p.danger, size = Type.caption, weight = FontWeight.SemiBold)
                }
            }
        }

        Group("Model") {
            when {
                state.listingStale -> Caption("Save to see the models this provider offers.")
                state.typing || (listing.models.isEmpty() && !kind.folders) -> Field(form.model, { edit { f -> f.copy(model = it) } }, placeholder = "model name", mono = true)
                else -> {
                    val options = listing.models.map { m ->
                        m.key to listOfNotNull(m.key, AgentChoices.sizeText(m.sizeBytes).ifEmpty { null }, "loaded".takeIf { m.loaded }).joinToString(" · ")
                    }
                    val missing = form.model to (if (form.model.isEmpty() || kind.folders) "Choose a model…" else "${form.model} (not in the list)")
                    Pick("Model", if (chosen == null) listOf(missing) + options else options, form.model, { edit { f -> f.copy(model = it) } }, mono = true)
                }
            }
            if (!state.listingStale) {
                Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                    Btn("Refresh list", { scope.launch { state.listModels() } }, look = Look.PLAIN, small = true, enabled = busy.isEmpty())
                    if (!kind.folders) Btn(if (state.typing) "Pick from the list" else "Type a name", { state.typing = !state.typing }, look = Look.PLAIN, small = true)
                }
                listing.error?.let { Caption(it, color = p.danger) }
                if (listing.error == null && !state.loadable && !state.typing) {
                    Caption(
                        when {
                            listing.models.isNotEmpty() -> "Choose a model from the list, then save."
                            kind.folders -> "No .gguf model files were found in this folder or the folders inside it."
                            else -> "Choose or type a model, then save."
                        },
                        color = p.warning,
                    )
                }
                if (kind.folders && chosen != null) {
                    Caption(if (chosen.projector != null) "Projector found: this model can take images and, if it supports it, speech." else "No projector beside this file: text only.")
                }
            }
        }

        if (kind.endpoint) Group("API key") {
            if (form.provider != saved.provider) {
                Caption("Save the provider change first. Each provider keeps its own key.")
            } else {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                    Dot(if (s.apiKeySet) "ok" else "warn")
                    Txt(if (s.apiKeySet) "A key is stored" else "No key stored", Modifier.weight(1f))
                    if (s.apiKeySet) Btn("Remove", { scope.launch { state.removeKey() } }, look = Look.PLAIN, small = true, enabled = busy.isEmpty())
                }
                Field(state.newKey, { state.newKey = it }, placeholder = if (s.apiKeySet) "Type a new key to replace it" else "Paste the key", mono = true, secret = true)
                Caption("Stored with Save, in the PC's credential store. It is never shown again.")
            }
        }

        if (kind.lifecycle) Group("Load parameters") {
            Side(
                { m -> pick(m, "context_length", "Context length", form.contextLength) { edit { f -> f.copy(contextLength = it) } } },
                { m -> pick(m, "eval_batch_size", "Batch size", form.batchSize) { edit { f -> f.copy(batchSize = it) } } },
            )
            Side(
                { m -> pick(m, "flash_attention", "Flash attention", form.flashAttention) { edit { f -> f.copy(flashAttention = it) } } },
                { m -> pick(m, "offload_kv_cache_to_gpu", "KV cache", form.kvOnGpu) { edit { f -> f.copy(kvOnGpu = it) } } },
            )
            if (form.provider == "llamacpp") {
                Side(
                    { m -> pick(m, "moe_cpu_layers", "Expert layers on CPU", form.moeCpuLayers) { edit { f -> f.copy(moeCpuLayers = it) } } },
                    { m -> pick(m, "gpu_layers", "Layers on the cards", form.gpuLayers) { edit { f -> f.copy(gpuLayers = it) } } },
                )
                pick(Modifier, "gpu", "Graphics cards", form.gpu) { edit { f -> f.copy(gpu = it) } }
                if (form.gpu.isEmpty()) pick(Modifier, "gpu_priority", "A model larger than one card", form.gpuPriority) { edit { f -> f.copy(gpuPriority = it) } }
                if (form.gpu.isEmpty() && form.gpuPriority.isEmpty()) pick(Modifier, "gpu_split", "Split between the cards", form.gpuSplit) { edit { f -> f.copy(gpuSplit = it) } }
                Caption(
                    (if (form.gpu.isEmpty() && form.gpuPriority.isNotEmpty()) "The model goes on the chosen card. Only what does not fit there goes on the next card."
                    else "A model too large for one card is split across the cards by layer; what does not fit runs on the CPU, which is slower.") +
                        if (s.placement.isNotEmpty()) " Loaded now: ${s.placement}." else "",
                )
            }
            pick(Modifier, "idle_unload_minutes", "Unload when not used for", form.idleUnloadMinutes) { edit { f -> f.copy(idleUnloadMinutes = it) } }
            Caption("Used the next time the model is loaded. Reload applies them now.")
        }

        Group("Answers") {
            Side(
                { m -> pick(m, "temperature", "Temperature", form.temperature) { edit { f -> f.copy(temperature = it) } } },
                { m -> pick(m, "top_p", "Top p", form.topP) { edit { f -> f.copy(topP = it) } } },
            )
            Side(
                { m -> pick(m, "max_output_tokens", "Output limit", form.maxOutputTokens) { edit { f -> f.copy(maxOutputTokens = it) } } },
                { m -> pick(m, "reasoning", if (form.provider == "llamacpp") "Thinking" else "Reasoning", form.reasoning) { edit { f -> f.copy(reasoning = it) } } },
            )
            if (form.provider == "openai_compatible") Caption("Cloud reasoning models reject temperature and top p while reasoning is on, and accept only some effort levels.")
        }

        Group("Context") {
            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                Field(
                    form.compactAtTokens, { text -> edit { f -> f.copy(compactAtTokens = text.filter(Char::isDigit)) } }, Modifier.weight(1f),
                    label = if (agent == "main") "Summarise older turns at (tokens)" else "Send at most (tokens)",
                    placeholder = AgentChoices.contextDefault(agent, form.provider, s.loadedContext),
                )
                Btn("−", { edit { f -> f.copy(compactAtTokens = AgentChoices.stepTokens(f.compactAtTokens, up = false)) } })
                Btn("+", { edit { f -> f.copy(compactAtTokens = AgentChoices.stepTokens(f.compactAtTokens, up = true)) } })
            }
            Caption(
                when {
                    agent == "voice" -> "Empty: the last 60 messages. Older messages are left out, not summarised."
                    form.provider == "openai_compatible" -> "A cloud endpoint does not report its window, so older turns are only summarised once a limit is set."
                    else -> "Empty: at 90% of the loaded window. Steps of 1024 tokens."
                },
            )
        }
    }
}

private val LOCAL_ENDPOINT = Regex("^https?://(127\\.0\\.0\\.1|localhost|\\[::1])(:|/|$)")

/** The gateway as the agent page uses it. */
private class GatewayAgentSettings(private val api: GatewayApi) : AgentSettingsApi {
    override suspend fun settings(agent: String) = api.llm(agent)
    override suspend fun models(agent: String) = api.models(agent)
    override suspend fun change(agent: String, changes: Map<String, Any?>) {
        api.putLlm(agent, JSONObject(changes.mapValues { (_, v) -> jsonValue(v) }))
    }
    override suspend fun setKey(agent: String, key: String) = api.setKey(agent, key)
    override suspend fun model(agent: String, action: String) = api.model(agent, action)
}

/** A change map as JSON: a cleared value is an explicit null, nested maps become objects. */
private fun jsonValue(value: Any?): Any = when (value) {
    null -> JSONObject.NULL
    is Map<*, *> -> JSONObject(value.entries.associate { (k, v) -> k.toString() to jsonValue(v) })
    else -> value
}
