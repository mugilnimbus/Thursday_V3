package app.thursday

import app.thursday.domain.NavigationEdge
import app.thursday.domain.WindowShape
import app.thursday.domain.bubbleMaxDp
import app.thursday.domain.tileColumns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WindowShapeTest {
    private val phoneUpright = WindowShape(384, 853, quarterTurns = 0)
    private val phoneOnItsSide = WindowShape(853, 384, quarterTurns = 1)
    private val phoneOnItsOtherSide = WindowShape(853, 384, quarterTurns = 3)
    private val phoneUpsideDown = WindowShape(384, 853, quarterTurns = 2)
    private val tabletUpright = WindowShape(720, 1152, quarterTurns = 0)
    private val tabletOnItsSide = WindowShape(1152, 720, quarterTurns = 1)

    @Test
    fun theNavigationStaysOnTheSameEdgeOfTheDeviceWhenItIsTurnedOnItsSide() {
        assertEquals(NavigationEdge.BOTTOM, phoneUpright.navigation)
        assertEquals("the device's bottom edge is now the right of the screen", NavigationEdge.RIGHT, phoneOnItsSide.navigation)
        assertEquals("turned the other way it is the left", NavigationEdge.LEFT, phoneOnItsOtherSide.navigation)
        assertEquals(NavigationEdge.BOTTOM, tabletUpright.navigation)
        assertEquals(NavigationEdge.RIGHT, tabletOnItsSide.navigation)
    }

    @Test
    fun eachDestinationStaysWhereItIsOnTheDevice() {
        assertTrue("the left end of the bar is the bottom of the right edge", phoneOnItsSide.navigationReversed)
        assertFalse("and the top of the left edge", phoneOnItsOtherSide.navigationReversed)
        assertFalse(phoneUpright.navigationReversed)
    }

    @Test
    fun heldUpsideDownTheNavigationGoesToTheBottomOfTheScreenAgain() {
        assertEquals(NavigationEdge.BOTTOM, phoneUpsideDown.navigation)
        assertFalse(phoneUpsideDown.navigationReversed)
    }

    @Test
    fun theBarIsPutAwayInAChatOnlyWhereItCostsHeightOnANarrowScreen() {
        assertTrue(phoneUpright.barHiddenInChat)
        assertTrue(phoneUpsideDown.barHiddenInChat)
        assertFalse("down the side it costs no height", phoneOnItsSide.barHiddenInChat)
        assertFalse("a tablet has the height to spare", tabletUpright.barHiddenInChat)
    }

    @Test
    fun onlyATabletLyingDownShowsTheListBesideWhatIsOpen() {
        assertTrue(tabletOnItsSide.twoPanes)
        assertFalse(tabletUpright.twoPanes)
        assertFalse("wide enough, but a chat needs all of the little height there is", phoneOnItsSide.twoPanes)
        assertFalse(phoneUpright.twoPanes)
    }

    @Test
    fun theMonitorPutsItsTilesTwoToARowWhereThePaneIsWideEnough() {
        assertEquals("a phone held upright", 1, tileColumns(384f))
        assertEquals("a tablet held upright", 2, tileColumns(720f))
        assertEquals("a tablet on its side, beside the navigation", 2, tileColumns(1076f))
        assertEquals("a phone on its side, beside the navigation", 2, tileColumns(777f))
    }

    @Test
    fun aMessageIsNearlyAsWideAsAPhoneAndAboutThreeQuartersOfAWiderPane() {
        assertEquals("a phone held upright, as before", 340f, bubbleMaxDp(358f), 0f)
        assertEquals("never wider than the list itself", 300f, bubbleMaxDp(300f), 0f)
        assertEquals("a tablet held upright", 541f, bubbleMaxDp(694f), 0.5f)
        assertEquals("beside the list on a tablet lying down", 553f, bubbleMaxDp(709f), 0.5f)
        assertEquals("a comfortable line of text at most", 680f, bubbleMaxDp(1100f), 0f)
    }
}
