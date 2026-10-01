package app.thursday.ui.projects

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.thursday.MainActivity
import app.thursday.data.ApiException
import app.thursday.data.FileEntry
import app.thursday.data.FilePreview
import app.thursday.data.FolderListing
import app.thursday.graph
import app.thursday.ui.Nav
import app.thursday.ui.Screen
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Field
import app.thursday.ui.common.LineIcon
import app.thursday.ui.common.ListBox
import app.thursday.ui.common.ListRow
import app.thursday.ui.common.Look
import app.thursday.ui.common.Panel
import app.thursday.ui.common.TopBar
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Make a project from the phone: name it and pick a folder on the PC. Asks for the phone's lock check first. */
@Composable
fun NewProjectScreen(activity: MainActivity, nav: Nav) {
    val graph = activity.graph
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf("") }
    var listing by remember { mutableStateOf<FolderListing?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    fun open(path: String) {
        scope.launch {
            try {
                listing = graph.api.folders(path)
                error = null
            } catch (e: ApiException) {
                error = e.message
            }
        }
    }
    LaunchedEffect(Unit) {
        // Start in the PC user's home folder; the drives are one step up from any drive root.
        runCatching { graph.api.folders("") }.onSuccess { open(it.home) }.onFailure { error = it.message }
    }

    Column(Modifier.fillMaxSize()) {
        TopBar("New project", onBack = { nav.back() })
        val current = listing
        LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s3)) {
            item { Field(name, { name = it }, label = "Name", placeholder = "My project") }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(Space.s1)) {
                    Txt("Folder on the PC", color = p.muted, size = Type.caption, weight = FontWeight.SemiBold)
                    Txt(current?.path?.ifEmpty { "This PC" } ?: "…", mono = true, size = Type.caption)
                    Caption("The main agent can only read and change files inside this folder.")
                }
            }
            error?.let { item { Caption(it, color = p.danger) } }
            if (current != null) item {
                ListBox {
                    current.parent?.let { parent ->
                        ListRow(onClick = { open(parent) }) {
                            LineIcon("back", p.muted, 18.dp)
                            Caption(if (parent.isEmpty()) "This PC (drives)" else "Up one folder")
                        }
                    }
                    current.folders.forEach { folder ->
                        ListRow(onClick = { open(folder.path) }) {
                            LineIcon("folder", p.accentBright, 18.dp)
                            Txt(folder.name, Modifier.weight(1f), maxLines = 1)
                            LineIcon("chev", p.muted, 16.dp)
                        }
                    }
                    if (current.folders.isEmpty()) ListRow { Caption("No folders inside this one.") }
                }
            }
        }
        Box(Modifier.fillMaxWidth().padding(Space.s4)) {
            Btn(
                if (busy) "Creating…" else "Create project here",
                {
                    val folder = current?.path ?: return@Btn
                    busy = true
                    scope.launch {
                        try {
                            if (activity.guard.confirm("Create project", folder)) {
                                val project = graph.live.createProject(name.trim(), folder)
                                val chat = graph.live.createChat(project.id)
                                nav.section(Screen.Chats)
                                nav.push(Screen.Chat(chat.id))
                            }
                        } catch (e: ApiException) {
                            error = e.message
                        } finally {
                            busy = false
                        }
                    }
                },
                look = Look.PRIMARY, modifier = Modifier.fillMaxWidth(),
                enabled = !busy && name.isNotBlank() && !current?.path.isNullOrEmpty(),
            )
        }
    }
}

private fun size(bytes: Long?): String = when {
    bytes == null -> ""
    bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1_048_576.0)
    bytes >= 1024 -> "${bytes / 1024} kB"
    else -> "$bytes B"
}

/** Look inside a project's folder: browse, search file names, and preview text files. Read-only. */
@Composable
fun FilesScreen(activity: MainActivity, nav: Nav, projectId: String, projectName: String) {
    val api = activity.graph.api
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    var path by remember { mutableStateOf("") }
    var q by remember { mutableStateOf("") }
    var entries by remember { mutableStateOf<List<FileEntry>?>(null) }
    var preview by remember { mutableStateOf<FilePreview?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(path, q) {
        if (q.isNotBlank()) delay(300)
        if (q.length == 1) return@LaunchedEffect
        try {
            entries = api.files(projectId, path, q.takeIf { it.length >= 2 })
            error = null
        } catch (e: ApiException) {
            error = e.message
        }
    }

    Column(Modifier.fillMaxSize()) {
        val shown = preview
        TopBar(shown?.path?.substringAfterLast('/') ?: projectName, onBack = {
            when {
                shown != null -> preview = null
                path.isNotEmpty() -> path = path.substringBeforeLast('/', "")
                else -> nav.back()
            }
        })
        if (shown != null) {
            Column(Modifier.fillMaxSize().padding(Space.s3), verticalArrangement = Arrangement.spacedBy(Space.s2)) {
                Caption("${shown.path} · ${size(shown.size)}${if (shown.truncated) " · first 200 kB shown" else ""}")
                Box(
                    Modifier.weight(1f).fillMaxWidth().clip(RoundedCornerShape(Radius.md)).background(p.panelTop)
                        .border(1.dp, p.border, RoundedCornerShape(Radius.md)).padding(Space.s3),
                ) {
                    if (shown.binary) Caption("This file is not text, so it cannot be shown here.")
                    else LazyColumn {
                        items(shown.text.orEmpty().lines().chunked(200)) { block ->
                            Txt(block.joinToString("\n"), Modifier.horizontalScroll(rememberScrollState()), mono = true, size = 12.sp)
                        }
                    }
                }
            }
            return@Column
        }
        LazyColumn(contentPadding = PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s3)) {
            item { Field(q, { q = it }, placeholder = "Search file names in this project") }
            item { Caption(if (q.length >= 2) "Results for “$q”" else "/" + path, color = p.muted) }
            error?.let { item { Caption(it, color = p.danger) } }
            item {
                Panel(padding = 0.dp) {
                    val list = entries
                    when {
                        list == null -> ListRow { Caption("Loading…") }
                        list.isEmpty() -> ListRow { Caption(if (q.length >= 2) "No file names match." else "This folder is empty.") }
                        else -> Column {
                            list.forEach { entry ->
                                ListRow(onClick = {
                                    if (entry.isDir) {
                                        q = ""
                                        path = entry.path
                                    } else scope.launch {
                                        try {
                                            preview = api.file(projectId, entry.path)
                                        } catch (e: ApiException) {
                                            error = e.message
                                        }
                                    }
                                }) {
                                    LineIcon(if (entry.isDir) "folder" else "file", if (entry.isDir) p.accentBright else p.muted, 18.dp)
                                    Column(Modifier.weight(1f)) {
                                        Txt(entry.name, maxLines = 1)
                                        if (q.length >= 2) Caption(entry.path, maxLines = 1)
                                    }
                                    Caption(if (entry.isDir) "" else size(entry.size))
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
