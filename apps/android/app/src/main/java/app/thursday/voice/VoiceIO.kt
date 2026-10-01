package app.thursday.voice

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.MediaRecorder
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.thursday.Prefs
import app.thursday.data.ApiException
import app.thursday.data.GatewayApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.coroutines.resume

enum class VoiceMode { IDLE, RECORDING, TRANSCRIBING, PLAYING }

/**
 * Voice in and out on the phone, the same way as the dashboard.
 *
 * In: push to talk. The clip is recorded to a temporary file, sent to the PC's speech service through the
 * gateway, deleted, and the text that comes back is sent as a normal message.
 * Out: replies are fetched as audio and played when "read replies aloud" is on.
 * No audio is kept on the phone or the PC.
 */
class VoiceIO(private val context: Context, private val api: GatewayApi, private val prefs: Prefs, private val scope: CoroutineScope) {
    var available by mutableStateOf(false)
        private set
    var mode by mutableStateOf(VoiceMode.IDLE)
        private set
    var speakReplies by mutableStateOf(prefs.speakReplies)
        private set
    var error by mutableStateOf<String?>(null)
    /** Microphone loudness from 0 to 1 while recording, for the particle field. */
    var level by mutableFloatStateOf(0f)
        private set

    private var recorder: MediaRecorder? = null
    private var clip: File? = null
    private var meter: Job? = null
    private var player: MediaPlayer? = null
    private val queue = ArrayDeque<String>()
    private var speaking = false

    suspend fun refresh() {
        available = runCatching { api.speechAvailable() }.getOrDefault(false)
    }

    fun setSpeak(on: Boolean) {
        speakReplies = on
        prefs.speakReplies = on
        if (!on) stopSpeaking()
    }

    /* ---------- speech to text ---------- */

    fun startRecording() {
        if (mode == VoiceMode.RECORDING || mode == VoiceMode.TRANSCRIBING) return
        stopSpeaking()
        error = null
        val file = File(context.cacheDir, "clip.m4a")
        try {
            @Suppress("DEPRECATION")
            val r = if (android.os.Build.VERSION.SDK_INT >= 31) MediaRecorder(context) else MediaRecorder()
            r.setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            r.setAudioSamplingRate(16_000)
            r.setAudioChannels(1)
            r.setAudioEncodingBitRate(48_000)
            r.setMaxDuration(MAX_RECORD_MS)
            r.setOutputFile(file.absolutePath)
            r.prepare()
            r.start()
            recorder = r
            clip = file
            mode = VoiceMode.RECORDING
            meter = scope.launch {
                while (isActive) {
                    level = (runCatching { r.maxAmplitude }.getOrDefault(0) / 12_000f).coerceIn(0f, 1f)
                    delay(60)
                }
            }
        } catch (e: Exception) {
            release()
            error = "Could not start the microphone."
        }
    }

    /** Stop recording and return what was said ("" when nothing was heard). */
    suspend fun stopRecording(): String {
        val file = clip
        if (mode != VoiceMode.RECORDING || file == null) return ""
        val stopped = runCatching { recorder?.stop() }.isSuccess // fails when the clip is too short
        release()
        if (!stopped) {
            error = "That was too short. Hold on a little longer while you speak."
            return ""
        }
        mode = VoiceMode.TRANSCRIBING
        return try {
            val audio = withContext(Dispatchers.IO) { file.readBytes() }
            val text = api.transcribe(audio, "audio/mp4").trim()
            if (text.isEmpty()) error = "I did not hear anything. Try again a little closer to the phone."
            text
        } catch (e: ApiException) {
            error = e.message
            ""
        } finally {
            withContext(Dispatchers.IO) { file.delete() }
            mode = VoiceMode.IDLE
        }
    }

    fun cancelRecording() {
        if (mode != VoiceMode.RECORDING) return
        runCatching { recorder?.stop() }
        release()
        clip?.delete()
        mode = VoiceMode.IDLE
    }

    private fun release() {
        meter?.cancel()
        level = 0f
        runCatching { recorder?.release() }
        recorder = null
    }

    /* ---------- text to speech ---------- */

    /** Read a reply aloud, queued behind any reply still playing. Does nothing unless the setting is on. */
    fun say(text: String) {
        if (!speakReplies || !available || text.isBlank()) return
        queue.addLast(text)
        if (!speaking) scope.launch { drain() }
    }

    fun stopSpeaking() {
        queue.clear()
        runCatching { player?.stop() }
        runCatching { player?.release() }
        player = null
        if (mode == VoiceMode.PLAYING) mode = VoiceMode.IDLE
    }

    private suspend fun drain() {
        speaking = true
        while (queue.isNotEmpty()) {
            val text = queue.removeFirst()
            try {
                val wav = api.speak(text)
                if (mode == VoiceMode.RECORDING || mode == VoiceMode.TRANSCRIBING || !speakReplies) continue // the user started talking
                val file = File(context.cacheDir, "reply.wav")
                withContext(Dispatchers.IO) { file.writeBytes(wav) }
                play(file)
                withContext(Dispatchers.IO) { file.delete() }
            } catch (e: ApiException) {
                error = e.message
            }
        }
        speaking = false
    }

    private suspend fun play(file: File) = suspendCancellableCoroutine { cont ->
        val p = MediaPlayer()
        player = p
        fun done() {
            runCatching { p.release() }
            if (player === p) player = null
            if (mode == VoiceMode.PLAYING) mode = VoiceMode.IDLE
            if (cont.isActive) cont.resume(Unit)
        }
        try {
            p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            p.setDataSource(file.absolutePath)
            p.setOnCompletionListener { done() }
            p.setOnErrorListener { _, _, _ -> done(); true }
            p.prepare()
            mode = VoiceMode.PLAYING
            p.start()
        } catch (e: Exception) {
            done()
        }
        cont.invokeOnCancellation { done() }
    }

    private companion object {
        const val MAX_RECORD_MS = 120_000
    }
}
