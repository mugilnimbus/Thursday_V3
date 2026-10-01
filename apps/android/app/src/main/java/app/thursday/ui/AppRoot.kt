package app.thursday.ui

import android.Manifest
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.R
import app.thursday.graph
import app.thursday.ui.chat.ChatScreen
import app.thursday.ui.chats.ChatsScreen
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Look
import app.thursday.ui.common.TabIcon
import app.thursday.ui.common.Txt
import app.thursday.ui.monitor.MonitorScreen
import app.thursday.ui.pair.PairScreen
import app.thursday.ui.projects.FilesScreen
import app.thursday.ui.projects.NewProjectScreen
import app.thursday.ui.settings.SettingsScreen
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.ThursdayTheme
import app.thursday.ui.theme.Type
import app.thursday.ui.tools.ToolsScreen
import app.thursday.ui.trace.TraceScreen
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

sealed interface Screen {
    data object Chats : Screen
    data class Chat(val chatId: String) : Screen
    data class Trace(val taskId: String?) : Screen
    data object Tools : Screen
    data object Monitor : Screen
    data object Settings : Screen
    data object NewProject : Screen
    data class Files(val projectId: String, val projectName: String) : Screen
}

/** Back stack and section switching. Sections reset the stack; chat and trace push onto it. */
class Nav {
    val stack = mutableStateListOf<Screen>(Screen.Chats)
    val current: Screen get() = stack.last()
    fun push(screen: Screen) {
        if (current != screen) stack.add(screen)
    }
    fun section(screen: Screen) {
        stack.clear()
        stack.add(screen)
    }
    fun back(): Boolean = if (stack.size > 1) { stack.removeAt(stack.lastIndex); true } else false
}

private const val RELOCK_AFTER_MS = 30_000L

@Composable
fun AppRoot(activity: MainActivity) {
    val graph = activity.graph
    var theme by remember { mutableStateOf(graph.prefs.theme) }
    ThursdayTheme(theme) {
        val p = LocalPalette.current
        val pairing by graph.pairing.collectAsStateWithLifecycle()
        val revoked by graph.revoked.collectAsStateWithLifecycle()
        var locked by remember { mutableStateOf(graph.prefs.appLock) }
        var hiddenAt by remember { mutableStateOf(0L) }
        LifecycleEventEffect(Lifecycle.Event.ON_STOP) { hiddenAt = System.currentTimeMillis() }
        LifecycleEventEffect(Lifecycle.Event.ON_START) {
            if (graph.prefs.appLock && hiddenAt > 0 && System.currentTimeMillis() - hiddenAt > RELOCK_AFTER_MS) locked = true
        }
        Box(Modifier.fillMaxSize().background(p.bg)) {
            when {
                pairing == null -> PairScreen(activity)
                revoked -> Revoked { graph.unpair() }
                locked -> Lock(activity) { locked = false }
                else -> Main(activity, onTheme = { theme = it; graph.prefs.theme = it })
            }
        }
    }
}

@Composable
private fun Main(activity: MainActivity, onTheme: (String) -> Unit) {
    val graph = activity.graph
    val nav = remember { Nav() }
    val toast = remember { mutableStateOf<String?>(null) }
    val notifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}

    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33) notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        graph.live.start()
        graph.syncService()
    }
    LaunchedEffect(Unit) { graph.live.toasts.collect { toast.value = it } }
    LaunchedEffect(toast.value) {
        if (toast.value != null) {
            delay(4000)
            toast.value = null
        }
    }
    // A notification tap opens its chat.
    val open by activity.openChat
    LaunchedEffect(open) {
        open?.let {
            nav.section(Screen.Chats)
            nav.push(Screen.Chat(it))
            activity.openChat.value = null
        }
    }
    BackHandler(enabled = nav.stack.size > 1) { nav.back() }

    val p = LocalPalette.current
    Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().imePadding()) {
        Box(Modifier.weight(1f)) {
            when (val s = nav.current) {
                Screen.Chats -> ChatsScreen(activity, nav)
                is Screen.Chat -> ChatScreen(activity, nav, s.chatId)
                is Screen.Trace -> TraceScreen(activity, nav, s.taskId)
                Screen.Tools -> ToolsScreen(activity)
                Screen.Monitor -> MonitorScreen(activity)
                Screen.Settings -> SettingsScreen(activity, onTheme)
                Screen.NewProject -> NewProjectScreen(activity, nav)
                is Screen.Files -> FilesScreen(activity, nav, s.projectId, s.projectName)
            }
            toast.value?.let {
                Box(
                    Modifier.align(Alignment.BottomCenter).padding(Space.s3).fillMaxWidth().clip(RoundedCornerShape(21.dp))
                        .background(p.bg).padding(1.dp).clip(RoundedCornerShape(21.dp)).background(p.accentSoft).padding(Space.s3),
                ) { Txt(it, size = Type.caption) }
            }
        }
        TabBar(nav)
    }
}

@Composable
private fun TabBar(nav: Nav) {
    val p = LocalPalette.current
    val section = when (nav.stack.first()) {
        Screen.Chats, is Screen.Chat, Screen.NewProject, is Screen.Files -> "chats"
        is Screen.Trace -> "trace"
        Screen.Tools -> "tools"
        Screen.Monitor -> "monitor"
        Screen.Settings -> "settings"
    }
    Column {
        Box(Modifier.fillMaxWidth().height(1.dp).background(p.border))
        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceAround) {
            listOf(
                Triple("chats", "Chats", Screen.Chats), Triple("trace", "Trace", Screen.Trace(null)), Triple("tools", "Tools", Screen.Tools),
                Triple("monitor", "Monitor", Screen.Monitor), Triple("settings", "Settings", Screen.Settings),
            ).forEach { (id, label, screen) ->
                val on = id == section
                Column(
                    Modifier.clip(RoundedCornerShape(13.dp)).clickable { nav.section(screen) }.padding(horizontal = 10.dp, vertical = 6.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    TabIcon(id, if (on) p.accentBright else p.muted)
                    Txt(label, color = if (on) p.accentBright else p.muted, size = 11.sp, weight = if (on) FontWeight.SemiBold else FontWeight.Medium)
                }
            }
        }
    }
}

@Composable
private fun Revoked(onUnpair: () -> Unit) {
    val p = LocalPalette.current
    Column(Modifier.fillMaxSize().statusBarsPadding().padding(Space.s5), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Txt("This phone was removed on your PC", size = Type.title, weight = FontWeight.SemiBold)
        Spacer(Modifier.height(Space.s3))
        Caption("Its device token no longer works. Pair again with a new code from the dashboard.", color = p.muted)
        Spacer(Modifier.height(Space.s4))
        Btn("Pair again", onUnpair, look = Look.PRIMARY)
    }
}

@Composable
private fun Lock(activity: MainActivity, onUnlocked: () -> Unit) {
    val scope = rememberCoroutineScope()
    val unlock: () -> Unit = { scope.launch { if (activity.guard.confirm("Unlock Thursday")) onUnlocked() } }
    LaunchedEffect(Unit) { unlock() }
    Column(Modifier.fillMaxSize().padding(Space.s5), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Image(painterResource(R.drawable.logo), contentDescription = null, modifier = Modifier.size(96.dp))
        Spacer(Modifier.height(Space.s4))
        Txt("Thursday is locked", size = Type.title, weight = FontWeight.SemiBold)
        Spacer(Modifier.height(Space.s4))
        Btn("Unlock", unlock, look = Look.PRIMARY, modifier = Modifier.width(200.dp))
    }
}
