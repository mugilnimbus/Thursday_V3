package app.thursday.ui.chat

import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import app.thursday.data.ApiException
import app.thursday.data.ChatMessage
import app.thursday.data.GatewayApi
import app.thursday.data.StreamMessage
import app.thursday.domain.Event
import app.thursday.domain.MESSAGE_PAGE
import app.thursday.domain.TaskView
import app.thursday.domain.buildTasks
import app.thursday.domain.messagesOnlyInEvents
import app.thursday.live.StreamClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID

enum class Voice { IDLE, LISTENING, THINKING, SPEAKING }

/** `direct`: sent straight to the main agent, so no voice reply streams back and the voice agent is not shown as thinking. */
data class Outgoing(val clientMessageId: String, val text: String, val status: String, val error: String, val direct: Boolean = false)

sealed interface ThreadItem {
    val key: String
    val pos: Double
    data class Message(val message: ChatMessage) : ThreadItem {
        override val key get() = "m${message.id}"
        override val pos get() = (message.pos ?: 0L).toDouble()
    }
    data class Task(val task: TaskView, override val pos: Double) : ThreadItem {
        override val key get() = "t${task.taskId}"
    }
}

/**
 * One open chat: stored messages and task events over REST, everything newer from the live stream,
 * merged by event position so nothing shows twice. Mirrors the dashboard's ChatSession.
 */
class ChatSession(val chatId: String, private val api: GatewayApi, private val stream: StreamClient, private val scope: CoroutineScope) {
    val messages = mutableStateListOf<ChatMessage>()
    val events = mutableStateListOf<Event>()
    val outgoing = mutableStateListOf<Outgoing>()
    val replies = mutableStateMapOf<String, String>()
    val loading = mutableStateOf(true)
    val error = mutableStateOf<String?>(null)

    /** There may be messages older than the ones shown. */
    val hasEarlier = mutableStateOf(false)
    val voice = mutableStateOf(Voice.IDLE)
    val tasks = derivedStateOf { buildTasks(events) }
    val items = derivedStateOf { buildItems() }

    /** Called for each new reply from the voice agent once it is stored, with its text and the id it was streamed under. */
    var onReply: ((String, String?) -> Unit)? = null

    /** Called with each part of a reply while it is still being written (used to read it aloud as it arrives). */
    var onReplyPart: ((String, String) -> Unit)? = null

    private val seen = HashSet<Long>()
    private var lastEventPos = 0L
    private var buffered: MutableList<StreamMessage>? = mutableListOf()
    private var settle: Job? = null
    private val listener: Job = scope.launch {
        stream.messages.collect { m -> buffered?.add(m) ?: onStream(m) }
    }

    fun dispose() {
        listener.cancel()
        settle?.cancel()
    }

    suspend fun load() {
        loading.value = true
        error.value = null
        try {
            val (history, pending) = api.messages(chatId)
            val all = mutableListOf<Event>()
            var last = lastEventPos
            while (true) {
                val page = api.timeline(chatId, last)
                all += page
                page.lastOrNull()?.let { last = maxOf(last, it.pos) }
                if (page.size < 1000) break
            }
            // Only now: a load that failed half-way starts again from where it began, and loses nothing.
            lastEventPos = last
            messages.clear()
            seen.clear()
            messages.addAll(history)
            history.forEach { m -> m.pos?.let(seen::add) }
            hasEarlier.value = history.size >= MESSAGE_PAGE
            outgoing.clear()
            outgoing.addAll(pending.filter { it.status != "delivered" }.map { Outgoing(it.clientMessageId, it.text, it.status, it.error, it.direct) })
            events.addAll(all)
            messagesOnlyInEvents(history.map { it.pos }, all).forEach(::addMessage)
            val held = buffered ?: mutableListOf()
            buffered = null
            held.forEach(::onStream)
        } catch (e: ApiException) {
            error.value = e.message
        } finally {
            loading.value = false
        }
    }

    /** Fetch the page of messages before the oldest one shown. Returns how many were added above it. */
    suspend fun loadEarlier(): Int {
        val first = messages.firstOrNull() ?: return 0
        return try {
            val (older, _) = api.messages(chatId, before = first.id)
            older.forEach { m -> m.pos?.let(seen::add) }
            messages.addAll(0, older)
            hasEarlier.value = older.size >= MESSAGE_PAGE
            older.size
        } catch (e: ApiException) {
            error.value = e.message
            0
        }
    }

    fun send(text: String) {
        val entry = Outgoing(UUID.randomUUID().toString(), text, "sending", "")
        outgoing.add(entry)
        post(entry.clientMessageId)
    }

    fun retry(clientMessageId: String) = post(clientMessageId)

    private fun post(clientMessageId: String) {
        val index = outgoing.indexOfFirst { it.clientMessageId == clientMessageId }
        if (index < 0) return
        val entry = outgoing[index]
        outgoing[index] = entry.copy(status = "sending", error = "")
        scope.launch {
            try {
                val result = api.send(chatId, clientMessageId, entry.text)
                val direct = result.optBoolean("direct")
                update(clientMessageId) { it.copy(direct = direct, status = if (it.status == "sending") result.optString("status", "queued") else it.status) }
                if (!direct) voice.value = Voice.THINKING
            } catch (e: ApiException) {
                val status = if (!e.offline && e.status in 400..499) "failed" else "unsent"
                update(clientMessageId) { it.copy(status = status, error = e.message ?: "") }
            }
        }
    }

    private fun update(id: String, change: (Outgoing) -> Outgoing) {
        val i = outgoing.indexOfFirst { it.clientMessageId == id }
        if (i >= 0) outgoing[i] = change(outgoing[i])
    }

    private fun onStream(message: StreamMessage) {
        when (message) {
            is StreamMessage.Delta -> if (message.chatId == chatId) {
                replies[message.clientMessageId] = (replies[message.clientMessageId] ?: "") + message.text
                onReplyPart?.invoke(message.clientMessageId, message.text)
                voice.value = Voice.SPEAKING
                settleSoon()
            }
            is StreamMessage.Outgoing -> if (message.chatId == chatId) onOutgoing(message)
            is StreamMessage.Stored -> {
                val e = message.event
                if (e.chatId != chatId || e.pos <= lastEventPos) return
                lastEventPos = e.pos
                events.add(e)
                if (e.type == "user_message" || e.type == "assistant_message") addMessage(e)
            }
            is StreamMessage.Banners, StreamMessage.CatalogChanged -> Unit
        }
    }

    private fun onOutgoing(m: StreamMessage.Outgoing) {
        if (outgoing.none { it.clientMessageId == m.clientMessageId }) {
            if (m.status == "queued" && m.text != null) outgoing.add(Outgoing(m.clientMessageId, m.text, "queued", "", m.direct)) // sent from another device
            return
        }
        update(m.clientMessageId) { it.copy(status = m.status, error = m.error ?: "") }
        if (m.status == "failed") {
            replies.remove(m.clientMessageId)
            voice.value = Voice.IDLE
        }
        if (m.status == "delivered") settleSoon()
    }

    private fun addMessage(e: Event) {
        if (!seen.add(e.pos)) return
        val clientId = e.payload["client_message_id"] as? String
        messages.add(
            ChatMessage(
                e.pos, e.pos, if (e.type == "user_message") "user" else "assistant", e.payload["text"]?.toString() ?: "", e.ts, clientId,
                direct = e.type == "user_message" && e.payload["direct"] == true,
            ),
        )
        if (e.type == "assistant_message" && System.currentTimeMillis() - app.thursday.domain.epochMillis(e.ts) < 60_000) onReply?.invoke(e.payload["text"]?.toString() ?: "", clientId)
        if (clientId == null) return
        if (e.type == "user_message") outgoing.removeAll { it.clientMessageId == clientId } else {
            replies.remove(clientId)
            settleSoon()
        }
    }

    private fun settleSoon() {
        settle?.cancel()
        settle = scope.launch {
            delay(1200)
            val sending = outgoing.any { it.status == "sending" || it.status == "queued" }
            voice.value = if (sending && replies.isEmpty()) Voice.THINKING else Voice.IDLE
        }
    }

    private fun buildItems(): List<ThreadItem> {
        val items = messages.map { ThreadItem.Message(it) }.toMutableList<ThreadItem>()
        val byPos = messages.sortedBy { it.pos ?: 0L }
        for (task in tasks.value.values) {
            // A task card sits under the reply that announced it, else where the task began.
            val next = byPos.firstOrNull { (it.pos ?: 0L) > task.firstPos }
            // A task sent straight to the main agent goes right after the user's message, where the voice agent announced it
            // (the main agent announces it earlier, before that message is stored).
            val pos = task.directPos?.toDouble() ?: if (next?.role == "assistant") (next.pos ?: 0L) + 0.5 else task.firstPos.toDouble()
            items += ThreadItem.Task(task, pos)
        }
        return items.sortedBy { it.pos }
    }
}
