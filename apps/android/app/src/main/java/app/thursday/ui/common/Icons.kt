package app.thursday.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/* The dashboard's line icons (24 by 24 SVG paths), drawn as strokes. */
private val PATHS = mapOf(
    "chats" to "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
    "trace" to "M4 6h16M4 12h10M4 18h6",
    "tools" to "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.5-.5-2.5z",
    "monitor" to "M3 17l5-6 4 4 6-8 3 4",
    "settings" to "M4 7h9M17 7h3M4 17h3M11 17h9M15 4v6M9 14v6",
    "send" to "M12 19V5M5 12l7-7 7 7",
    "mic" to "M9 6a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0zM5 11a7 7 0 0 0 14 0M12 18v3",
    "more" to "M5 12h.01M12 12h.01M19 12h.01",
    "plus" to "M12 5v14M5 12h14",
    "back" to "M15 6l-6 6 6 6",
    "chev" to "M9 6l6 6-6 6",
    "pause" to "M9 5v14M15 5v14",
    "play" to "M7 5l12 7-12 7z",
    "stop" to "M6 8a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2z",
    "trash" to "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
    "edit" to "M4 20h4L19 9l-4-4L4 16z",
    "scan" to "M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16",
    "folder" to "M3 6h7l2 2h9v11H3z",
    "refresh" to "M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5",
    "file" to "M6 3h8l4 4v14H6zM14 3v4h4",
    "speaker" to "M4 9v6h4l5 4V5L8 9H4zM16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12",
    "mute" to "M4 9v6h4l5 4V5L8 9H4zM17 9.5l5 5M22 9.5l-5 5",
    "alert" to "M12 3l10 18H2L12 3zM12 10v5M12 18h.01",
)

@Composable
fun LineIcon(name: String, color: Color, size: Dp = 22.dp, modifier: Modifier = Modifier) {
    val path = remember(name) { PathParser().parsePathString(PATHS[name] ?: PATHS.getValue("more")).toPath() }
    Canvas(modifier.size(size)) {
        val k = this.size.width / 24f
        scale(k, k, pivot = androidx.compose.ui.geometry.Offset.Zero) {
            drawPath(path, color, style = Stroke(width = (if (name == "more") 2.8f else 1.8f), cap = StrokeCap.Round, join = StrokeJoin.Round))
        }
    }
}

@Composable
fun TabIcon(name: String, color: Color) = LineIcon(name, color, 22.dp)
