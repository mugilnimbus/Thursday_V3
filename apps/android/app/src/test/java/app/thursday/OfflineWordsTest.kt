package app.thursday

import app.thursday.data.offlineWords
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

class OfflineWordsTest {
    @Test
    fun aNameThatCannotBeLookedUpPointsAtPrivateDns() {
        val words = offlineWords(UnknownHostException("Unable to resolve host"))
        assertTrue(words, words.startsWith("Cannot find your PC by its name."))
        assertTrue(words, "Private DNS" in words)
    }

    @Test
    fun anyOtherFailureToConnectPointsAtTailscale() {
        val plain = "Cannot reach your PC. Check that Tailscale is on."
        assertEquals(plain, offlineWords(SocketTimeoutException("timeout")))
        assertEquals(plain, offlineWords(IOException("connection reset")))
    }
}
