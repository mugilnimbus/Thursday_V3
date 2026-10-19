package app.thursday

import app.thursday.domain.Event
import app.thursday.domain.followsNewest
import app.thursday.domain.messagesOnlyInEvents
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatLoadTest {
    private fun event(pos: Long, type: String) = Event(pos, "voice", "2026-01-01T00:00:00Z", "c1", null, type, mapOf("text" to "m$pos"))

    @Test
    fun aMessageStoredWhileTheChatLoadedIsTakenFromTheEvents() {
        val events = listOf(event(3, "user_message"), event(4, "task_status"), event(7, "assistant_message"))
        assertEquals(listOf(7L), messagesOnlyInEvents(listOf(2L, 3L), events).map { it.pos })
    }

    @Test
    fun anEmptyHistoryTakesEveryMessageEvent() {
        val events = listOf(event(1, "user_message"), event(2, "llm_call"), event(3, "assistant_message"))
        assertEquals(listOf(1L, 3L), messagesOnlyInEvents(emptyList(), events).map { it.pos })
    }

    @Test
    fun olderPagesAndMessagesWithoutAPositionAddNothing() {
        val events = listOf(event(1, "user_message"), event(5, "assistant_message"))
        assertEquals(emptyList<Long>(), messagesOnlyInEvents(listOf(5L, 6L), events).map { it.pos })
        assertEquals(emptyList<Long>(), messagesOnlyInEvents(listOf(null, null), events).map { it.pos })
    }

    @Test
    fun theListFollowsNewContentOnlyFromItsEnd() {
        assertTrue(followsNewest(canScrollDown = false))
        assertFalse(followsNewest(canScrollDown = true))
    }
}
