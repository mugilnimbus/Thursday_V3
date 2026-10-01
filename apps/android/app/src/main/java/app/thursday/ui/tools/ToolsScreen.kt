package app.thursday.ui.tools

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
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
import app.thursday.MainActivity
import app.thursday.data.ApiException
import app.thursday.data.ToolsOverview
import app.thursday.graph
import app.thursday.ui.common.BannerRow
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Chip
import app.thursday.ui.common.Dot
import app.thursday.ui.common.ListBox
import app.thursday.ui.common.ListRow
import app.thursday.ui.common.Look
import app.thursday.ui.common.Panel
import app.thursday.ui.common.TopBar
import app.thursday.ui.common.Txt
import app.thursday.ui.relativeTime
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val GROUPS = listOf(
    Triple(listOf("shell", "shell.session.open", "shell.session.exec", "shell.session.close"), "shell · shell sessions", "Run PowerShell in the project folder"),
    Triple(listOf("fs.delete"), "fs.delete", "Delete files or folders"),
    Triple(listOf("fs.write", "fs.edit", "fs.patch"), "fs.write · fs.edit · fs.patch", "Create and change files"),
    Triple(listOf("fs.read", "fs.list"), "fs.read · fs.list", "Read files and folders"),
)

/** Most important first: what runs without asking (revocable), then tool servers, then built-in tools. */
@Composable
fun ToolsScreen(activity: MainActivity) {
    val api = activity.graph.api
    val live = activity.graph.live
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    var data by remember { mutableStateOf<ToolsOverview?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    LaunchedEffect(reload) {
        while (true) {
            try {
                data = api.tools()
                error = null
            } catch (e: ApiException) {
                error = e.message
            }
            delay(30_000)
        }
    }
    Column(Modifier.fillMaxSize()) {
        TopBar("Tools")
        LazyColumn(contentPadding = PaddingValues(Space.s4), verticalArrangement = Arrangement.spacedBy(Space.s4)) {
            error?.let { item { BannerRow(it) } }
            if (data?.reachable == false) item { BannerRow("The main agent is not running, so rules and tool servers cannot be read right now.") }
            item {
                Panel {
                    Txt("Allowed without asking", weight = FontWeight.SemiBold)
                    Caption("Only inside the chat shown · revoke any time")
                    ListBox {
                        val rules = data?.rules ?: emptyList()
                        if (rules.isEmpty()) ListRow { Caption(if (data == null) "Loading…" else "Nothing. Every risky tool asks first.") }
                        rules.forEach { rule ->
                            ListRow {
                                Column(Modifier.weight(1f)) {
                                    Row(horizontalArrangement = Arrangement.spacedBy(Space.s2), verticalAlignment = Alignment.CenterVertically) {
                                        Txt(rule.tool, mono = true, size = Type.caption, weight = FontWeight.SemiBold)
                                        if (rule.tool.startsWith("shell")) Chip("any command", p.danger)
                                    }
                                    Caption("Chat “${rule.chatTitle}” · since ${relativeTime(rule.createdAt)}")
                                }
                                Btn("Revoke", {
                                    scope.launch {
                                        if (activity.guard.confirm("Revoke ${rule.tool}")) {
                                            runCatching { api.revokeRule(rule.chatId, rule.tool) }
                                                .onSuccess { live.toast("Revoked ${rule.tool} for “${rule.chatTitle}”."); reload++ }
                                                .onFailure { live.toast(it.message ?: "Could not revoke.") }
                                        }
                                    }
                                }, look = Look.DANGER, small = true)
                            }
                        }
                    }
                }
            }
            item {
                Panel {
                    Txt("Tool servers", weight = FontWeight.SemiBold)
                    ListBox {
                        (data?.servers ?: emptyList()).forEach { s ->
                            ListRow {
                                Dot(if (s.alive) "ok" else "")
                                Column(Modifier.weight(1f)) {
                                    Txt(s.projectName)
                                    Caption(if (!s.alive) "Stopped · starts on next use" else "Running" + if (s.openSessions > 0) " · ${s.openSessions} shell session(s) open" else "")
                                }
                            }
                        }
                    }
                    Caption("One tool server per project. A server with an open shell session is never stopped automatically.")
                }
            }
            item {
                Panel {
                    Txt("Built-in tools", weight = FontWeight.SemiBold)
                    ListBox {
                        val catalog = data?.catalog ?: emptyList()
                        GROUPS.map { (names, label, text) ->
                            val found = catalog.filter { it.name in names }
                            Triple(label, text, found.any { it.asksFirst } || (found.isEmpty() && names[0] in setOf("shell", "fs.delete")))
                        }.sortedByDescending { it.third }.forEach { (label, text, asks) ->
                            ListRow {
                                Column(Modifier.weight(1f)) {
                                    Txt(label, mono = true, size = Type.caption, weight = FontWeight.SemiBold)
                                    Caption(text)
                                }
                                Chip(if (asks) "asks first" else "allowed", if (asks) p.warning else p.muted)
                            }
                        }
                    }
                }
            }
        }
    }
}
