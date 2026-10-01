package app.thursday

import app.thursday.data.PairingLink
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PairingLinkTest {
    @Test
    fun readsTheDashboardLink() {
        val link = PairingLink.parse("thursday://pair?url=https%3A%2F%2Fpc.tail.ts.net&code=ABCD2345", allowLocalHttp = false)
        assertEquals(PairingLink("https://pc.tail.ts.net", "ABCD2345"), link)
    }

    @Test
    fun acceptsTypedCodesWithDashAndLowercase() {
        assertEquals(PairingLink("https://pc.tail.ts.net", "ABCD2345"), PairingLink.of("pc.tail.ts.net/", "abcd-2345", false))
    }

    @Test
    fun refusesPlainHttpExceptLocalDebug() {
        assertNull(PairingLink.of("http://pc.tail.ts.net", "ABCD2345", allowLocalHttp = false))
        assertNull(PairingLink.of("http://127.0.0.1:8701", "ABCD2345", allowLocalHttp = false))
        assertEquals("http://127.0.0.1:8701", PairingLink.of("http://127.0.0.1:8701", "ABCD2345", allowLocalHttp = true)?.baseUrl)
        assertNull(PairingLink.of("http://10.0.0.5:8701", "ABCD2345", allowLocalHttp = true))
    }

    @Test
    fun refusesOtherLinksAndBadCodes() {
        assertNull(PairingLink.parse("https://evil.example/pair?url=x&code=ABCD2345", false))
        assertNull(PairingLink.parse("thursday://pair?url=https%3A%2F%2Fpc&code=SHORT", false))
        assertNull(PairingLink.of("https://user:pw@pc.tail.ts.net", "ABCD2345", false))
    }
}
