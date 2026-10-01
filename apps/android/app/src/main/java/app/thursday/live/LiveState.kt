package app.thursday.live

import app.thursday.data.ApiException
import app.thursday.data.Approval
import app.thursday.data.Banner
import app.thursday.data.Chat
import app.thursday.data.GatewayApi
import app.thursday.data.Project
import app.thursday.data.Status
import app.thursday.data.StreamMessage
import app.thursday.data.TaskRow
import app.thursday.domain.epochMillis
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * App-wide state mirrored from the gateway: projects and chats, pending approvals, running tasks, and
 * service status. Screens read it; the live stream keeps it fresh; notifications are raised from it.
 */
class LiveState(
    private val api: GatewayApi,
    val stream: StreamClient,
    private val notifier: Notifier,
    private val scope: CoroutineScope,
) {
    val projects = MutableStateFlow<List<Project>>(emptyList())
    val chats = MutableStateFlow<Map<String, List<Chat>>>(emptyMap())
    val approvals = MutableStateFlow<List<Approval>>(emptyList())
    val running = MutableStateFlow<List<TaskRow>>(emptyList())
    val status = MutableStateFlow<Status?>(null)
    val banners = MutableStateFlow<List<Banner>>(emptyList())
    val loaded = MutableStateFlow(false)
    val error = MutableStateFlow<String?>(null)
    private val _toasts = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val toasts: SharedFlow<String> = _toasts

    @Volatile var appVisible = false
    @Volatile var openChatId: String? = null
    private var jobs = listOf<Job>()
    private var streamStarted = false

    fun start() {
        if (jobs.isNotEmpty()) {
            stream.nudge()
            return
        }
        jobs = listOf(
            scope.launch { stream.messages.collect(::onStream) },
            scope.launch {
                // Status every 15 s; the first one gives the stream position to join at.
                while (isActive) {
                    refreshStatus()
                    delay(15_000)
                }
            },
            scope.launch {
                while (isActive) {
                    refreshTasks()
                    delay(30_000)
                }
            },
        )
    }

    fun stop() {
        jobs.forEach { it.cancel() }
        jobs = emptyList()
        stream.stop()
        streamStarted = false
    }

    fun toast(text: String) {
        _toasts.tryEmit(text)
    }

    suspend fun refreshStatus() {
        try {
            val s = api.status()
            status.value = s
            banners.value = s.banners
            error.value = null
            if (!streamStarted) {
                streamStarted = true
                stream.start(maxOf(stream.lastPos, s.streamPos))
                refreshProjects()
            }
        } catch (e: ApiException) {
            if (!loaded.value) error.value = e.message
        }
    }

    /** Reload everything the screens show. Used by the refresh button and when the app comes back. */
    suspend fun refreshAll() {
        refreshStatus()
        refreshProjects()
        refreshTasks()
        stream.nudge()
    }

    suspend fun createProject(name: String, folder: String): Project {
        val project = api.createProject(name, folder)
        refreshProjects()
        return project
    }

    suspend fun refreshProjects() {
        try {
            val list = api.projects()
            val byProject = list.associate { it.id to api.chats(it.id) }
            projects.value = list
            chats.value = byProject
            loaded.value = true
        } catch (e: ApiException) {
            error.value = e.message
        }
    }

    suspend fun refreshTasks() {
        runCatching {
            running.value = api.tasks("running", null)
            approvals.value = api.approvals()
        }
    }

    fun chat(chatId: String): Pair<Project, Chat>? {
        for (p in projects.value) chats.value[p.id]?.firstOrNull { it.id == chatId }?.let { return p to it }
        return null
    }

    /** "warn" when waiting for approval, "run" while a task works, else "". */
    fun dot(chatId: String): String = when {
        approvals.value.any { it.chatId == chatId } -> "warn"
        running.value.any { it.chatId == chatId && it.state == "input_required" } -> "warn"
        running.value.any { it.chatId == chatId } -> "run"
        else -> ""
    }

    suspend fun answer(approval: Approval, decision: String): String? = try {
        api.answer(approval.id, decision)
        approvals.update { list -> list.filter { it.id != approval.id } }
        notifier.cancelApproval(approval.id)
        null
    } catch (e: ApiException) {
        if (e.status == 409) {
            refreshTasks()
            "This approval was already answered or has expired."
        } else e.message
    }

    suspend fun control(taskId: String, action: String): String? = try {
        api.control(taskId, action)
        null
    } catch (e: ApiException) {
        e.message
    } finally {
        refreshTasks()
    }

    suspend fun createChat(projectId: String): Chat {
        val chat = api.createChat(projectId)
        chats.update { it + (projectId to listOf(chat) + (it[projectId] ?: emptyList())) }
        return chat
    }

    suspend fun renameChat(chatId: String, title: String) {
        api.renameChat(chatId, title)
        chats.update { all -> all.mapValues { (_, list) -> list.map { if (it.id == chatId) it.copy(title = title) else it } } }
    }

    suspend fun deleteChat(chatId: String) {
        api.deleteChat(chatId)
        chats.update { all -> all.mapValues { (_, list) -> list.filter { it.id != chatId } } }
        approvals.update { list -> list.filter { it.chatId != chatId } }
    }

    private fun onStream(message: StreamMessage) {
        when (message) {
            is StreamMessage.Banners -> banners.value = message.banners
            is StreamMessage.CatalogChanged -> scope.launch { refreshProjects() } // made or removed on another device
            is StreamMessage.Stored -> onEvent(message)
            else -> Unit
        }
    }

    private fun onEvent(message: StreamMessage.Stored) {
        val e = message.event
        val fresh = System.currentTimeMillis() - epochMillis(e.ts) < 5 * 60_000 // replays after a gap do not re-notify
        val lookingAtIt = appVisible && openChatId == e.chatId
        when (message.kind) {
            "approval_requested" -> {
                scope.launch { refreshTasks() }
                val id = e.payload["approval_id"]?.toString() ?: return
                if (fresh && !lookingAtIt) notifier.approval(id, e.chatId, e.payload["summary"]?.toString() ?: "A task needs your approval")
            }
            "approval_resolved" -> {
                scope.launch { refreshTasks() }
                e.payload["approval_id"]?.toString()?.let(notifier::cancelApproval)
            }
            "task_state" -> scope.launch { refreshTasks() }
            "notification" -> if (fresh && !lookingAtIt) {
                val title = e.payload["title"]?.toString() ?: "Thursday"
                notifier.task(e.taskId ?: e.pos.toString(), e.chatId, title, e.payload["body"]?.toString() ?: "")
            }
            "timeline_event" -> if (e.type == "user_message" || e.type == "assistant_message") {
                val chatId = e.chatId ?: return
                if (chat(chatId) == null) scope.launch { refreshProjects() } // made on another device
                else chats.update { all -> all.mapValues { (_, list) -> list.map { if (it.id == chatId) it.copy(lastActivity = e.ts) else it } } }
            }
        }
    }
}
