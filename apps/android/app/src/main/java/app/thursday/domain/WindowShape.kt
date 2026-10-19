package app.thursday.domain

import kotlin.math.max
import kotlin.math.min

/** The edge of the screen the navigation runs along. */
enum class NavigationEdge { BOTTOM, RIGHT, LEFT }

/**
 * What the app's window means for its layout. Sizes are in dp and do not count the keyboard, so the layout does not
 * change when the keyboard opens. [quarterTurns] is how far the screen is turned from the way the device is held
 * naturally (0 to 3 quarter turns, as the system reports its rotation).
 *
 * - The navigation stays on the edge of the device where it is when the device is held naturally (its bottom edge),
 *   the way a camera's controls do: turning the device on its side does not move it, the icons only turn to stay
 *   upright. On the screen that edge is the bottom, the right after one quarter turn, the left after three. Held
 *   upside down, which is done on purpose, the navigation goes to the bottom of the screen again.
 * - Along the bottom of a narrow screen the navigation is put away inside a chat, so the chat has the height.
 * - A window at least 840 wide and 480 tall shows a list and what is opened from it side by side (a tablet lying
 *   down). A phone lying down is wide enough but not tall enough: it keeps one pane, so a chat gets all of it.
 */
data class WindowShape(val widthDp: Int, val heightDp: Int, val quarterTurns: Int = 0) {
    val navigation: NavigationEdge
        get() = when (quarterTurns) {
            1 -> NavigationEdge.RIGHT
            3 -> NavigationEdge.LEFT
            else -> NavigationEdge.BOTTOM
        }

    /**
     * Whether the destinations run the other way along the edge, so each one stays where it is on the device: on the
     * right edge the first destination (the left end of the bottom bar) is at the bottom.
     */
    val navigationReversed: Boolean get() = navigation == NavigationEdge.RIGHT
    val barHiddenInChat: Boolean get() = navigation == NavigationEdge.BOTTOM && widthDp < 600
    val twoPanes: Boolean get() = widthDp >= 840 && heightDp >= 480
}

/**
 * How many of the Monitor's tiles go side by side in a pane this wide (dp): one on a phone held upright, two from
 * 600, where each is still wide enough for its figure and its graph.
 */
fun tileColumns(paneWidthDp: Float): Int = if (paneWidthDp >= 600f) 2 else 1

/**
 * The widest a message may be in a list this wide (dp): nearly all of a phone's width, about three quarters of a
 * wider pane, and never more than a comfortable line of text.
 */
fun bubbleMaxDp(listWidthDp: Float): Float = max(min(340f, listWidthDp), min(680f, listWidthDp * 0.78f))
