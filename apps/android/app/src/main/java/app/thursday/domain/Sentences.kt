package app.thursday.domain

/*
 * Cut a reply into pieces to read aloud one after another. Mirrors the dashboard's sentences.ts.
 *
 * Making the audio takes about a fifth of the time the audio lasts, so the wait before the voice starts is set by
 * how long the first piece is: a whole reply takes several seconds, a sentence about one, a short clause under half
 * a second. So a reply is spoken piece by piece, and the next piece is prepared while one plays. The feed also works
 * on a reply that is still being written: text goes in as it arrives and complete pieces come out.
 *
 * A piece ends after . ! or ? followed by a space, or at a line break. Short pieces join the next one, so "Okay."
 * is not a clip of its own, and a number list ("1. First") or an abbreviation ("e.g. this") does not end a piece.
 * The first piece of a reply may also end at a comma, semicolon or colon, which gets the voice started sooner; after
 * that pieces are whole sentences, which sound better.
 */

private const val MIN_CHARS = 24
private const val MAX_CHARS = 320
private const val QUICK_MIN_CHARS = 16 // the shortest opening clause worth a clip of its own
private val END = Regex("""([.!?]+["')\]]*)(\s+)|([,;:])[ \t]+|\n+""") // a clause mark before a line break is left to the line break
private val LAST_WORD = Regex("""(\S+)$""")
private val CLOSERS = Regex("""["')\]]+$""")
private val MARKS = Regex("""[.!?]+$""")
private val SPACES = Regex("""\s+""")
private val LETTER_OR_DIGIT = Regex("""[\p{L}\p{N}]""")
private val ABBREVIATIONS = setOf("e.g", "i.e", "etc", "vs", "mr", "mrs", "ms", "dr", "no", "fig", "approx")

/** Whether a piece has anything a voice can say (not only punctuation or markdown marks). */
fun sayable(piece: String): Boolean = LETTER_OR_DIGIT.containsMatchIn(piece)

private fun endsSentence(before: String): Boolean {
    val word = (LAST_WORD.find(before)?.groupValues?.get(1) ?: "").replace(CLOSERS, "").replace(MARKS, "")
    if (word.isNotEmpty() && word.all(Char::isDigit)) return false // "1." in a numbered list
    if (word.length == 1 && word[0].isLetter()) return false // an initial: "J. Smith"
    return word.lowercase() !in ABBREVIATIONS
}

class SentenceFeed {
    private var rest = ""
    private var started = false // the reply's first piece has been given out

    /** Add text as it arrives. Returns the pieces that are now complete. */
    fun push(text: String): List<String> {
        rest += text
        return take(final = false)
    }

    /** The reply is over: whatever is left is the last piece. */
    fun flush(): List<String> = take(final = true)

    private fun take(final: Boolean): List<String> {
        val pieces = mutableListOf<String>()
        var start = 0
        fun give(piece: String) {
            pieces += piece // one with nothing to say in it (a rule, a code fence) is dropped below
            started = started || sayable(piece)
        }
        for (match in END.findAll(rest)) {
            val end = match.range.last + 1
            if (match.groups[3] != null) {
                // A clause: only the opening of a reply is cut here.
                val clause = rest.substring(start, match.range.first + 1)
                if (started || !sayable(clause) || clause.trim().length < QUICK_MIN_CHARS) continue
                give(clause)
                start = end
                continue
            }
            if (end == rest.length && !final && '\n' !in match.value) break // more of this sentence's space may come
            val punctuation = match.groups[1]?.value
            val mark = match.range.first + (punctuation?.length ?: 0)
            val piece = rest.substring(start, mark)
            if (punctuation != null && !endsSentence(piece)) continue
            if (sayable(piece) && piece.trim().length < MIN_CHARS) continue // too short alone: joins the next
            give(piece)
            start = end
        }
        rest = rest.substring(start)
        // A long run with no sentence end (a list on one line, a long clause) is cut at the last comma or space.
        while (rest.length > MAX_CHARS) {
            val window = rest.substring(0, MAX_CHARS)
            val comma = maxOf(window.lastIndexOf(", "), window.lastIndexOf("; ")) + 1
            val space = window.lastIndexOf(' ') + 1
            val cut = if (comma > 0) comma else if (space > 0) space else MAX_CHARS
            give(rest.substring(0, cut))
            rest = rest.substring(cut)
        }
        if (final && rest.isNotBlank()) {
            give(rest)
            rest = ""
        }
        return pieces.map { it.replace(SPACES, " ").trim() }.filter(::sayable)
    }
}

/** A whole reply as its pieces. */
fun sentences(text: String): List<String> = SentenceFeed().let { it.push(text) + it.flush() }
