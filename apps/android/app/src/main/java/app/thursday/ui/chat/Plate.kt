package app.thursday.ui.chat

import androidx.compose.foundation.background
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * How solid the backing of the chat's messages and cards is: 1 hides the particle field behind them, 0 shows all of
 * it. Set from the phone's "message transparency" setting.
 */
val LocalMessageSolid = compositionLocalOf { 1f }

/** The widest a message bubble may be here; the chat sets it from the width it has. */
val LocalBubbleMax = compositionLocalOf { 340.dp }

/** Cards in the chat (a task, an approval) stop growing at a comfortable line of text. */
val CARD_MAX = 680.dp

/** A setting from 0 to 100 percent see-through as the solidness to draw with. */
fun solidFor(transparencyPercent: Int): Float = 1f - transparencyPercent.coerceIn(0, 100) / 100f

/**
 * The backing of one element in the chat: the page colour under the element's own tint. The face is drawn behind the
 * list, and a tint that is see-through by design would let it show through the text; the page colour stops that,
 * and [solid] fades both together when some of the face is wanted.
 */
fun Modifier.plate(page: Color, solid: Float, tint: Color = Color.Transparent): Modifier =
    background(page.copy(alpha = solid)).background(tint.copy(alpha = tint.alpha * solid))
