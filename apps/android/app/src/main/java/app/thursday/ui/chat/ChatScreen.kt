package app.thursday.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.data.ChatMessage
import app.thursday.graph
import app.thursday.ui.Nav
import app.thursday.ui.Screen
import app.thursday.ui.clock
import app.thursday.ui.common.BannerRow
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Look
import app.thursday.ui.common.MarkdownText
import app.thursday.ui.common.TopBar
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.voice.VoiceMode
import kotlinx.coroutines.launch

@Composable
fun ChatScreen(activity: MainActivity, nav: Nav, chatId: String) {
    val graph = activity.graph
    val live = graph.live
    val p = LocalPalette.current
    val session = remember(chatId) { ChatSession(chatId, graph.api, graph.stream, graph.scope) }
    DisposableEffect(chatId) {
        live.openChatId = chatId
        session.onReply = { graph.voice.say(it) }
        onDispose {
            graph.voice.cancelRecording()
            graph.voice.stopSpeaking()
            session.dispose()
            if (live.openChatId == chatId) live.openChatId = null
        }
    }
    LaunchedEffect(chatId) {
        graph.voice.refresh()
        session.load()
    }

    val chats by live.chats.collectAsStateWithLifecycle()
    val approvalsAll by live.approvals.collectAsStateWithLifecycle()
    val banners by live.banners.collectAsStateWithLifecycle()
    val status by live.status.collectAsStateWithLifecycle()
    val found = remember(chats, chatId) { live.chat(chatId) }
    val approvals = approvalsAll.filter { it.chatId == chatId }
    val tasks = session.tasks.value
    val active = tasks.values.lastOrNull { !it.terminal }
    val items = session.items.value
    val listState = rememberLazyListState()
    val count = items.size + session.outgoing.size + session.replies.size + approvals.size
    LaunchedEffect(count, session.replies.values.sumOf { it.length }) {
        if (count > 0) listState.animateScrollToItem(count + 1)
    }

    Column(Modifier.fillMaxSize()) {
        TopBar(found?.second?.title ?: "Chat", onBack = { nav.back() }) {
            if (active != null) TaskControls(activity, active)
        }
        // The particles follow the microphone while you talk, and move while a reply is read aloud.
        val field = when (graph.voice.mode) {
            VoiceMode.RECORDING -> Voice.LISTENING
            VoiceMode.PLAYING -> Voice.SPEAKING
            VoiceMode.TRANSCRIBING -> Voice.THINKING
            VoiceMode.IDLE -> session.voice.value
        }
        // The particle field fills the area behind the list: a line along the bottom, and a face while the voice agent thinks or speaks.
        Box(Modifier.weight(1f).fillMaxWidth()) {
        VoiceField(field, graph.voice.level, showFace = remember { graph.prefs.faceAnimation })
        LazyColumn(
            Modifier.fillMaxSize(),
            state = listState,
            // Room below the last message equal to the particle field, so it can be scrolled clear of it.
            contentPadding = PaddingValues(start = Space.s3, end = Space.s3, top = Space.s3, bottom = 80.dp),
            verticalArrangement = Arrangement.spacedBy(Space.s3),
        ) {
            items(banners, key = { "b" + it.code }) { BannerRow(it.text) }
            if (session.loading.value) item { Caption("Loading…") }
            session.error.value?.let { item { Caption(it, color = p.danger) } }
            if (!session.loading.value && items.isEmpty() && session.outgoing.isEmpty()) item {
                Caption("Start with what you want done. For example: “List the files in this project and tell me what it is.”")
            }
            items(items, key = { it.key }) { item ->
                when (item) {
                    is ThreadItem.Message -> Bubble(item.message)
                    is ThreadItem.Task -> Column(verticalArrangement = Arrangement.spacedBy(Space.s3)) {
                        TaskCard(item.task, onTrace = { nav.push(Screen.Trace(item.task.taskId)) })
                        approvals.filter { it.taskId == item.task.taskId }.forEach { ApprovalCard(activity, it, found?.first?.name ?: "this project", item.task.instruction) }
                    }
                }
            }
            items(approvals.filter { a -> tasks.values.none { it.taskId == a.taskId } }, key = { "a" + it.id }) {
                ApprovalCard(activity, it, found?.first?.name ?: "this project", "")
            }
            items(session.outgoing, key = { "o" + it.clientMessageId }) { out ->
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
                    BubbleBox(user = true) {
                        Txt(out.text)
                        Caption(outgoingMeta(out, status?.voiceAgent == false))
                    }
                    if (out.status == "unsent" || out.status == "failed") Btn("Retry", { session.retry(out.clientMessageId) }, small = true, modifier = Modifier.padding(top = 4.dp))
                }
            }
            items(session.replies.entries.toList(), key = { "r" + it.key }) { (_, text) ->
                BubbleBox(user = false) {
                    MarkdownText(text)
                    Caption("Voice agent · replying")
                }
            }
            if (session.voice.value == Voice.THINKING && session.replies.isEmpty()) item { BubbleBox(user = false) { Caption("…") } }
        }
        }
        Telemetry(graph, session)
        Composer(activity, graph.prefs.draft(chatId), onDraft = { graph.prefs.saveDraft(chatId, it) }, onSend = { session.send(it) })
    }
}

private fun outgoingMeta(out: Outgoing, voiceDown: Boolean) = when (out.status) {
    "sending" -> "Sending…"
    "queued" -> if (voiceDown) "Queued · sends when the voice agent is back" else "Queued"
    "delivered" -> "Delivered"
    "unsent" -> "Not sent · cannot reach your PC"
    else -> "Failed · ${out.error.ifEmpty { "the voice agent refused it" }}"
}

@Composable
private fun Bubble(message: ChatMessage) {
    val user = message.role == "user"
    Column(Modifier.fillMaxWidth(), horizontalAlignment = if (user) Alignment.End else Alignment.Start) {
        BubbleBox(user) {
            if (user) Txt(message.text) else MarkdownText(message.text)
            Caption("${if (user) "You" else "Voice agent"} · ${clock(message.createdAt)}")
        }
    }
}

@Composable
fun BubbleBox(user: Boolean, content: @Composable () -> Unit) {
    val p = LocalPalette.current
    Box(
        Modifier.widthIn(max = 340.dp).clip(RoundedCornerShape(Radius.lg))
            .background(if (user) p.accentFill else p.panelTop)
            .border(1.dp, if (user) p.accent else p.border, RoundedCornerShape(Radius.lg))
            .padding(horizontal = Space.s3, vertical = Space.s2),
    ) { Column(verticalArrangement = Arrangement.spacedBy(2.dp)) { content() } }
}

@Composable
private fun TaskControls(activity: MainActivity, task: app.thursday.domain.TaskView) {
    val live = activity.graph.live
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    fun act(action: String) {
        busy = true
        scope.launch {
            live.control(task.taskId, action)?.let(live::toast)
            busy = false
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(Space.s2), verticalAlignment = Alignment.CenterVertically) {
        if (task.pauseState == "paused") Btn("Resume", { act("resume") }, small = true, enabled = !busy)
        else Btn("Pause", { act("pause") }, small = true, enabled = !busy && task.pauseState != "pausing")
        Btn("Stop", { act("stop") }, small = true, look = Look.DANGER, enabled = !busy)
    }
}

@Composable
private fun Telemetry(graph: app.thursday.Graph, session: ChatSession) {
    val p = LocalPalette.current
    var main by remember { mutableStateOf<app.thursday.data.LlmSettings?>(null) }
    var voice by remember { mutableStateOf<app.thursday.data.LlmSettings?>(null) }
    val status by graph.live.status.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) {
        main = runCatching { graph.api.llm("main") }.getOrNull()
        voice = runCatching { graph.api.llm("voice") }.getOrNull()
    }
    val events = session.events.toList()
    val waiting = session.tasks.value.values.any { it.state == "input_required" }
    fun line(agent: String, s: app.thursday.data.LlmSettings?, up: Boolean?): String {
        if (up == false) return "offline"
        if (s == null) return "…"
        val stats = app.thursday.domain.agentStats(events, agent)
        val parts = mutableListOf(s.model.substringAfterLast('/'), if (s.sendsOffPc) "off this PC" else "local")
        if (agent == "main" && waiting) parts += "waiting for you" else stats.tokensPerSecond?.let { parts += "$it tok/s" }
        val ctx = app.thursday.domain.formatContext(s.loadedContext ?: stats.contextLength)
        parts += stats.contextPercent?.let { "context $it% of $ctx" } ?: "context $ctx"
        return parts.joinToString(" · ")
    }
    Txt(
        "Voice ${line("voice", voice, status?.voiceAgent)}  |  Main ${line("main", main, status?.mainAgent)}",
        Modifier.fillMaxWidth().padding(horizontal = Space.s3, vertical = 2.dp),
        color = p.muted, size = 11.sp, align = androidx.compose.ui.text.style.TextAlign.Center,
    )
}
