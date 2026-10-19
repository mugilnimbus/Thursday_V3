package app.thursday.live

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.thursday.graph
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * Foreground service that keeps the live connection while the app is in the background, so approval
 * requests and finished tasks notify with the phone locked. Type `remoteMessaging`: it relays messages
 * from the PC, and unlike `dataSync` it has no daily time limit on Android 15.
 */
class LiveService : Service() {
    private var watch: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val graph = applicationContext.graph
        val notification = graph.notifier.connection("Connecting to your PC…")
        // The `remoteMessaging` type exists from Android 14; before that a foreground service needs no type.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceCompat.startForeground(
                this, Notifier.CONNECTION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING,
            )
        } else {
            startForeground(Notifier.CONNECTION_ID, notification)
        }
        graph.live.start()
        if (watch == null) {
            watch = graph.scope.launch {
                graph.stream.state.collect { state ->
                    val text = when (state) {
                        Connection.LIVE -> "Connected to your PC"
                        Connection.CONNECTING -> "Connecting to your PC…"
                        Connection.OFFLINE -> "PC unreachable, retrying"
                        Connection.REVOKED -> "This phone was removed on the PC"
                    }
                    // Update the same notification in place; calling startForeground again is ignored on some phones.
                    graph.notifier.updateConnection(text)
                }
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        watch?.cancel()
        watch = null
        val graph = applicationContext.graph
        if (!graph.visible) graph.live.stop()
        super.onDestroy()
    }

    companion object {
        fun start(context: Context) {
            runCatching { ContextCompat.startForegroundService(context, Intent(context, LiveService::class.java)) }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, LiveService::class.java))
        }
    }
}
