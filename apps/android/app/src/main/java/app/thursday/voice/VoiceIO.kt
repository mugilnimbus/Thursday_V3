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
import app.thursday.domain.SentenceFeed
import app.thursday.domain.sentences
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

enum class VoiceMode { IDLE, RECORDING, TRANSCRIBING, PLAYING }

/**
 * Voice in and out on the phone, the same way as the dashboard.
 *
 * In: push to talk. The clip is recorded to a temporary file, sent to the PC's speech service through the
 * gateway, deleted, and the text that comes back is sent as a normal message.
 * Out: replies are read aloud when "read replies aloud" is on, one sentence at a time: the first sentence plays
 * while the next is being made, and a reply that is still being written is read as it arrives. A piece that cannot
 * be played says why in the message bar; stopping one that is playing never blocks the ones after it.
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
    private val replies = SpeechQueue(
        scope,
        fetch = ::fetchClip,
        play = { if (it.isNotEmpty()) playClip(it) },
        onError = { error = it },
        allowed = { mode != VoiceMode.RECORDING && mode != VoiceMode.TRANSCRIBING && speakReplies }, // not once the user starts talking
        onIdle = { if (mode == VoiceMode.PLAYING) mode = VoiceMode.IDLE },
    )
    private val feeds = HashMap<String, SentenceFeed>() // replies being read while they are still written

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
        warm()
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

    /**
     * The microphone was pressed: the PC starts loading what the turn needs while you are still talking.
     * Models that were unloaded after a break would otherwise make the first turn wait.
     */
    private fun warm() {
        scope.launch { runCatching { api.warmSpeech(speakReplies) } }
    }

    /** A message was sent and its reply will be read aloud: the PC loads the voice while the reply is written. */
    fun warmVoice() {
        if (speakReplies && available) scope.launch { runCatching { api.warmSpeech(speak = true, listen = false) } }
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

    /** Read a whole reply aloud, sentence by sentence, behind anything still playing. Nothing unless the setting is on. */
    fun say(text: String) {
        if (!speakReplies || text.isBlank()) return
        if (!available) {
            // The speech service may have started after this screen did: look again once before giving up.
            scope.launch {
                refresh()
                if (available) sentences(text).forEach(replies::add)
            }
            return
        }
        sentences(text).forEach(replies::add)
    }

    /** Read a reply aloud while it is still being written: call with each new part of its text. */
    fun sayPart(replyId: String, part: String) {
        if (!speakReplies || !available) return
        feeds.getOrPut(replyId) { SentenceFeed() }.push(part).forEach(replies::add)
    }

    /** The reply is complete: read what is left of it. False when none of it came through [sayPart]. */
    fun sayEnd(replyId: String): Boolean {
        val feed = feeds.remove(replyId) ?: return false
        feed.flush().forEach(replies::add)
        return true
    }

    /** Stop the reply that is playing and drop the ones waiting. Cancelling the reader is what releases the player. */
    fun stopSpeaking() {
        feeds.clear()
        replies.stop()
        runCatching { player?.stop() }
        runCatching { player?.release() }
        player = null
        if (mode == VoiceMode.PLAYING) mode = VoiceMode.IDLE
    }

    /** The audio of one piece. Empty when there is nothing in it a voice can say, which is not an error. */
    private suspend fun fetchClip(text: String): ByteArray = try {
        api.speak(text)
    } catch (e: ApiException) {
        if (e.status == 422) ByteArray(0) else throw e
    }

    /** Write the audio to a temporary file, play it to the end, and delete it however that ends. */
    private suspend fun playClip(wav: ByteArray) {
        val file = File(context.cacheDir, "reply.wav")
        try {
            withContext(Dispatchers.IO) { file.writeBytes(wav) }
            play(file)
        } finally {
            withContext(NonCancellable + Dispatchers.IO) { file.delete() }
        }
    }

    /** Play one clip to the end. Throws when the phone cannot play it, so the reason reaches the message bar. */
    private suspend fun play(file: File) = suspendCancellableCoroutine { cont ->
        val p = MediaPlayer()
        player = p
        // Between two sentences of one reply the voice is still speaking: the queue says when nothing is left.
        fun done(failure: Exception? = null) {
            runCatching { p.release() }
            if (player === p) player = null
            if (cont.isActive) if (failure == null) cont.resume(Unit) else cont.resumeWithException(failure)
        }
        try {
            // Media volume, the one the volume keys change, so the reply is as loud as everything else on the phone.
            p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            p.setDataSource(file.absolutePath)
            p.setOnCompletionListener { done() }
            p.setOnErrorListener { _, what, extra -> done(IOException("the phone could not play the audio (error $what, $extra)")); true }
            p.prepare()
            mode = VoiceMode.PLAYING
            p.start()
        } catch (e: Exception) {
            done(e)
        }
        cont.invokeOnCancellation { done() }
    }

    private companion object {
        const val MAX_RECORD_MS = 120_000
    }
}
