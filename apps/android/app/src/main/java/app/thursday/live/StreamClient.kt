package app.thursday.live

import app.thursday.data.GatewayApi
import app.thursday.data.Parse
import app.thursday.data.StreamMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import kotlin.math.min
import kotlin.random.Random

enum class Connection { OFFLINE, CONNECTING, LIVE, REVOKED }

/**
 * The one live event stream (`/v1/stream`). Replays from the last position seen, so nothing is missed
 * across reconnects; reconnects with jittered backoff (1 s doubling to 30 s); stops for good when the
 * gateway refuses the device token (close code 1008: this phone was revoked).
 */
class StreamClient(private val api: GatewayApi, private val scope: CoroutineScope) {
    private val _messages = MutableSharedFlow<StreamMessage>(extraBufferCapacity = 256)
    val messages: SharedFlow<StreamMessage> = _messages
    private val _state = MutableStateFlow(Connection.OFFLINE)
    val state: StateFlow<Connection> = _state

    @Volatile var lastPos = 0L
        private set
    private var socket: WebSocket? = null
    private var retry: Job? = null
    private var attempt = 0
    private var running = false

    @Synchronized
    fun start(after: Long) {
        lastPos = maxOf(lastPos, after)
        running = true
        if (_state.value == Connection.REVOKED) return
        connect()
    }

    @Synchronized
    fun stop() {
        running = false
        retry?.cancel()
        socket?.close(1000, null)
        socket = null
        if (_state.value != Connection.REVOKED) _state.value = Connection.OFFLINE
    }

    /** Forget a refused token and the old position: called when this phone is paired again or unpaired. */
    @Synchronized
    fun reset() {
        stop()
        attempt = 0
        lastPos = 0
        _state.value = Connection.OFFLINE
    }

    /** Reconnect now (for example when the network comes back or the app returns to the foreground). */
    @Synchronized
    fun nudge() {
        if (!running || socket != null || _state.value == Connection.REVOKED) return
        retry?.cancel()
        attempt = 0
        connect()
    }

    @Synchronized
    private fun connect() {
        if (!running || socket != null) return
        val request = api.streamRequest(lastPos) ?: return
        _state.value = Connection.CONNECTING
        socket = api.client.newWebSocket(request, Listener())
    }

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            attempt = 0
            _state.value = Connection.LIVE
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val message = runCatching { Parse.stream(JSONObject(text)) }.getOrNull() ?: return
            if (message is StreamMessage.Stored) {
                if (message.event.pos <= lastPos) return // replayed duplicate
                lastPos = message.event.pos
            }
            _messages.tryEmit(message)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code, null)
            closed(webSocket, revoked = code == 1008)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            closed(webSocket, revoked = response?.code == 401 || response?.code == 403)
        }
    }

    private fun closed(webSocket: WebSocket, revoked: Boolean) {
        synchronized(this) {
            if (socket !== webSocket) return
            socket = null
            if (revoked) {
                running = false
                _state.value = Connection.REVOKED
                return
            }
            _state.value = Connection.OFFLINE
            if (!running) return
            attempt += 1
            val base = min(30_000.0, 1000.0 * (1 shl min(attempt - 1, 5)))
            val wait = (base * (0.75 + Random.nextDouble() * 0.5)).toLong()
            retry = scope.launch {
                delay(wait)
                connect()
            }
        }
    }
}
