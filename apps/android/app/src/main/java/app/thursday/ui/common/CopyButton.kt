package app.thursday.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import app.thursday.ui.theme.LocalPalette
import kotlinx.coroutines.delay

/** A small button that copies a piece of text, and shows a tick for a moment once it has. */
@Composable
fun CopyButton(text: String, modifier: Modifier = Modifier, what: String = "message") {
    val p = LocalPalette.current
    val clipboard = LocalClipboardManager.current
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(copied) {
        if (copied) {
            delay(1600)
            copied = false
        }
    }
    Box(
        modifier.size(32.dp).clip(CircleShape).clickable(onClickLabel = if (copied) "Copied" else "Copy $what") {
            clipboard.setText(AnnotatedString(text))
            copied = true
        },
        contentAlignment = Alignment.Center,
    ) { LineIcon(if (copied) "check" else "copy", if (copied) p.success else p.muted, 16.dp) }
}
