package app.thursday.ui.chat

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.thursday.MainActivity
import app.thursday.data.ChatMessage
import app.thursday.domain.bubbleMaxDp
import app.thursday.domain.followsNewest
import app.thursday.graph
import app.thursday.ui.Nav
import app.thursday.ui.Screen
import app.thursday.ui.clock
import app.thursday.ui.common.BannerRow
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.CopyButton
import app.thursday.ui.common.Look
import app.thursday.ui.common.MarkdownText
import app.thursday.ui.common.TopBar
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.voice.VoiceMode
import kotlinx.coroutines.launch

/** One chat. `besideList`: it is shown next to the list it was opened from, so it needs no way back. */
@Composable
fun ChatScreen(activity: MainActivity, nav: Nav, chatId: String, besideList: Boolean = false) {
    val graph = activity.graph
    val live = graph.live
    val p = LocalPalette.current
    val session = remember(chatId) { ChatSession(chatId, graph.api, graph.stream, graph.scope) }
    DisposableEffect(chatId) {
        live.openChatId = chatId
        // A reply is read aloud as it is written; one that arrived whole is read once it is stored.
        session.onReplyPart = { id, part -> graph.voice.sayPart(id, part) }
        session.onReply = { text, id -> if (!(id != null && graph.voice.sayEnd(id))) graph.voice.say(text) }
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
    val direct = found?.second?.direct ?: false
    val approvals = approvalsAll.filter { it.chatId == chatId }
    val tasks = session.tasks.value
    val active = tasks.values.lastOrNull { !it.terminal }
    val items = session.items.value
    val listState = rememberLazyListState()
    val count = items.size + session.outgoing.size + session.replies.size + approvals.size
    // The list moves down to new content only while the reader is at its end; someone reading further up stays
    // there. Where the list came to rest decides it, and sending a message returns to the end.
    var follow by remember { mutableStateOf(true) }
    LaunchedEffect(listState) {
        snapshotFlow { listState.isScrollInProgress }.collect { moving -> if (!moving) follow = followsNewest(listState.canScrollForward) }
    }
    LaunchedEffect(session.outgoing.size) { if (session.outgoing.isNotEmpty()) follow = true }
    LaunchedEffect(count, session.replies.values.sumOf { it.length }) {
        if (count > 0 && follow) listState.animateScrollToItem(count + 1)
    }

    Column(Modifier.fillMaxSize()) {
        TopBar(found?.second?.title ?: "Chat", onBack = if (besideList) null else ({ nav.back() })) {
            if (active != null) TaskControls(activity, active)
        }
        // The particles follow the microphone while you talk, and move while a reply is read aloud.
        val field = when (graph.voice.mode) {
            VoiceMode.RECORDING -> Voice.LISTENING
            VoiceMode.PLAYING -> Voice.SPEAKING
            VoiceMode.TRANSCRIBING -> Voice.THINKING
            VoiceMode.IDLE -> session.voice.value
        }
        // The particle field covers everything below the title, in two see-through layers: the face behind the
        // messages, and the particle line over them. The status line rests on the message box, and the particle line
        // is lifted to run there. Nothing here has a backing of its own but the messages: they scroll on behind the
        // particles, the status line and the message box, which are all see-through, down to the bottom.
        val scope = rememberCoroutineScope()
        var statusPx by remember { mutableIntStateOf(0) }
        var boxPx by remember { mutableIntStateOf(0) }
        val density = LocalDensity.current
        BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
        val lineCentre = if (statusPx > 0) boxPx + statusPx / 2f else null
        val bubbleMax = bubbleMaxDp((maxWidth - Space.s3 * 2).value).dp
        VoiceField(field, graph.voice.level, showFace = remember { graph.prefs.faceAnimation }, lineCentre = lineCentre, parts = FieldParts.FACE)
        CompositionLocalProvider(
            LocalMessageSolid provides remember { solidFor(graph.prefs.messageTransparency) },
            LocalBubbleMax provides bubbleMax,
        ) {
        LazyColumn(
            Modifier.fillMaxSize(),
            state = listState,
            // Room below the last message, so it can be scrolled clear of the particle line, the status line and the
            // message box.
            contentPadding = PaddingValues(start = Space.s3, end = Space.s3, top = Space.s3, bottom = with(density) { (boxPx + statusPx).toDp() } + LINE_BAND / 2),
            verticalArrangement = Arrangement.spacedBy(Space.s3),
        ) {
            items(banners, key = { "b" + it.code }) { BannerRow(it.text) }
            if (session.loading.value) item { Caption("Loading…") }
            if (session.hasEarlier.value && !session.loading.value) item(key = "earlier") {
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Btn("Earlier messages", {
                        scope.launch {
                            // The message that was at the top stays where it is; the older ones go in above it.
                            val index = listState.firstVisibleItemIndex
                            val offset = listState.firstVisibleItemScrollOffset
                            val added = session.loadEarlier()
                            if (added > 0) listState.scrollToItem(index + added, offset)
                        }
                    }, look = Look.PLAIN, small = true)
                }
            }
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
                        Meta(outgoingMeta(out, status?.voiceAgent == false) + if (out.direct && out.status != "failed" && out.status != "unsent") " · direct" else "", out.text)
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
        if (!follow) Btn(
            "Newest ↓",
            { follow = true; scope.launch { listState.animateScrollToItem(count + 1) } },
            small = true,
            modifier = Modifier.align(Alignment.BottomEnd).padding(end = Space.s3, bottom = with(density) { (boxPx + statusPx).toDp() } + Space.s2),
        )
        // Over the messages, and letting them show through: the particle line. It takes no touches.
        VoiceField(field, graph.voice.level, lineCentre = lineCentre, parts = FieldParts.LINE)
        Column(Modifier.align(Alignment.BottomCenter)) {
        Box(Modifier.onSizeChanged { statusPx = it.height }) { Telemetry(graph, session) }
        Box(Modifier.onSizeChanged { boxPx = it.height }) {
            Composer(
                activity, graph.prefs.draft(chatId), direct,
                onDraft = { graph.prefs.saveDraft(chatId, it) },
                onSend = {
                    graph.voice.warmVoice()
                    session.send(it)
                },
                onDirect = { on -> scope.launch { live.setChatDirect(chatId, on)?.let(live::toast) } },
            )
        }
        }
        }
    }
}

private fun outgoingMeta(out: Outgoing, voiceDown: Boolean) = when (out.status) {
    "sending" -> "Sending…"
    "queued" -> if (voiceDown) "Queued · sends when the voice agent is back" else "Queued"
    "delivered" -> "Delivered"
    "unsent" -> "Not sent · cannot reach your PC"
    else -> "Failed · ${out.error.ifEmpty { if (out.direct) "the main agent refused it" else "the voice agent refused it" }}"
}

@Composable
private fun Bubble(message: ChatMessage) {
    val user = message.role == "user"
    Column(Modifier.fillMaxWidth(), horizontalAlignment = if (user) Alignment.End else Alignment.Start) {
        BubbleBox(user) {
            if (user) Txt(message.text) else MarkdownText(message.text)
            Meta("${if (user) (if (message.direct) "You · direct" else "You") else "Voice agent"} · ${clock(message.createdAt)}", message.text)
        }
    }
}

/** The small line under a message: who and when, and a button that copies the message. */
@Composable
private fun Meta(line: String, copies: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Caption(line, Modifier.weight(1f, fill = false))
        CopyButton(copies)
    }
}

@Composable
fun BubbleBox(user: Boolean, content: @Composable () -> Unit) {
    val p = LocalPalette.current
    Box(
        Modifier.widthIn(max = LocalBubbleMax.current).clip(RoundedCornerShape(Radius.lg))
            .plate(p.bg, LocalMessageSolid.current, if (user) p.accentFill else p.panelTop)
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
    fun line(agent: String, s: app.thursday.data.LlmSettings?, up: Boolean?): String {
        if (up == false) return "offline"
        if (s == null) return "…"
        val stats = app.thursday.domain.agentStats(events, agent)
        val parts = listOfNotNull(
            stats.tokensPerSecond?.let { "$it tok/s" },
            app.thursday.domain.contextText(stats.contextTokens, s.loadedContext ?: stats.contextLength).ifEmpty { null },
            "sends data off this PC".takeIf { s.sendsOffPc },
        )
        return parts.joinToString("\u00A0·\u00A0").ifEmpty { "ready" }.replace(' ', '\u00A0')
    }
    // One line, "Voice 107 tok/s · 1275/8192 · Main 74 tok/s · 2345/65536", resting on the message box with nothing
    // behind it but the particle line. If it is ever too long for the screen it breaks between the two agents,
    // never inside one.
    Text(
        "Voice\u00A0${line("voice", voice, status?.voiceAgent)} · Main\u00A0${line("main", main, status?.mainAgent)}",
        Modifier.fillMaxWidth().padding(horizontal = Space.s3),
        color = p.muted, fontSize = STATUS_TEXT, lineHeight = STATUS_TEXT * 1.4f, textAlign = TextAlign.Center, maxLines = 2,
        overflow = TextOverflow.Ellipsis,
        style = TextStyle(shadow = Shadow(p.bg, blurRadius = 10f)), // keeps the letters readable over bright particles
    )
}

/* The particle line lives in a band this tall (see `fieldLayout`), with its middle on the status line. */
private val LINE_BAND = 72.dp
private val STATUS_TEXT = 11.sp
