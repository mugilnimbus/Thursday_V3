package app.thursday.voice

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.launch

/**
 * Pieces of replies waiting to be read aloud, one at a time and in order.
 *
 * A reply is read sentence by sentence, so the first sound comes after the first sentence is made, not after the
 * whole reply. While one piece plays, the audio of the next is already being fetched, so there is no gap.
 *
 * The reader is a coroutine, so stopping is just cancelling it: whatever is fetching or playing is cancelled with it,
 * and the next piece starts a fresh reader. (An earlier version kept a "speaking" flag that a stop during playback
 * never cleared, which silenced every later reply until the app restarted.) A piece that cannot be fetched or played
 * is reported and skipped; it never stops the pieces behind it.
 *
 * Kept free of Android classes so it can be unit tested: [fetch] gets the audio, [play] plays it until it ends.
 */
class SpeechQueue(
    private val scope: CoroutineScope,
    private val fetch: suspend (String) -> ByteArray,
    private val play: suspend (ByteArray) -> Unit,
    private val onError: (String) -> Unit,
    /** False when a fetched piece should not be played after all (the user started talking). */
    private val allowed: () -> Boolean = { true },
    /** Everything waiting has been read. Not called when the queue is stopped. */
    private val onIdle: () -> Unit = {},
) {
    private class Piece(val text: String) {
        var audio: Deferred<Result<ByteArray>>? = null
    }

    private val lock = Any()
    private val waiting = ArrayDeque<Piece>()
    private var reader: Job? = null

    fun add(text: String) {
        synchronized(lock) {
            waiting.addLast(Piece(text))
            prepare()
            if (reader?.isActive != true) {
                // Started only once it is known as the reader: on an immediate dispatcher it runs right here.
                val job = scope.launch(start = CoroutineStart.LAZY) { readAll() }
                reader = job
                job.start()
            }
        }
    }

    /** Drop the waiting pieces and stop the one being fetched or played. */
    fun stop() {
        synchronized(lock) {
            waiting.forEach { it.audio?.cancel() }
            waiting.clear()
            reader?.cancel()
            reader = null
        }
    }

    /** Have the audio of the piece that plays next, and of the one after it, on its way. Call with the lock held. */
    private fun prepare() {
        for (piece in waiting.take(2)) {
            if (piece.audio == null) piece.audio = scope.async {
                try {
                    Result.success(fetch(piece.text))
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    Result.failure(e)
                }
            }
        }
    }

    private suspend fun readAll() {
        val me = currentCoroutineContext()[Job]
        while (true) {
            val piece = synchronized(lock) {
                if (reader !== me) return // stopped: the queue belongs to whoever reads next
                prepare()
                // Giving up the queue under the lock means a piece added a moment later starts a new reader.
                waiting.firstOrNull().also { if (it == null) reader = null }
            }
            if (piece == null) {
                onIdle()
                return
            }
            val audio = piece.audio!!.await()
            synchronized(lock) {
                if (waiting.firstOrNull() !== piece) return // stopped while this piece was being made
                waiting.removeFirst()
                prepare() // the piece after this one is made while this one plays
            }
            try {
                val bytes = audio.getOrThrow()
                if (allowed()) play(bytes)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                onError(e.message?.takeIf { it.isNotBlank() } ?: "Could not read the reply aloud (${e.javaClass.simpleName}).")
            }
        }
    }
}
