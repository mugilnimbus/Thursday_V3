package app.thursday.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.thursday.domain.MdAlign
import app.thursday.domain.MdBlock
import app.thursday.domain.MdSpan
import app.thursday.domain.fitColumns
import app.thursday.domain.mdParse
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Palette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type

private fun AnnotatedString.Builder.add(spans: List<MdSpan>, p: Palette) {
    for (s in spans) when (s) {
        is MdSpan.Text -> append(s.text)
        is MdSpan.Bold -> withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { add(s.spans, p) }
        is MdSpan.Italic -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { add(s.spans, p) }
        is MdSpan.Code -> withStyle(SpanStyle(fontFamily = Type.mono, background = p.accent.copy(alpha = 0.14f))) { append(s.text) }
        is MdSpan.Link -> withLink(
            LinkAnnotation.Url(s.href, TextLinkStyles(SpanStyle(color = p.accentBright, textDecoration = TextDecoration.Underline))),
        ) { append(s.text) }
    }
}

/**
 * The grid of a table. `cells` holds every cell, row after row. Each column is as wide as its widest cell, within
 * limits (a long cell wraps), and every cell of a row is as tall as the tallest one in it. A table wider than
 * `available` pixels first narrows its columns as far as their longest words allow.
 */
@Composable
private fun TableGrid(columns: Int, available: Int, cells: @Composable () -> Unit) {
    Layout(cells) { measurables, _ ->
        val least = 56.dp.roundToPx()
        val most = 220.dp.roundToPx()
        val rows = measurables.size / columns
        fun widest(c: Int, of: (Int) -> Int) = (0 until rows).maxOf { r -> of(r * columns + c) }
        val natural = IntArray(columns) { c -> widest(c) { measurables[it].maxIntrinsicWidth(Constraints.Infinity) }.coerceIn(least, most) }
        val floors = IntArray(columns) { c -> widest(c) { measurables[it].minIntrinsicWidth(Constraints.Infinity) }.coerceIn(least, natural[c]) }
        val widths = fitColumns(natural, floors, available)
        val heights = IntArray(rows) { r -> (0 until columns).maxOf { c -> measurables[r * columns + c].minIntrinsicHeight(widths[c]) } }
        val placed = List(rows * columns) { i -> measurables[i].measure(Constraints.fixed(widths[i % columns], heights[i / columns])) }
        layout(widths.sum(), heights.sum()) {
            var y = 0
            for (r in 0 until rows) {
                var x = 0
                for (c in 0 until columns) {
                    placed[r * columns + c].place(x, y)
                    x += widths[c]
                }
                y += heights[r]
            }
        }
    }
}

/** Agent text drawn with headings, bold, lists, tables and code. Parsed once per text. */
@Composable
fun MarkdownText(text: String, modifier: Modifier = Modifier, size: TextUnit = Type.base, color: Color = LocalPalette.current.text) {
    val p = LocalPalette.current
    val blocks = remember(text) { mdParse(text) }
    @Composable
    fun line(spans: List<MdSpan>, weight: FontWeight? = null, scale: Float = 1f, mod: Modifier = Modifier, align: TextAlign? = null) = Text(
        buildAnnotatedString { add(spans, p) }, mod, color = color, fontSize = (size.value * scale).sp, fontWeight = weight, lineHeight = (size.value * scale * 1.4f).sp,
        textAlign = align,
    )
    Column(modifier, verticalArrangement = Arrangement.spacedBy(Space.s2)) {
        for (block in blocks) when (block) {
            is MdBlock.Heading -> line(block.spans, FontWeight.SemiBold, if (block.level <= 2) 1.12f else 1f)
            is MdBlock.Paragraph -> line(block.spans)
            is MdBlock.Bullets -> Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                block.items.forEachIndexed { i, item ->
                    Row {
                        Text(if (block.ordered) "${block.start + i}." else "•", Modifier.width(22.dp), color = p.muted, fontSize = size)
                        line(item, mod = Modifier.weight(1f))
                    }
                }
            }
            is MdBlock.CodeBlock -> Box(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).background(p.bg).border(1.dp, p.border, RoundedCornerShape(Radius.md))
                    .horizontalScroll(rememberScrollState()).padding(Space.s2),
            ) { Text(block.text, color = color, fontFamily = Type.mono, fontSize = 13.sp) }
            is MdBlock.Table -> {
                // A table wider than the message scrolls sideways inside its own box.
                val edge = p.border
                val rows = listOf(block.head) + block.rows
                BoxWithConstraints {
                val room = constraints.maxWidth
                Box(Modifier.clip(RoundedCornerShape(Radius.md)).border(1.dp, edge, RoundedCornerShape(Radius.md)).horizontalScroll(rememberScrollState())) {
                    TableGrid(block.head.size, room) {
                        rows.forEachIndexed { r, row ->
                            row.forEachIndexed { c, cell ->
                                Box(
                                    Modifier
                                        .background(if (r == 0) p.accent.copy(alpha = 0.09f) else Color.Transparent)
                                        .drawBehind {
                                            val (wide, tall) = this.size // `size` alone is this function's text size
                                            if (r < rows.lastIndex) drawLine(edge, Offset(0f, tall), Offset(wide, tall), 1.dp.toPx())
                                            if (c > 0) drawLine(edge, Offset.Zero, Offset(0f, tall), 1.dp.toPx())
                                        }
                                        .padding(horizontal = 10.dp, vertical = 6.dp),
                                ) {
                                    val align = when (block.align[c]) { MdAlign.CENTER -> TextAlign.Center; MdAlign.RIGHT -> TextAlign.End; MdAlign.LEFT -> TextAlign.Start }
                                    line(cell, if (r == 0) FontWeight.SemiBold else null, 0.95f, Modifier.fillMaxWidth(), align)
                                }
                            }
                        }
                    }
                }
                }
            }
            MdBlock.Rule -> Box(Modifier.fillMaxWidth().height(1.dp).background(p.border))
        }
    }
}
