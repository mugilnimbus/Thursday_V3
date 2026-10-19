package app.thursday.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.data.Device
import app.thursday.graph
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.ListBox
import app.thursday.ui.common.ListRow
import app.thursday.ui.common.Look
import app.thursday.ui.common.Txt
import app.thursday.ui.relativeTime
import app.thursday.ui.theme.Type
import kotlinx.coroutines.launch
import org.json.JSONObject

// Settings kept on the PC, as the phone shows them.

/** A number of days as the dashboard's list words it: 7 days, 3 months, 1 year. */
internal fun daysText(days: Int): String = when {
    days == 1 -> "1 day"
    days % 365 == 0 -> if (days == 365) "1 year" else "${days / 365} years"
    days >= 60 && days % 30 == 0 -> "${days / 30} months"
    else -> "$days days"
}

@Composable
internal fun DevicesPage(activity: MainActivity, onBack: () -> Unit) {
    val graph = activity.graph
    val api = graph.api
    val scope = rememberCoroutineScope()
    var devices by remember { mutableStateOf<List<Device>?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val me by graph.pairing.collectAsStateWithLifecycle()
    LaunchedEffect(reload) { runCatching { devices = api.devices() } }
    SettingsPage("Devices", onBack) {
        val list = devices
        if (list == null) Caption("…") else ListBox {
            list.forEach { d ->
                ListRow {
                    Column(Modifier.weight(1f)) {
                        Txt(d.name + if (d.id == me?.deviceId) " (this device)" else "")
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
        Caption("A revoked device can no longer reach the PC. New pairing codes can only be made on the PC.")
    }
}

@Composable
internal fun BackupPage(activity: MainActivity, onBack: () -> Unit) {
    val graph = activity.graph
    val api = graph.api
    val scope = rememberCoroutineScope()
    var backup by remember { mutableStateOf<JSONObject?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    LaunchedEffect(reload) { runCatching { backup = api.backupSettings() } }
    SettingsPage("Backup", onBack) {
        val b = backup
        val last = b?.optJSONObject("last_run")
        Group("Where and how often") {
            Txt(b?.optString("folder")?.ifEmpty { "No folder set" } ?: "…", mono = true, size = Type.caption)
            Caption(if (b == null) "…" else "${if (b.optBoolean("daily")) "Every day" else "Only when asked"} · keeps ${b.optInt("keep_copies")} copies")
            Caption("Change the folder and schedule in the dashboard on the PC.")
        }
        Group("Last backup") {
            Caption(last?.let { "${relativeTime(it.optString("created_at"))} · ${if (it.optBoolean("complete")) "complete" else "partial"}" } ?: "No backup yet")
            Btn(if (busy) "Backing up…" else "Back up now", {
                scope.launch {
                    busy = true
                    runCatching { api.backupNow() }.onSuccess { graph.live.toast("Backup finished."); reload++ }.onFailure { graph.live.toast(it.message ?: "Backup failed.") }
                    busy = false
                }
            }, enabled = !busy && b?.optString("folder").orEmpty().isNotEmpty())
        }
    }
}

@Composable
internal fun GeneralPage(activity: MainActivity, onBack: () -> Unit) {
    val api = activity.graph.api
    var general by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(Unit) { runCatching { general = api.general() } }
    SettingsPage("General", onBack) {
        val g = general
        Group("Keeping the PC awake") {
            Caption(if (g == null) "…" else "While a task is paused, the PC stays awake for ${g.optDouble("keep_awake_paused_minutes", 30.0).toInt()} minutes.")
        }
        Group("How long things are kept") {
            // An older PC answers with the earlier name for the same setting.
            val keep = g?.let { if (it.has("data_retention_days")) it.optInt("data_retention_days") else it.optInt("trace_retention_days") }
            Caption(
                when {
                    g == null || keep == null -> "…"
                    keep == 0 -> "Working data is kept until you delete it. Metrics for ${g.optInt("metrics_retention_days")} days."
                    else -> "Working data for ${daysText(keep)}, metrics for ${g.optInt("metrics_retention_days")} days."
                },
            )
            Caption("Working data is how tasks were done: their steps and traces, the saved state of finished tasks, and the log of tool calls. Chats and their messages stay until you delete them. Monitor shows how much is stored.")
        }
        Caption("Change these in the dashboard on the PC.")
    }
}
