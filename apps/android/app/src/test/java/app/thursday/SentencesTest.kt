package app.thursday

import app.thursday.domain.SentenceFeed
import app.thursday.domain.sayable
import app.thursday.domain.sentences
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The same cases as the dashboard's sentences.test.ts: both clients cut a reply the same way. */
class SentencesTest {
    @Test
    fun aReplyIsCutAtTheEndsOfSentences() {
        assertEquals(
            listOf("The file tells Python how the project is built.", "It lists what the project needs!", "Is that clear enough?"),
            sentences("The file tells Python how the project is built. It lists what the project needs! Is that clear enough?"),
        )
    }

    @Test
    fun aShortPieceJoinsTheNextSoOneWordIsNotAClipOfItsOwn() {
        assertEquals(listOf("Okay. I started the task and will tell you when it is done."), sentences("Okay. I started the task and will tell you when it is done."))
        assertEquals(listOf("Done."), sentences("Done."))
    }

    @Test
    fun aListNumberAnInitialADecimalOrAnAbbreviationDoesNotEndAPiece() {
        assertEquals(
            listOf("Yes. There are 3.5 thousand files in the folder,", "e.g. the logs and the checkpoints.", "That is a lot of files."),
            sentences("Yes. There are 3.5 thousand files in the folder, e.g. the logs and the checkpoints. That is a lot of files."),
        )
        assertEquals(
            listOf("1. Open the settings page first", "2. Choose the models folder next"),
            sentences("1. Open the settings page first\n2. Choose the models folder next"),
        )
    }

    @Test
    fun eachLineOfAListIsAPieceAndWhatCannotBeSaidIsSkipped() {
        assertEquals(
            listOf("Here is what I found in it:", "- the training script for the model", "- the saved checkpoints of the runs"),
            sentences("Here is what I found in it:\n- the training script for the model\n---\n- the saved checkpoints of the runs"),
        )
        assertEquals(listOf(false, false, true), listOf(sayable("```"), sayable("--- ***"), sayable("ok")))
    }

    @Test
    fun piecesComeOutWhileTheReplyIsStillBeingWrittenAndTheRestAtTheEnd() {
        val feed = SentenceFeed()
        assertEquals(emptyList<String>(), feed.push("The task is running now"))
        assertEquals(listOf("The task is running now."), feed.push(". I will"))
        assertEquals("the reply may go on after this full stop", emptyList<String>(), feed.push(" tell you when it is done."))
        assertEquals(listOf("I will tell you when it is done."), feed.flush())
        assertEquals(emptyList<String>(), feed.flush())
    }

    @Test
    fun thePiecesAreTheSameHoweverTheTextArrives() {
        val text = "First I listed the folder to see what is there. Then I read the two files that looked relevant, which took a moment. Nothing was changed."
        val whole = sentences(text)
        for (size in listOf(1, 3, 7, 40)) {
            val feed = SentenceFeed()
            val pieces = text.chunked(size).flatMap(feed::push) + feed.flush()
            assertEquals("in chunks of $size", whole, pieces)
        }
        assertEquals(3, whole.size)
    }

    @Test
    fun theFirstPieceOfAReplyEndsAtACommaSoTheVoiceStartsSoonerAndOnlyTheFirst() {
        assertEquals(
            listOf("I listed the folder,", "read the two files that looked relevant, and found the script.", "Nothing was changed, as you asked."),
            sentences("I listed the folder, read the two files that looked relevant, and found the script. Nothing was changed, as you asked."),
        )
        val feed = SentenceFeed()
        assertEquals("given out as soon as the comma is passed", listOf("The task is running now,"), feed.push("The task is running now, and"))
        assertEquals(emptyList<String>(), feed.push(" it will take a while, I think. "))
        assertEquals(listOf("and it will take a while, I think."), feed.flush())
    }

    @Test
    fun aShortOpeningWordIsNotAClipAndANumberIsNotCut() {
        assertEquals(listOf("Okay, I started the task and will tell you when it is done."), sentences("Okay, I started the task and will tell you when it is done."))
        assertEquals(listOf("Sure, the folder holds 1,250 files,", "most of them logs."), sentences("Sure, the folder holds 1,250 files, most of them logs."))
        assertEquals(
            listOf("Everything went well this time.", "Here is what was done today:", "- listed the folder first", "- read the main script next"),
            sentences("Everything went well this time. Here is what was done today:\n- listed the folder first\n- read the main script next"),
        )
    }

    @Test
    fun aVeryLongRunWithoutASentenceEndIsCutAtAComma() {
        val long = (0 until 60).joinToString(", ") { "item number $it" }
        val pieces = sentences(long)
        assertTrue(pieces.size > 2)
        assertTrue(pieces.all { it.length <= 320 })
        assertEquals(long, pieces.joinToString(" "))
    }
}
