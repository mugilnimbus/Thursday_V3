package app.thursday.domain

/**
 * The stored messages and the events of a chat are read a moment apart, so a message stored in between is in
 * the events only. These are the events to show as messages: the ones newer than the newest stored message.
 * Older message events belong to earlier pages of the history and are left alone.
 *
 * [storedPositions] holds the position of each stored message (null for one stored before positions were kept).
 */
fun messagesOnlyInEvents(storedPositions: List<Long?>, events: List<Event>): List<Event> {
    val known = storedPositions.filterNotNull()
    if (storedPositions.isNotEmpty() && known.isEmpty()) return emptyList()
    val newest = known.maxOrNull() ?: -1L
    return events.filter { it.pos > newest && (it.type == "user_message" || it.type == "assistant_message") }
}

/** A full page came back, so there may be older messages still. */
const val MESSAGE_PAGE = 50

/**
 * Whether the list should move down to new content: only while the reader is at the end. Someone who scrolled
 * up to read stays where they are. [canScrollDown] is the list's state when it last came to rest.
 */
fun followsNewest(canScrollDown: Boolean): Boolean = !canScrollDown
