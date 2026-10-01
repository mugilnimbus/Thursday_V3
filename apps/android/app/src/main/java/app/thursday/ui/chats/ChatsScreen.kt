package app.thursday.ui.chats

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.R
import app.thursday.data.ApiException
import app.thursday.data.Chat
import app.thursday.graph
import app.thursday.live.Connection
import app.thursday.ui.Nav
import app.thursday.ui.Screen
import app.thursday.ui.common.BannerRow
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Dot
import app.thursday.ui.common.Field
import app.thursday.ui.common.IconButton
import app.thursday.ui.common.LineIcon
import app.thursday.ui.common.ListBox
import app.thursday.ui.common.ListRow
import app.thursday.ui.common.Look
import app.thursday.ui.common.SectionTitle
import app.thursday.ui.common.Txt
import app.thursday.ui.relativeTime
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.launch

@Composable
fun ChatsScreen(activity: MainActivity, nav: Nav) {
    val live = activity.graph.live
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    val projects by live.projects.collectAsStateWithLifecycle()
    val chats by live.chats.collectAsStateWithLifecycle()
    val approvals by live.approvals.collectAsStateWithLifecycle()
    val running by live.running.collectAsStateWithLifecycle()
    val banners by live.banners.collectAsStateWithLifecycle()
    val loaded by live.loaded.collectAsStateWithLifecycle()
    val error by live.error.collectAsStateWithLifecycle()
    val connection by live.stream.state.collectAsStateWithLifecycle()
    var renaming by remember { mutableStateOf<Chat?>(null) }
    var deleting by remember { mutableStateOf<Chat?>(null) }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().height(52.dp).padding(horizontal = Space.s4), verticalAlignment = Alignment.CenterVertically) {
            Image(painterResource(R.drawable.logo), contentDescription = null, modifier = Modifier.size(28.dp))
            Txt("Thursday", Modifier.padding(start = Space.s2).weight(1f), size = Type.title, weight = FontWeight.SemiBold)
            val (label, color) = when (connection) {
                Connection.LIVE -> "Live" to p.success
                Connection.CONNECTING -> "Connecting" to p.warning
                Connection.REVOKED -> "Removed" to p.danger
                Connection.OFFLINE -> "Offline" to p.danger
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).background(color, androidx.compose.foundation.shape.CircleShape))
                Caption(" $label", color = p.muted)
            }
            IconButton("refresh", "Refresh", {
                scope.launch {
                    live.refreshAll()
                    live.toast("Up to date.")
                }
            })
            IconButton("plus", "New project", { nav.push(Screen.NewProject) })
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s3)) {
            items(banners) { BannerRow(it.text) }
            if (!loaded) item {
                Caption(error ?: "Connecting to your PC…", color = if (error != null) p.danger else p.muted)
            }
            if (loaded && projects.isEmpty()) item {
                Column(verticalArrangement = Arrangement.spacedBy(Space.s3)) {
                    Caption("No projects yet. A project is a folder on your PC that Thursday may work in.", color = p.muted)
                    Btn("Add a project folder", { nav.push(Screen.NewProject) }, look = Look.PRIMARY)
                }
            }
            items(projects, key = { it.id }) { project ->
                Column(verticalArrangement = Arrangement.spacedBy(Space.s2)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        SectionTitle(project.name, Modifier.weight(1f))
                        Btn("Files", { nav.push(Screen.Files(project.id, project.name)) }, look = Look.PLAIN, small = true)
                    }
                    ListBox {
                        (chats[project.id] ?: emptyList()).forEach { chat ->
                            val dot = when {
                                approvals.any { it.chatId == chat.id } -> "warn"
                                running.any { it.chatId == chat.id && it.state == "input_required" } -> "warn"
                                running.any { it.chatId == chat.id } -> "run"
                                else -> ""
                            }
                            ListRow(onClick = { nav.push(Screen.Chat(chat.id)) }) {
                                Dot(dot)
                                Column(Modifier.weight(1f)) {
                                    Txt(chat.title, maxLines = 1)
                                    Caption(
                                        when (dot) { "warn" -> "Waiting for your approval"; "run" -> "Working"; else -> relativeTime(chat.lastActivity) },
                                        maxLines = 1,
                                    )
                                }
                                ChatMenu(onRename = { renaming = chat }, onDelete = { deleting = chat })
                            }
                        }
                        ListRow(onClick = {
                            scope.launch {
                                try {
                                    nav.push(Screen.Chat(live.createChat(project.id).id))
                                } catch (e: ApiException) {
                                    live.toast(e.message ?: "Could not make a chat.")
                                }
                            }
                        }) {
                            LineIcon("plus", p.muted, 18.dp)
                            Caption("New chat")
                        }
                    }
                }
            }
        }
    }

    renaming?.let { chat ->
        var title by remember(chat.id) { mutableStateOf(chat.title) }
        AlertDialog(
            onDismissRequest = { renaming = null },
            containerColor = p.bg,
            title = { Txt("Rename chat", size = Type.title, weight = FontWeight.SemiBold) },
            text = { Field(title, { title = it }, label = "Name") },
            confirmButton = {
                Btn("Rename", {
                    scope.launch {
                        runCatching { live.renameChat(chat.id, title.trim()) }.onFailure { live.toast(it.message ?: "Could not rename.") }
                        renaming = null
                    }
                }, look = Look.PRIMARY, enabled = title.isNotBlank())
            },
            dismissButton = { Btn("Cancel", { renaming = null }, look = Look.PLAIN) },
        )
    }
    deleting?.let { chat ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            containerColor = p.bg,
            title = { Txt("Delete chat “${chat.title}”?", size = Type.title, weight = FontWeight.SemiBold) },
            text = { Caption("Its messages, tasks, traces, and allow-always rules are removed from every service. A running task is stopped first. This cannot be undone.") },
            confirmButton = {
                Btn("Delete chat", {
                    scope.launch {
                        if (activity.guard.confirm("Delete this chat")) {
                            runCatching { live.deleteChat(chat.id) }.onFailure { live.toast(it.message ?: "Could not delete.") }
                        }
                        deleting = null
                    }
                }, look = Look.DANGER)
            },
            dismissButton = { Btn("Cancel", { deleting = null }, look = Look.PLAIN) },
        )
    }
}

@Composable
private fun ChatMenu(onRename: () -> Unit, onDelete: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    val p = LocalPalette.current
    Box {
        IconButton("more", "Chat actions", { open = true })
        DropdownMenu(open, { open = false }, containerColor = p.bg) {
            DropdownMenuItem(text = { Txt("Rename", size = Type.caption) }, onClick = { open = false; onRename() })
            DropdownMenuItem(text = { Txt("Delete chat…", color = p.danger, size = Type.caption) }, onClick = { open = false; onDelete() })
        }
    }
}
