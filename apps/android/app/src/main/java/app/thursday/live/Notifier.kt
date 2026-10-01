package app.thursday.live

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import app.thursday.MainActivity
import app.thursday.R

/**
 * Notifications: approvals (high importance, open the chat; answering always happens in the app, behind
 * the phone's lock-screen check), finished tasks, and the quiet "connected" notice the live service needs.
 */
class Notifier(private val context: Context) {
    private val manager = NotificationManagerCompat.from(context)

    init {
        val system = context.getSystemService(NotificationManager::class.java)
        system.createNotificationChannels(
            listOf(
                NotificationChannel(APPROVALS, "Approvals", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Thursday needs your yes before a risky step"
                },
                NotificationChannel(TASKS, "Finished tasks", NotificationManager.IMPORTANCE_DEFAULT),
                NotificationChannel(CONNECTION, "Connection", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "Shown while Thursday stays connected in the background"
                    setShowBadge(false)
                },
            ),
        )
    }

    fun connection(text: String): Notification =
        NotificationCompat.Builder(context, CONNECTION)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle("Thursday")
            .setContentText(text)
            .setOngoing(true)
            .setSilent(true)
            .setContentIntent(open(null, 0))
            .build()

    fun updateConnection(text: String) = post(CONNECTION_ID, connection(text))

    fun approval(approvalId: String, chatId: String?, summary: String) = post(
        approvalId.hashCode(),
        NotificationCompat.Builder(context, APPROVALS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle("Approval needed")
            .setContentText(summary)
            .setStyle(NotificationCompat.BigTextStyle().bigText(summary))
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE) // details hidden on the lock screen
            .setAutoCancel(true)
            .setContentIntent(open(chatId, approvalId.hashCode()))
            .build(),
    )

    fun cancelApproval(approvalId: String) = manager.cancel(approvalId.hashCode())

    fun task(taskId: String, chatId: String?, title: String, body: String) = post(
        taskId.hashCode(),
        NotificationCompat.Builder(context, TASKS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setAutoCancel(true)
            .setContentIntent(open(chatId, taskId.hashCode()))
            .build(),
    )

    private fun post(id: Int, notification: Notification) {
        val allowed = ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        if (allowed) manager.notify(id, notification)
    }

    private fun open(chatId: String?, requestCode: Int): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .apply { chatId?.let { putExtra(MainActivity.EXTRA_CHAT, it) } }
        return PendingIntent.getActivity(context, requestCode, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    companion object {
        const val APPROVALS = "approvals"
        const val TASKS = "tasks"
        const val CONNECTION = "connection"
        const val CONNECTION_ID = 1
    }
}
