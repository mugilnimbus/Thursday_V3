package app.thursday

import app.thursday.voice.SpeechQueue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList

class SpeechQueueTest {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val started = CopyOnWriteArrayList<String>()
    private val finished = CopyOnWriteArrayList<String>()
    private val cancelled = CopyOnWriteArrayList<String>()
    private val errors = CopyOnWriteArrayList<String>()
    private val fetched = CopyOnWriteArrayList<String>()
    private val idle = java.util.concurrent.atomic.AtomicInteger()
    private val release = java.util.concurrent.ConcurrentHashMap<String, CompletableDeferred<Unit>>()

    @After
    fun tearDown() = scope.cancel()

    /** Audio is the reply's own text; a clip "plays" until the test lets it end. */
    private fun queue(
        allowed: () -> Boolean = { true }, fetchFails: Set<String> = emptySet(), playFails: Set<String> = emptySet(), on: CoroutineScope = scope,
    ) = SpeechQueue(
        on,
        fetch = { text ->
            fetched += text
            if (text in fetchFails) throw IOException("no audio for $text") else text.toByteArray()
        },
        play = { audio ->
            val text = String(audio)
            started += text
            if (text in playFails) throw IOException("cannot play $text")
            try {
                release.getOrPut(text) { CompletableDeferred() }.await()
            } catch (e: CancellationException) {
                cancelled += text // the real player is released here
                throw e
            }
            finished += text
        },
        onError = { errors += it },
        allowed = allowed,
        onIdle = { idle.incrementAndGet() },
    )

    private suspend fun until(what: String, check: () -> Boolean) = withTimeout(5_000) {
        while (!check()) delay(5)
    }.also { assertTrue(what, check()) }

    private fun let(text: String) = release.getOrPut(text) { CompletableDeferred() }.complete(Unit)

    @Test
    fun repliesPlayOneAfterAnotherInOrder() = runBlocking<Unit> {
        val q = queue()
        q.add("one")
        q.add("two")
        until("one starts") { started == listOf("one") }
        delay(50)
        assertEquals("the second waits for the first", listOf("one"), started.toList())
        let("one")
        until("two starts") { started == listOf("one", "two") }
        let("two")
        until("both finished") { finished == listOf("one", "two") }
    }

    @Test
    fun stoppingWhileAReplyPlaysNeverSilencesTheNextOne() = runBlocking<Unit> {
        val q = queue()
        q.add("first")
        until("first is playing") { "first" in started }
        q.stop() // the user taps the mic, turns the speaker off, or leaves the chat
        until("the stopped reply is cancelled, which releases the player") { "first" in cancelled }
        q.add("second")
        until("the next reply still plays") { "second" in started }
        let("second")
        until("and ends") { "second" in finished }
        assertTrue("the stopped reply never finished", "first" !in finished)
    }

    @Test
    fun stoppingDropsTheRepliesStillWaiting() = runBlocking<Unit> {
        val q = queue()
        q.add("a")
        q.add("b")
        until("a is playing") { "a" in started }
        q.stop()
        delay(100)
        assertEquals(listOf("a"), started.toList())
    }

    @Test
    fun aReplyThatCannotBeFetchedIsReportedAndSkipped() = runBlocking<Unit> {
        val q = queue(fetchFails = setOf("bad"))
        q.add("bad")
        q.add("good")
        until("good starts") { "good" in started }
        assertEquals(listOf("no audio for bad"), errors.toList())
        let("good")
    }

    @Test
    fun aReplyThePhoneCannotPlayIsReportedAndSkipped() = runBlocking<Unit> {
        val q = queue(playFails = setOf("bad"))
        q.add("bad")
        q.add("good")
        until("good starts") { "good" in started }
        assertEquals(listOf("cannot play bad"), errors.toList())
        let("good")
    }

    @Test
    fun aReplyIsNotPlayedOnceTheUserHasStartedTalking() = runBlocking<Unit> {
        var talking = false
        val q = queue(allowed = { !talking })
        q.add("first")
        until("first is playing") { "first" in started }
        talking = true
        let("first")
        q.add("second")
        delay(150)
        assertEquals("the second is fetched but not played", listOf("first"), started.toList())
        talking = false
        q.add("third")
        until("playing resumes after") { "third" in started }
        let("third")
    }

    @Test
    fun theNextPieceIsMadeWhileOnePlaysSoThereIsNoGap() = runBlocking<Unit> {
        val q = queue()
        listOf("one", "two", "three", "four").forEach(q::add)
        until("one is playing") { "one" in started }
        until("the pieces behind it are on their way") { "two" in fetched && "three" in fetched }
        delay(50)
        assertTrue("but not the whole reply at once", "four" !in fetched)
        assertEquals(listOf("one"), started.toList())
        let("one")
        until("two starts") { "two" in started }
        until("and the next one is made") { "four" in fetched }
    }

    @Test
    fun itSaysWhenEverythingHasBeenReadButNotWhenStopped() = runBlocking<Unit> {
        val q = queue()
        q.add("one")
        q.add("two")
        until("one is playing") { "one" in started }
        assertEquals("still reading", 0, idle.get())
        let("one")
        let("two")
        until("idle once both are read") { idle.get() == 1 }
        q.add("three")
        until("three is playing") { "three" in started }
        q.stop()
        until("three is cancelled") { "three" in cancelled }
        delay(50)
        assertEquals("a stop is not the end of reading", 1, idle.get())
    }

    @Test
    fun aQueueOnAnImmediateDispatcherReadsToo() = runBlocking<Unit> {
        // The app's scope runs a new coroutine at once, inside the call that starts it.
        val immediate = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        try {
            val q = queue(on = immediate)
            q.add("one")
            q.add("two")
            until("one starts") { "one" in started }
            let("one")
            until("two starts") { "two" in started }
            let("two")
            until("both finished") { finished == listOf("one", "two") }
            q.add("three")
            until("a piece added after the queue ran dry is read") { "three" in started }
            let("three")
        } finally {
            immediate.cancel()
        }
    }
}
