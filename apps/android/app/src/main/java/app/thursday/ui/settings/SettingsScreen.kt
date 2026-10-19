package app.thursday.ui.settings

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.key
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.data.LlmSettings
import app.thursday.domain.AgentChoices
import app.thursday.graph
import app.thursday.ui.PaneHint
import app.thursday.ui.common.TopBar
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.relativeTime
import app.thursday.ui.theme.Space
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Settings on the phone, laid out like the phone's own settings: one scrolling list of subjects, and each subject
 * opens one page that shows all of its settings. Pages that change something on the PC have Save at the top right,
 * and saving asks for the phone's fingerprint or lock-screen credential first.
 * An API key can be typed here and is stored on the PC; it is never shown again, only whether one is set.
 */
@Composable
fun SettingsScreen(activity: MainActivity, onTheme: (String) -> Unit, twoPanes: Boolean = false) {
    var page by remember { mutableStateOf<String?>(null) }
    val back = { page = null }
    BackHandler(enabled = page != null, onBack = back)
    if (twoPanes) {
        // A wide window: the list stays, and the page chosen in it opens beside it.
        val p = LocalPalette.current
        Row(Modifier.fillMaxSize()) {
            Box(Modifier.width(360.dp).fillMaxHeight()) { SettingsList(activity, open = page) { page = it } }
            Box(Modifier.width(1.dp).fillMaxHeight().background(p.border))
            Box(Modifier.weight(1f).fillMaxHeight()) {
                val shown = page
                if (shown == null) PaneHint("Choose what to set on the left.")
                else CompositionLocalProvider(LocalBesideList provides true) { key(shown) { SettingsPages(activity, shown, onTheme, back) } }
            }
        }
        return
    }
    val shown = page
    if (shown == null) SettingsList(activity, open = null) { page = it } else SettingsPages(activity, shown, onTheme, back)
}

/** True while a settings page is shown beside the list it was chosen from, where it needs no way back. */
internal val LocalBesideList = compositionLocalOf { false }

@Composable
private fun SettingsPages(activity: MainActivity, page: String, onTheme: (String) -> Unit, back: () -> Unit) {
    when (page) {
        "app" -> AppPage(activity, onTheme, back)
        "pairing" -> PairingPage(activity, back)
        "main" -> AgentPage(activity, "main", "Main agent", back)
        "voice" -> AgentPage(activity, "voice", "Voice agent", back)
        "prompts" -> PromptsPage(activity, back)
        "devices" -> DevicesPage(activity, back)
        "backup" -> BackupPage(activity, back)
        else -> GeneralPage(activity, back)
    }
}

private fun agentSummary(s: LlmSettings?): String {
    if (s == null) return "…"
    val state = when {
        s.reachable == false -> "not reachable"
        !s.supportsLifecycle -> "remote"
        s.loaded -> "loaded"
        else -> "off"
    }
    return listOf(s.model.substringAfterLast('/').ifEmpty { "no model" }, AgentChoices.kind(s.provider).label, state).joinToString(" · ")
}

@Composable
private fun SettingsList(activity: MainActivity, open: String?, choose: (String) -> Unit) {
    val graph = activity.graph
    val api = graph.api
    val pairing by graph.pairing.collectAsStateWithLifecycle()
    var main by remember { mutableStateOf<LlmSettings?>(null) }
    var voice by remember { mutableStateOf<LlmSettings?>(null) }
    var devices by remember { mutableStateOf<Int?>(null) }
    var backup by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(Unit) {
        launch { runCatching { main = api.llm("main") } }
        launch { runCatching { voice = api.llm("voice") } }
        launch { runCatching { devices = api.devices().size } }
        launch { runCatching { backup = api.backupSettings() } }
    }
    val prefs = graph.prefs
    Column(Modifier.fillMaxSize()) {
        TopBar("Settings")
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s4)) {
            // One row of the list: its page is marked while it is open beside the list.
            val entry: @Composable (String, String, String, String) -> Unit = { page, icon, title, summary ->
                ListEntry(icon, title, summary, marked = page == open) { choose(page) }
            }
            ListGroup("This device", listOf(
                {
                    entry("app", "phone", "App", listOf(
                        if (prefs.theme == "white") "White theme" else "Black theme",
                        if (prefs.appLock) "locked" else "no lock",
                        if (prefs.stayConnected) "stays connected" else "connects when open",
                    ).joinToString(" · "))
                },
                { entry("pairing", "link", "Pairing", pairing?.baseUrl?.removePrefix("https://") ?: "Not paired") },
            ))
            ListGroup("Agents", listOf(
                { entry("main", "chip", "Main agent", agentSummary(main)) },
                { entry("voice", "mic", "Voice agent", agentSummary(voice)) },
                { entry("prompts", "edit", "Prompts", "What each agent is told before every task") },
            ))
            ListGroup("The PC", listOf(
                { entry("devices", "devices", "Devices", devices?.let { if (it == 1) "1 paired device" else "$it paired devices" } ?: "…") },
                {
                    val last = backup?.optJSONObject("last_run")
                    entry("backup", "database", "Backup", when {
                        backup == null -> "…"
                        last != null -> "Last backup ${relativeTime(last.optString("created_at"))}"
                        else -> "No backup yet"
                    })
                },
                { entry("general", "settings", "General", "Keeping awake, and how long data is kept") },
            ))
        }
    }
}
