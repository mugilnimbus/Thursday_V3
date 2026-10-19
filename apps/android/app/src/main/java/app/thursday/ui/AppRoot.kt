package app.thursday.ui

import android.Manifest
import android.hardware.display.DisplayManager
import android.os.Build
import android.view.Display
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
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.R
import app.thursday.domain.NavigationEdge
import app.thursday.domain.WindowShape
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

    /** Open something from a section's list. It takes the place of whatever the list had open, so Back returns to the list. */
    fun open(screen: Screen) {
        while (stack.size > 1) stack.removeAt(stack.lastIndex)
        stack.add(screen)
    }
    fun section(screen: Screen) {
        stack.clear()
        stack.add(screen)
    }
    fun back(): Boolean = if (stack.size > 1) { stack.removeAt(stack.lastIndex); true } else false
}

private const val RELOCK_AFTER_MS = 30_000L
private const val TURN_SETTLES_MS = 400L
private val LIST_PANE = 360.dp
private val RAIL = 76.dp

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

/**
 * The paired app. How it is laid out follows the window ([WindowShape]):
 * - the navigation stays on the edge of the device it is on when the device is held upright (its bottom edge):
 *   turned on its side, that edge is the right or the left of the screen, and only the icons turn;
 * - along the bottom of a narrow screen it is put away inside a chat, so the chat has the height (the Back arrow
 *   returns to the list);
 * - a tablet lying down shows a section's list and what is opened from it side by side.
 * Turning the device only redraws this; the open screens and what was typed stay.
 */
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
    val turns = rememberQuarterTurns(activity)
    val window = LocalConfiguration.current.let { WindowShape(it.screenWidthDp, it.screenHeightDp, turns) }
    // While the keyboard is open the bar along the bottom is put away: it would sit on top of the keyboard and take
    // room from what is being typed into.
    val typing = WindowInsets.ime.getBottom(LocalDensity.current) > 0
    val bottomBar = window.navigation == NavigationEdge.BOTTOM && !typing && !(window.barHiddenInChat && nav.current is Screen.Chat)
    // Clear of the status bar, the system's own navigation, a camera cut-out at the side, and the keyboard.
    Row(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
        if (window.navigation == NavigationEdge.LEFT) NavRail(nav, window)
        Column(Modifier.weight(1f).fillMaxHeight()) {
            Box(Modifier.weight(1f).fillMaxWidth()) {
                Panes(activity, nav, window, onTheme)
                toast.value?.let {
                    Box(
                        Modifier.align(Alignment.BottomCenter).padding(Space.s3).fillMaxWidth().clip(RoundedCornerShape(21.dp))
                            .background(p.bg).padding(1.dp).clip(RoundedCornerShape(21.dp)).background(p.accentSoft).padding(Space.s3),
                    ) { Txt(it, size = Type.caption) }
                }
            }
            if (bottomBar) TabBar(nav)
        }
        if (window.navigation == NavigationEdge.RIGHT) NavRail(nav, window)
    }
}

/**
 * How far the screen is turned from the way the device is held naturally, in quarter turns, kept up to date.
 *
 * Two things say that the device was turned, and neither is enough alone. The display says so for every turn, but
 * it can say so before the turn can be read, and what is read then is the old one. The window's new shape arrives
 * for a quarter turn, but not for a turn right round from one side to the other, which changes no shape. So the
 * turn is read again after each of them, and once more when the turn has settled. It is read from the display as
 * the system has it, not as this window has last been told.
 */
@Composable
private fun rememberQuarterTurns(activity: MainActivity): Int {
    val shape = LocalConfiguration.current
    val displays = remember(activity) { activity.applicationContext.getSystemService(DisplayManager::class.java) }
    fun now(): Int = displays.getDisplay(activity.display?.displayId ?: Display.DEFAULT_DISPLAY)?.rotation ?: 0
    var turns by remember { mutableIntStateOf(now()) }
    var changes by remember { mutableIntStateOf(0) }
    DisposableEffect(displays) {
        val listener = object : DisplayManager.DisplayListener {
            override fun onDisplayAdded(displayId: Int) = Unit
            override fun onDisplayRemoved(displayId: Int) = Unit
            override fun onDisplayChanged(displayId: Int) {
                turns = now()
                changes++
            }
        }
        displays.registerDisplayListener(listener, null)
        onDispose { displays.unregisterDisplayListener(listener) }
    }
    LaunchedEffect(shape.screenWidthDp, shape.screenHeightDp, changes) {
        turns = now()
        delay(TURN_SETTLES_MS)
        turns = now()
    }
    return turns
}

/** One pane, or on a wide window a section's list with what is opened from it beside it. */
@Composable
private fun Panes(activity: MainActivity, nav: Nav, window: WindowShape, onTheme: (String) -> Unit) {
    val p = LocalPalette.current
    val current = nav.current
    val root = nav.stack.first()
    if (!(window.twoPanes && (root == Screen.Chats || root is Screen.Trace))) {
        Pane(activity, nav, current, window, onTheme, besideList = false)
        return
    }
    Row(Modifier.fillMaxSize()) {
        Box(Modifier.width(LIST_PANE).fillMaxHeight()) {
            if (root == Screen.Chats) ChatsScreen(activity, nav, open = (current as? Screen.Chat)?.chatId)
            else TraceScreen(activity, nav, null, open = (current as? Screen.Trace)?.taskId)
        }
        Box(Modifier.width(1.dp).fillMaxHeight().background(p.border))
        Box(Modifier.weight(1f).fillMaxHeight()) {
            if (nav.stack.size == 1) {
                PaneHint(if (root == Screen.Chats) "Choose a chat on the left, or start a new one." else "Choose a task on the left to see how it was done.")
            } else {
                // Only what the list itself opened sits "beside" it; anything opened from there has a way back.
                Pane(activity, nav, current, window, onTheme, besideList = nav.stack.size == 2)
            }
        }
    }
}

@Composable
private fun Pane(activity: MainActivity, nav: Nav, screen: Screen, window: WindowShape, onTheme: (String) -> Unit, besideList: Boolean) {
    when (screen) {
        Screen.Chats -> ChatsScreen(activity, nav)
        // A chat or a task that takes another's place starts afresh: its own draft, scroll position and voice.
        is Screen.Chat -> key(screen.chatId) { ChatScreen(activity, nav, screen.chatId, besideList = besideList) }
        is Screen.Trace -> key(screen.taskId) { TraceScreen(activity, nav, screen.taskId, besideList = besideList) }
        Screen.Tools -> ToolsScreen(activity)
        Screen.Monitor -> MonitorScreen(activity)
        Screen.Settings -> SettingsScreen(activity, onTheme, twoPanes = window.twoPanes)
        Screen.NewProject -> NewProjectScreen(activity, nav)
        is Screen.Files -> FilesScreen(activity, nav, screen.projectId, screen.projectName)
    }
}

/** What the second pane says while nothing is open in it. */
@Composable
fun PaneHint(text: String) {
    Box(Modifier.fillMaxSize().padding(Space.s5), contentAlignment = Alignment.Center) { Caption(text) }
}

private data class Destination(val id: String, val label: String, val screen: Screen)

private val DESTINATIONS = listOf(
    Destination("chats", "Chats", Screen.Chats), Destination("trace", "Trace", Screen.Trace(null)), Destination("tools", "Tools", Screen.Tools),
    Destination("monitor", "Monitor", Screen.Monitor), Destination("settings", "Settings", Screen.Settings),
)

private fun sectionOf(nav: Nav): String = when (nav.stack.first()) {
    Screen.Chats, is Screen.Chat, Screen.NewProject, is Screen.Files -> "chats"
    is Screen.Trace -> "trace"
    Screen.Tools -> "tools"
    Screen.Monitor -> "monitor"
    Screen.Settings -> "settings"
}

@Composable
private fun DestinationButton(item: Destination, on: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val p = LocalPalette.current
    Column(
        modifier.clip(RoundedCornerShape(13.dp)).clickable(onClick = onClick).padding(horizontal = 10.dp, vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        TabIcon(item.id, if (on) p.accentBright else p.muted)
        Txt(item.label, color = if (on) p.accentBright else p.muted, size = 11.sp, weight = if (on) FontWeight.SemiBold else FontWeight.Medium, maxLines = 1)
    }
}

/** The navigation along the bottom: the device held upright. */
@Composable
private fun TabBar(nav: Nav) {
    val p = LocalPalette.current
    val section = sectionOf(nav)
    Column {
        Box(Modifier.fillMaxWidth().height(1.dp).background(p.border))
        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceAround) {
            DESTINATIONS.forEach { item -> DestinationButton(item, item.id == section, Modifier) { nav.section(item.screen) } }
        }
    }
}

/**
 * The navigation down a side of the screen: the device is lying on its side. It is the bottom bar where the device
 * has it, seen from the side: on the same edge of the device, spread along it the same way, every destination in
 * the place it has on the device. Only the icons and their names have turned to stay upright.
 */
@Composable
private fun NavRail(nav: Nav, window: WindowShape) {
    val p = LocalPalette.current
    val section = sectionOf(nav)
    val edge: @Composable () -> Unit = { Box(Modifier.width(1.dp).fillMaxHeight().background(p.border)) }
    Row(Modifier.fillMaxHeight()) {
        if (window.navigation == NavigationEdge.RIGHT) edge()
        Column(
            Modifier.width(RAIL).fillMaxHeight().padding(vertical = 4.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.SpaceAround,
        ) {
            (if (window.navigationReversed) DESTINATIONS.asReversed() else DESTINATIONS).forEach { item ->
                DestinationButton(item, item.id == section, Modifier) { nav.section(item.screen) }
            }
        }
        if (window.navigation == NavigationEdge.LEFT) edge()
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
