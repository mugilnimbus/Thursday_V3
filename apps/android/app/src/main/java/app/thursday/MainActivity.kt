package app.thursday

import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.mutableStateOf
import androidx.fragment.app.FragmentActivity
import app.thursday.security.Guard
import app.thursday.ui.AppRoot

/** The single activity. A FragmentActivity so the system's biometric prompt can attach to it. */
class MainActivity : FragmentActivity() {
    /** A chat to open, from a notification tap. */
    val openChat = mutableStateOf<String?>(null)
    lateinit var guard: Guard
        private set

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        guard = Guard(this)
        openChat.value = intent?.getStringExtra(EXTRA_CHAT)
        setContent { AppRoot(this) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(EXTRA_CHAT)?.let { openChat.value = it }
    }

    companion object {
        const val EXTRA_CHAT = "chat_id"
    }
}
