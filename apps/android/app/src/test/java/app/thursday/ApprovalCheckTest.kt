package app.thursday

import app.thursday.domain.approvalNeedsCheck
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApprovalCheckTest {
    @Test
    fun allowingAsksForTheFingerprintWhileTheCheckIsOn() {
        assertTrue(approvalNeedsCheck("allow_once", checkOn = true))
        assertTrue(approvalNeedsCheck("allow_always", checkOn = true))
    }

    @Test
    fun allowingDoesNotAskOnceTheCheckIsTurnedOff() {
        assertFalse(approvalNeedsCheck("allow_once", checkOn = false))
        assertFalse(approvalNeedsCheck("allow_always", checkOn = false))
    }

    @Test
    fun denyingNeverAsks() {
        assertFalse(approvalNeedsCheck("deny", checkOn = true))
        assertFalse(approvalNeedsCheck("deny", checkOn = false))
    }
}
