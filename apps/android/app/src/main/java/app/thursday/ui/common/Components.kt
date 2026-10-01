package app.thursday.ui.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.thursday.domain.ChartShape
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type

@Composable
fun Txt(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = LocalPalette.current.text,
    size: TextUnit = Type.base,
    weight: FontWeight? = null,
    maxLines: Int = Int.MAX_VALUE,
    mono: Boolean = false,
    align: TextAlign? = null,
) = Text(
    text, modifier, color = color, fontSize = size, fontWeight = weight, maxLines = maxLines, overflow = TextOverflow.Ellipsis,
    fontFamily = if (mono) Type.mono else null, textAlign = align, lineHeight = (size.value * 1.4f).sp,
)

@Composable
fun Caption(text: String, modifier: Modifier = Modifier, color: Color = LocalPalette.current.muted, maxLines: Int = Int.MAX_VALUE) =
    Txt(text, modifier, color, Type.caption, maxLines = maxLines)

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) =
    Txt(text.uppercase(), modifier, LocalPalette.current.muted, 12.sp, FontWeight.SemiBold)

/** The panel: a faint violet gradient from the top, a thin border, rounded corners. */
@Composable
fun Panel(modifier: Modifier = Modifier, border: Color? = null, padding: Dp = Space.s4, content: @Composable ColumnScope.() -> Unit) {
    val p = LocalPalette.current
    Column(
        modifier
            .clip(RoundedCornerShape(Radius.lg))
            .background(Brush.linearGradient(listOf(p.panelTop, p.bg), start = Offset(0f, 0f), end = Offset(600f, 900f)))
            .border(1.dp, border ?: p.border, RoundedCornerShape(Radius.lg))
            .padding(padding),
        verticalArrangement = Arrangement.spacedBy(Space.s3),
        content = content,
    )
}

@Composable
fun Chip(text: String, color: Color) {
    Box(
        Modifier.clip(CircleShape).background(color.copy(alpha = 0.12f)).border(1.dp, color, CircleShape).padding(horizontal = 10.dp, vertical = 2.dp),
    ) { Txt(text, color = color, size = 12.sp, weight = FontWeight.SemiBold, maxLines = 1) }
}

@Composable
fun Dot(kind: String, modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    val color = when (kind) { "warn" -> p.warning; "run" -> p.accent; "ok" -> p.success; "bad" -> p.danger; else -> p.muted }
    Box(modifier.size(8.dp).clip(CircleShape).background(color))
}

enum class Look { PRIMARY, NORMAL, PLAIN, DANGER }

@Composable
fun Btn(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, look: Look = Look.NORMAL, enabled: Boolean = true, small: Boolean = false) {
    val p = LocalPalette.current
    val (fg, bg, line) = when (look) {
        Look.PRIMARY -> Triple(p.accentBright, p.accentFill, p.accent)
        Look.NORMAL -> Triple(p.text, Color.Transparent, p.borderStrong)
        Look.PLAIN -> Triple(p.accentBright, Color.Transparent, Color.Transparent)
        Look.DANGER -> Triple(p.danger, p.danger.copy(alpha = 0.10f), p.danger)
    }
    val shape = RoundedCornerShape(if (small) Radius.sm else Radius.md)
    Box(
        modifier
            .defaultMinSize(minHeight = if (small) 34.dp else 44.dp)
            .clip(shape)
            .background(bg)
            .border(BorderStroke(1.dp, line), shape)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = if (small) Space.s3 else Space.s4, vertical = 6.dp),
        contentAlignment = Alignment.Center,
    ) {
        Txt(text, color = if (enabled) fg else fg.copy(alpha = 0.45f), size = if (small) Type.caption else Type.base, weight = FontWeight.SemiBold, maxLines = 1)
    }
}

/** Segmented choice, like the dashboard's `.seg`. */
@Composable
fun Seg(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit, modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    Row(
        modifier.clip(RoundedCornerShape(Radius.md)).border(1.dp, p.borderStrong, RoundedCornerShape(Radius.md)).padding(2.dp),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        options.forEach { (value, label) ->
            val on = value == selected
            Box(
                Modifier
                    .clip(RoundedCornerShape(11.dp))
                    .background(if (on) p.accentFill else Color.Transparent)
                    .border(1.dp, if (on) p.accent else Color.Transparent, RoundedCornerShape(11.dp))
                    .clickable { onSelect(value) }
                    .padding(horizontal = Space.s3, vertical = 7.dp),
            ) { Txt(label, color = if (on) p.accentBright else p.muted, size = Type.caption, weight = FontWeight.Medium, maxLines = 1) }
        }
    }
}

@Composable
fun Field(
    value: String,
    onChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String? = null,
    placeholder: String = "",
    mono: Boolean = false,
    minLines: Int = 1,
    error: String? = null,
    help: String? = null,
) {
    val p = LocalPalette.current
    Column(modifier, verticalArrangement = Arrangement.spacedBy(Space.s1)) {
        label?.let { Txt(it, color = p.muted, size = Type.caption, weight = FontWeight.SemiBold) }
        BasicTextField(
            value, onChange,
            textStyle = TextStyle(color = p.text, fontSize = if (mono) 14.sp else Type.base, fontFamily = if (mono) Type.mono else null),
            cursorBrush = SolidColor(p.accent),
            minLines = minLines,
            modifier = Modifier.fillMaxWidth(),
            decorationBox = { inner ->
                Box(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md))
                        .border(1.dp, if (error != null) p.danger else p.borderStrong, RoundedCornerShape(Radius.md))
                        .padding(horizontal = Space.s3, vertical = 11.dp),
                ) {
                    if (value.isEmpty()) Txt(placeholder, color = p.muted.copy(alpha = 0.7f), size = if (mono) 14.sp else Type.base, mono = mono)
                    inner()
                }
            },
        )
        (error ?: help)?.let { Caption(it, color = if (error != null) p.danger else p.muted) }
    }
}

@Composable
fun BannerRow(text: String) {
    val p = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).background(p.warning.copy(alpha = 0.10f))
            .border(1.dp, p.warning, RoundedCornerShape(Radius.md)).padding(horizontal = Space.s3, vertical = Space.s2),
    ) { Txt(text, color = p.warning, size = Type.caption, weight = FontWeight.Medium) }
}

@Composable
fun ListBox(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val p = LocalPalette.current
    Column(modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).border(1.dp, p.border, RoundedCornerShape(Radius.md)), content = content)
}

@Composable
fun ListRow(onClick: (() -> Unit)? = null, content: @Composable RowScope.() -> Unit) {
    Row(
        Modifier.fillMaxWidth().defaultMinSize(minHeight = 52.dp).let { if (onClick != null) it.clickable(onClick = onClick) else it }
            .padding(horizontal = Space.s3, vertical = Space.s2),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Space.s3),
        content = content,
    )
}

/** Edge-to-edge time chart: smooth lines with a gradient fading down; breaks are stretches with no data. */
@Composable
fun Spark(chart: ChartShape, color: Color, modifier: Modifier = Modifier, fill: Boolean = true) {
    Canvas(modifier.fillMaxWidth().height(56.dp)) {
        val pad = 4.dp.toPx()
        fun at(point: Pair<Float, Float>) = Offset(point.first * size.width, pad + point.second * (size.height - pad))
        for (run in chart.runs) {
            val pts = run.map(::at)
            val line = Path().apply {
                moveTo(pts[0].x, pts[0].y)
                for (i in 1 until pts.size) {
                    val mid = (pts[i - 1].x + pts[i].x) / 2
                    cubicTo(mid, pts[i - 1].y, mid, pts[i].y, pts[i].x, pts[i].y)
                }
            }
            if (fill) {
                val area = Path().apply { addPath(line); lineTo(pts.last().x, size.height); lineTo(pts.first().x, size.height); close() }
                drawPath(area, Brush.verticalGradient(listOf(color.copy(alpha = 0.55f), color.copy(alpha = 0f)), startY = pts.minOf { it.y }, endY = size.height))
            }
            drawPath(line, color, style = Stroke(width = 2.2.dp.toPx(), cap = StrokeCap.Round))
        }
        chart.dots.forEach { drawCircle(color, 3.dp.toPx(), at(it)) }
    }
}

@Composable
fun Gauge(fraction: Double, label: String, color: Color, sizeDp: Dp = 168.dp) {
    val p = LocalPalette.current
    Box(Modifier.size(sizeDp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(sizeDp)) {
            val stroke = 12.dp.toPx()
            val inset = stroke / 2 + 6.dp.toPx()
            val arcSize = androidx.compose.ui.geometry.Size(size.width - 2 * inset, size.height - 2 * inset)
            drawArc(color.copy(alpha = 0.2f), 0f, 360f, false, Offset(inset, inset), arcSize, style = Stroke(stroke))
            drawArc(color, -90f, (360 * fraction.coerceIn(0.0, 1.0)).toFloat(), false, Offset(inset, inset), arcSize, style = Stroke(stroke, cap = StrokeCap.Round))
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Txt("${Math.round(fraction * 100)}%", size = Type.large, weight = FontWeight.SemiBold)
            Caption(label, color = p.muted)
        }
    }
}

val ScreenPadding = PaddingValues(horizontal = Space.s4, vertical = Space.s3)
