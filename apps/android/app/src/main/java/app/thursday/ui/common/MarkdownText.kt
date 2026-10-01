package app.thursday.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.thursday.domain.MdBlock
import app.thursday.domain.MdSpan
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

/** Agent text drawn with headings, bold, lists and code. Parsed once per text. */
@Composable
fun MarkdownText(text: String, modifier: Modifier = Modifier, size: TextUnit = Type.base, color: Color = LocalPalette.current.text) {
    val p = LocalPalette.current
    val blocks = remember(text) { mdParse(text) }
    @Composable
    fun line(spans: List<MdSpan>, weight: FontWeight? = null, scale: Float = 1f, mod: Modifier = Modifier) = Text(
        buildAnnotatedString { add(spans, p) }, mod, color = color, fontSize = (size.value * scale).sp, fontWeight = weight, lineHeight = (size.value * scale * 1.4f).sp,
    )
    Column(modifier, verticalArrangement = Arrangement.spacedBy(Space.s2)) {
        for (block in blocks) when (block) {
            is MdBlock.Heading -> line(block.spans, FontWeight.SemiBold, if (block.level <= 2) 1.12f else 1f)
            is MdBlock.Paragraph -> line(block.spans)
            is MdBlock.Bullets -> Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                block.items.forEachIndexed { i, item ->
                    Row {
                        Text(if (block.ordered) "${i + 1}." else "•", Modifier.width(22.dp), color = p.muted, fontSize = size)
                        line(item, mod = Modifier.weight(1f))
                    }
                }
            }
            is MdBlock.CodeBlock -> Box(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).background(p.bg).border(1.dp, p.border, RoundedCornerShape(Radius.md))
                    .horizontalScroll(rememberScrollState()).padding(Space.s2),
            ) { Text(block.text, color = color, fontFamily = Type.mono, fontSize = 13.sp) }
            MdBlock.Rule -> Box(Modifier.fillMaxWidth().height(1.dp).background(p.border))
        }
    }
}
