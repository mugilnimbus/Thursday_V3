package app.thursday.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.data.ApiException
import app.thursday.data.Device
import app.thursday.data.LlmSettings
import app.thursday.domain.formatContext
import app.thursday.graph
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Chip
import app.thursday.ui.common.Field
import app.thursday.ui.common.ListBox
import app.thursday.ui.common.ListRow
import app.thursday.ui.common.Look
import app.thursday.ui.common.Panel
import app.thursday.ui.common.Seg
import app.thursday.ui.common.TopBar
import app.thursday.ui.common.Txt
import app.thursday.ui.relativeTime
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Settings on the phone. Every change asks for the phone's fingerprint or lock-screen credential first.
 * API keys are never shown or written here; only whether each is set.
 */
@Composable
fun SettingsScreen(activity: MainActivity, onTheme: (String) -> Unit) {
    var tab by remember { mutableStateOf("phone") }
    Column(Modifier.fillMaxSize()) {
        TopBar("Settings")
        LazyColumn(contentPadding = PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s4)) {
            item {
                Seg(listOf("phone" to "Phone", "agents" to "Agents", "prompts" to "Prompts", "pc" to "PC"), tab, { tab = it })
            }
            item {
                when (tab) {
                    "phone" -> PhoneTab(activity, onTheme)
                    "agents" -> AgentsTab(activity)
                    "prompts" -> PromptsTab(activity)
                    else -> PcTab(activity)
                }
            }
        }
    }
}

@Composable
private fun SwitchRow(title: String, help: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    val p = LocalPalette.current
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Txt(title)
            Caption(help)
        }
        Switch(checked, onChange, colors = SwitchDefaults.colors(checkedTrackColor = p.accentFill, checkedThumbColor = p.accentBright, checkedBorderColor = p.accent))
    }
}

@Composable
private fun PhoneTab(activity: MainActivity, onTheme: (String) -> Unit) {
    val graph = activity.graph
    val scope = rememberCoroutineScope()
    var stay by remember { mutableStateOf(graph.prefs.stayConnected) }
    var lock by remember { mutableStateOf(graph.prefs.appLock) }
    var theme by remember { mutableStateOf(graph.prefs.theme) }
    var face by remember { mutableStateOf(graph.prefs.faceAnimation) }
    var confirmUnpair by remember { mutableStateOf(false) }
    val pairing by graph.pairing.collectAsStateWithLifecycle()
    Column(verticalArrangement = Arrangement.spacedBy(Space.s4)) {
        Panel {
            SwitchRow("Stay connected", "Keeps a quiet connection so approvals and finished tasks notify you with the phone locked.", stay) { on ->
                stay = on
                graph.prefs.stayConnected = on
                graph.syncService()
            }
            SwitchRow("App lock", "Ask for your fingerprint or phone PIN to open Thursday.", lock) { on ->
                scope.launch {
                    if (activity.guard.confirm(if (on) "Turn on app lock" else "Turn off app lock")) {
                        lock = on
                        graph.prefs.appLock = on
                    }
                }
            }
            SwitchRow("Face animation", "Shows the particle face in a chat while Thursday listens, thinks and speaks. The line along the bottom stays either way.", face) { on ->
                face = on
                graph.prefs.faceAnimation = on
            }
            Txt("Theme")
            Seg(listOf("black" to "Black", "white" to "White"), theme, { theme = it; onTheme(it) })
        }
        Panel {
            Txt("This phone", weight = FontWeight.SemiBold)
            Caption("Paired with ${pairing?.baseUrl ?: "—"}")
            if (confirmUnpair) {
                Caption("This forgets the pairing on this phone. Revoke it on the PC too (Settings, Devices).")
                Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                    Btn("Forget pairing", { graph.unpair() }, look = Look.DANGER, small = true)
                    Btn("Cancel", { confirmUnpair = false }, look = Look.PLAIN, small = true)
                }
            } else Btn("Unpair…", { confirmUnpair = true }, look = Look.DANGER, small = true)
        }
    }
}

@Composable
private fun AgentsTab(activity: MainActivity) {
    Column(verticalArrangement = Arrangement.spacedBy(Space.s4)) {
        AgentCard(activity, "main", "Main agent")
        AgentCard(activity, "voice", "Voice agent")
    }
}

@Composable
private fun AgentCard(activity: MainActivity, agent: String, title: String) {
    val graph = activity.graph
    val api = graph.api
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    var settings by remember { mutableStateOf<LlmSettings?>(null) }
    var endpoint by remember { mutableStateOf("") }
    var model by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    fun take(s: LlmSettings) {
        settings = s
        endpoint = s.baseUrl
        model = s.model
    }
    LaunchedEffect(agent) { runCatching { api.llm(agent) }.onSuccess(::take).onFailure { error = it.message } }

    fun run(label: String, prompt: String, block: suspend () -> LlmSettings) {
        scope.launch {
            if (!activity.guard.confirm(prompt)) return@launch
            busy = label
            error = null
            try {
                take(block())
            } catch (e: ApiException) {
                error = e.message
            } finally {
                busy = ""
            }
        }
    }

    Panel {
        val s = settings
        Row(verticalAlignment = Alignment.CenterVertically) {
            Txt(title, Modifier.weight(1f), size = Type.title, weight = FontWeight.SemiBold)
            when {
                busy == "load" || busy == "reload" -> Chip("loading…", p.accentBright)
                s == null -> Chip("…", p.muted)
                !s.supportsLifecycle -> Chip("remote", p.muted)
                s.loaded -> Chip("loaded · ${formatContext(s.loadedContext)}", p.success)
                else -> Chip("loads on first use", p.muted)
            }
        }
        if (s == null) {
            Caption(error ?: "Loading…", color = if (error != null) p.danger else p.muted)
            return@Panel
        }
        Caption("Provider: ${if (s.provider == "lmstudio") "LM Studio" else "OpenAI-compatible"}")
        Field(endpoint, { endpoint = it }, label = "Endpoint", mono = true)
        Field(model, { model = it }, label = "Model", mono = true)
        if (s.sendsOffPc) Txt("Everything in this agent's context leaves this PC.", color = p.danger, size = Type.caption, weight = FontWeight.SemiBold)
        Caption("API key: ${if (s.apiKeySet) "set" else "not set"}${s.apiKeySource?.let { " · $it in .env" } ?: ""}")
        if (endpoint.trim() != s.baseUrl || model.trim() != s.model) {
            Btn("Save", {
                run("save", "Change the $title model") {
                    val body = JSONObject()
                    if (endpoint.trim() != s.baseUrl) body.put("base_url", endpoint.trim())
                    if (model.trim() != s.model) body.put("model", model.trim())
                    app.thursday.data.Parse.llm(graph.api.putLlm(agent, body))
                }
            }, look = Look.PRIMARY, enabled = busy.isEmpty())
        }
        Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
            Btn("Reload keys", { run("keys", "Reload API keys") { api.reloadKeys(agent) } }, small = true, enabled = busy.isEmpty())
            if (s.supportsLifecycle) {
                Btn("Reload model", { run("reload", "Reload the $title model") { api.model(agent, "reload") } }, small = true, enabled = busy.isEmpty())
                if (s.loaded) Btn("Unload", { run("unload", "Unload the $title model") { api.model(agent, "unload") } }, small = true, enabled = busy.isEmpty())
                else Btn("Load", { run("load", "Load the $title model") { api.model(agent, "load") } }, small = true, enabled = busy.isEmpty())
            }
        }
        error?.let { Caption(it, color = p.danger) }
    }
}

@Composable
private fun PromptsTab(activity: MainActivity) {
    val api = activity.graph.api
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    var agent by remember { mutableStateOf("main") }
    var text by remember { mutableStateOf("") }
    var saved by remember { mutableStateOf("") }
    var version by remember { mutableIntStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    LaunchedEffect(agent, reload) {
        runCatching { api.prompt(agent) }.onSuccess {
            text = it.optString("text"); saved = text; version = it.optInt("version")
        }.onFailure { error = it.message }
    }
    Column(verticalArrangement = Arrangement.spacedBy(Space.s3)) {
        Seg(listOf("main" to "Main agent", "voice" to "Voice agent"), agent, { agent = it })
        Caption(if (version > 0) "Version $version" else "Built-in default")
        Field(text, { text = it }, mono = true, minLines = 10)
        Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
            Btn("Save as version ${version + 1}", {
                scope.launch {
                    if (activity.guard.confirm("Save the system prompt")) {
                        runCatching { api.savePrompt(agent, text) }.onSuccess { reload++ }.onFailure { error = it.message }
                    }
                }
            }, look = Look.PRIMARY, enabled = text != saved && text.isNotBlank())
            Btn("Discard", { text = saved }, look = Look.PLAIN, enabled = text != saved)
        }
        error?.let { Caption(it, color = p.danger) }
        Caption("New tasks use the saved prompt. Older versions can be restored from the dashboard.")
    }
}

@Composable
private fun PcTab(activity: MainActivity) {
    val graph = activity.graph
    val api = graph.api
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    var devices by remember { mutableStateOf<List<Device>>(emptyList()) }
    var backup by remember { mutableStateOf<JSONObject?>(null) }
    var general by remember { mutableStateOf<JSONObject?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    val me by graph.pairing.collectAsStateWithLifecycle()
    LaunchedEffect(reload) {
        runCatching { devices = api.devices() }
        runCatching { backup = api.backupSettings() }
        runCatching { general = api.general() }
    }
    Column(verticalArrangement = Arrangement.spacedBy(Space.s4)) {
        Panel {
            Txt("Paired devices", weight = FontWeight.SemiBold)
            ListBox {
                devices.forEach { d ->
                    ListRow {
                        Column(Modifier.weight(1f)) {
                            Txt(d.name + if (d.id == me?.deviceId) " (this phone)" else "")
                            Caption("Paired ${relativeTime(d.createdAt)}${d.lastSeen?.let { " · last seen ${relativeTime(it)}" } ?: ""}")
                        }
                        if (d.id != me?.deviceId) Btn("Revoke", {
                            scope.launch {
                                if (activity.guard.confirm("Revoke ${d.name}")) {
                                    runCatching { api.revokeDevice(d.id) }.onSuccess { reload++ }.onFailure { graph.live.toast(it.message ?: "Could not revoke.") }
                                }
                            }
                        }, look = Look.DANGER, small = true)
                    }
                }
            }
            Caption("New pairing codes can only be made on the PC.")
        }
        Panel {
            Txt("Backup", weight = FontWeight.SemiBold)
            val b = backup
            val last = b?.optJSONObject("last_run")
            Caption(if (b == null) "…" else "Folder: ${b.optString("folder").ifEmpty { "not set" }} · ${if (b.optBoolean("daily")) "daily" else "manual"} · keeps ${b.optInt("keep_copies")}")
            Caption(last?.let { "Last: ${relativeTime(it.optString("created_at"))} · ${if (it.optBoolean("complete")) "complete" else "partial"}" } ?: "No backup yet")
            Btn(if (busy) "Backing up…" else "Back up now", {
                scope.launch {
                    busy = true
                    runCatching { api.backupNow() }.onSuccess { graph.live.toast("Backup finished."); reload++ }.onFailure { graph.live.toast(it.message ?: "Backup failed.") }
                    busy = false
                }
            }, small = true, enabled = !busy && b?.optString("folder").orEmpty().isNotEmpty())
        }
        Panel {
            Txt("General", weight = FontWeight.SemiBold)
            val g = general
            Caption(
                if (g == null) "…" else listOf(
                    "Summarise older turns at ${g.optDouble("compaction_threshold_percent", 90.0).toInt()}%",
                    "Keep the PC awake while paused for ${g.optDouble("keep_awake_paused_minutes", 30.0).toInt()} min",
                    "Keep traces ${g.optInt("trace_retention_days")} days, metrics ${g.optInt("metrics_retention_days")} days",
                ).joinToString("\n"),
            )
            Caption("Change these in the dashboard on the PC.", color = p.muted)
        }
    }
}
