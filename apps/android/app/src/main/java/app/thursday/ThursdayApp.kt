package app.thursday

import android.app.Application
import android.content.Context
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import app.thursday.data.GatewayApi
import app.thursday.data.TokenStore
import app.thursday.live.Connection
import app.thursday.live.LiveService
import app.thursday.live.LiveState
import app.thursday.live.Notifier
import app.thursday.live.StreamClient
import app.thursday.voice.VoiceIO
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** Per-phone settings that are not secret. */
class Prefs(context: Context) {
    private val prefs = context.getSharedPreferences("prefs", Context.MODE_PRIVATE)
    var stayConnected: Boolean
        get() = prefs.getBoolean("stay_connected", true)
        set(v) = prefs.edit().putBoolean("stay_connected", v).apply()
    var appLock: Boolean
        get() = prefs.getBoolean("app_lock", false)
        set(v) = prefs.edit().putBoolean("app_lock", v).apply()
    var speakReplies: Boolean
        get() = prefs.getBoolean("speak_replies", false)
        set(v) = prefs.edit().putBoolean("speak_replies", v).apply()
    var faceAnimation: Boolean
        get() = prefs.getBoolean("face_animation", true)
        set(v) = prefs.edit().putBoolean("face_animation", v).apply()
    var traceGroup: String
        get() = prefs.getString("trace_group", "chat") ?: "chat"
        set(v) = prefs.edit().putString("trace_group", v).apply()
    var theme: String
        get() = prefs.getString("theme", "black") ?: "black"
        set(v) = prefs.edit().putString("theme", v).apply()
    fun draft(chatId: String): String = prefs.getString("draft.$chatId", "") ?: ""
    fun saveDraft(chatId: String, text: String) = prefs.edit().apply { if (text.isBlank()) remove("draft.$chatId") else putString("draft.$chatId", text) }.apply()
}

/**
 * Composition root: one instance of each piece, created once for the process.
 * The stream runs while the app is visible, and in the background only when "Stay connected" is on
 * (through the foreground [LiveService], so approvals arrive with the phone locked).
 */
class ThursdayApp : Application() {
    lateinit var graph: Graph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = Graph(this)
        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) = graph.foreground(true)
            override fun onStop(owner: LifecycleOwner) = graph.foreground(false)
        })
    }
}

class Graph(private val app: Application) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    val prefs = Prefs(app)
    val tokens = TokenStore(app)
    private val _pairing = MutableStateFlow(tokens.load())
    val pairing: StateFlow<TokenStore.Pairing?> = _pairing
    private val _revoked = MutableStateFlow(false)
    val revoked: StateFlow<Boolean> = _revoked
    val api = GatewayApi(pairing = { _pairing.value }, onUnauthorized = { markRevoked() })
    val stream = StreamClient(api, scope)
    val notifier = Notifier(app)
    val live = LiveState(api, stream, notifier, scope)
    val voice = VoiceIO(app, api, prefs, scope)
    var visible = false
        private set

    init {
        scope.launch { stream.state.collect { if (it == Connection.REVOKED) markRevoked() } }
    }

    fun paired(pairing: TokenStore.Pairing) {
        tokens.save(pairing)
        // A fresh pairing: drop the old "removed" state and restart the live connection with the new token.
        live.stop()
        stream.reset()
        _revoked.value = false
        _pairing.value = pairing
        live.start()
        syncService()
    }

    /** Forget the pairing on this phone (the PC keeps the device until it is revoked there). */
    fun unpair() {
        live.stop()
        stream.reset()
        LiveService.stop(app)
        tokens.clear()
        _pairing.value = null
        _revoked.value = false
    }

    fun foreground(visible: Boolean) {
        this.visible = visible
        live.appVisible = visible
        if (_pairing.value == null) return
        if (visible) {
            live.start()
            scope.launch {
                live.refreshAll() // catch up on anything that changed while the app was away
                voice.refresh()
            }
        } else if (!prefs.stayConnected) {
            live.stop()
        }
        syncService()
    }

    /** The background service runs only while paired, allowed, and not revoked. It is started from the foreground. */
    fun syncService() {
        if (_pairing.value != null && prefs.stayConnected && !_revoked.value) {
            if (visible) LiveService.start(app)
        } else {
            LiveService.stop(app)
        }
    }

    fun markRevoked() {
        _revoked.value = true
        LiveService.stop(app)
    }
}

val Context.graph: Graph get() = (applicationContext as ThursdayApp).graph
