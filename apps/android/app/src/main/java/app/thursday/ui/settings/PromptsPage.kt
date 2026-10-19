package app.thursday.ui.settings

import androidx.compose.foundation.layout.Row
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import app.thursday.MainActivity
import app.thursday.graph
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Field
import app.thursday.ui.common.Look
import app.thursday.ui.common.Seg
import app.thursday.ui.theme.LocalPalette
import kotlinx.coroutines.launch

@Composable
internal fun PromptsPage(activity: MainActivity, onBack: () -> Unit) {
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
    val dirty = text != saved
    SettingsPage(
        "Prompts", onBack,
        save = {
            scope.launch {
                if (activity.guard.confirm("Save the system prompt")) {
                    runCatching { api.savePrompt(agent, text) }.onSuccess { reload++ }.onFailure { error = it.message }
                }
            }
        },
        saveEnabled = dirty && text.isNotBlank(),
    ) {
        Seg(listOf("main" to "Main agent", "voice" to "Voice agent"), agent, { agent = it })
        Row(verticalAlignment = Alignment.CenterVertically) {
            Caption(if (version > 0) "Version $version" else "Built-in default")
            Fill()
            if (dirty) Btn("Discard", { text = saved }, look = Look.PLAIN, small = true)
        }
        if (dirty) Caption("Save stores this as version ${version + 1}.", color = p.warning)
        Field(text, { text = it }, mono = true, minLines = 12)
        error?.let { Caption(it, color = p.danger) }
        Caption("New tasks use the saved prompt. Older versions can be restored from the dashboard.")
    }
}
