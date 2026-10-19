package app.thursday.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.graph
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Look
import app.thursday.ui.common.Pick
import app.thursday.ui.common.Seg
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.launch

// Settings of this phone: they apply at once and are kept on the phone.

@Composable
internal fun AppPage(activity: MainActivity, onTheme: (String) -> Unit, onBack: () -> Unit) {
    val graph = activity.graph
    val scope = rememberCoroutineScope()
    var stay by remember { mutableStateOf(graph.prefs.stayConnected) }
    var lock by remember { mutableStateOf(graph.prefs.appLock) }
    var approvalCheck by remember { mutableStateOf(graph.prefs.approvalCheck) }
    var theme by remember { mutableStateOf(graph.prefs.theme) }
    var face by remember { mutableStateOf(graph.prefs.faceAnimation) }
    var seeThrough by remember { mutableIntStateOf(graph.prefs.messageTransparency) }
    SettingsPage("App", onBack) {
        Group("Appearance") {
            Txt("Theme")
            Seg(listOf("black" to "Black", "white" to "White"), theme, { theme = it; onTheme(it) })
            SwitchRow("Face animation", "Shows the particle face in a chat while Thursday listens, thinks and speaks. The line along the bottom stays either way.", face) { on ->
                face = on
                graph.prefs.faceAnimation = on
            }
            Pick("Message transparency", (0..100 step 10).map { "$it" to if (it == 0) "0% (solid)" else "$it%" }, "$seeThrough", { chosen ->
                seeThrough = chosen.toInt()
                graph.prefs.messageTransparency = seeThrough
            })
            Caption("How much of the face shows through the messages in a chat. 0% is solid, which is easiest to read.")
        }
        Group("Connection") {
            SwitchRow("Stay connected", "Keeps a quiet connection so approvals and finished tasks notify you with the phone locked.", stay) { on ->
                stay = on
                graph.prefs.stayConnected = on
                graph.syncService()
            }
        }
        Group("Security") {
            SwitchRow("App lock", "Ask for your fingerprint or phone PIN to open Thursday.", lock) { on ->
                scope.launch {
                    if (activity.guard.confirm(if (on) "Turn on app lock" else "Turn off app lock")) {
                        lock = on
                        graph.prefs.appLock = on
                    }
                }
            }
            // Turning the check off is itself checked: whoever holds the phone cannot quietly remove it.
            SwitchRow("Fingerprint before allowing", "Ask for your fingerprint or phone PIN when you press Allow on an approval. A typed or spoken “yes” in the chat is not checked.", approvalCheck) { on ->
                scope.launch {
                    if (activity.guard.confirm(if (on) "Turn on the check before allowing" else "Turn off the check before allowing")) {
                        approvalCheck = on
                        graph.prefs.approvalCheck = on
                    }
                }
            }
        }
        Caption("These apply to this device at once.")
    }
}

@Composable
internal fun PairingPage(activity: MainActivity, onBack: () -> Unit) {
    val graph = activity.graph
    val pairing by graph.pairing.collectAsStateWithLifecycle()
    var confirmUnpair by remember { mutableStateOf(false) }
    SettingsPage("Pairing", onBack) {
        Group("This phone is paired with") {
            Txt(pairing?.baseUrl ?: "—", mono = true, size = Type.caption)
            Caption("The phone reaches the PC at this address over your private network.")
        }
        Group("Unpair") {
            Caption("This forgets the pairing on this phone. Revoke it on the PC too (Settings, Devices). To pair again, make a new code on the PC.")
            if (confirmUnpair) {
                Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
                    Btn("Forget pairing", { graph.unpair() }, look = Look.DANGER)
                    Btn("Cancel", { confirmUnpair = false }, look = Look.PLAIN)
                }
            } else Btn("Unpair…", { confirmUnpair = true }, look = Look.DANGER)
        }
    }
}
