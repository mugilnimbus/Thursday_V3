package app.thursday.domain

/*
 * A small markdown reader for agent replies, mirroring apps/dashboard/src/lib/ui/markdown.ts.
 * It returns plain data; the UI draws it. Model output is untrusted: unknown syntax stays as text and
 * only http(s) addresses become links.
 */

sealed interface MdSpan {
    data class Text(val text: String) : MdSpan
    data class Bold(val spans: List<MdSpan>) : MdSpan
    data class Italic(val spans: List<MdSpan>) : MdSpan
    data class Code(val text: String) : MdSpan
    data class Link(val text: String, val href: String) : MdSpan
}

sealed interface MdBlock {
    data class Heading(val level: Int, val spans: List<MdSpan>) : MdBlock
    data class Paragraph(val spans: List<MdSpan>) : MdBlock
    data class Bullets(val ordered: Boolean, val items: List<List<MdSpan>>) : MdBlock
    data class CodeBlock(val text: String) : MdBlock
    data object Rule : MdBlock
}

private val INLINE = Regex("""(`[^`\n]+`)|(\*\*[^*\n]+?\*\*)|(__[^_\n]+?__)|(\*[^*\s][^*\n]*?\*)|(\[[^\]\n]+]\([^)\s]+\))""")
private val BULLET = Regex("""^\s*[-*+•]\s+(.*)$""")
private val NUMBER = Regex("""^\s*\d+[.)]\s+(.*)$""")
private val HEADING = Regex("""^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$""")
private val FENCE = Regex("""^\s*```""")
private val RULE = Regex("""^\s*([-*_])(\s*\1){2,}\s*$""")
private val WEB = Regex("^https?://", RegexOption.IGNORE_CASE)

fun mdInline(text: String): List<MdSpan> {
    val spans = mutableListOf<MdSpan>()
    var rest = text
    while (rest.isNotEmpty()) {
        val m = INLINE.find(rest)
        if (m == null) {
            spans += MdSpan.Text(rest)
            break
        }
        if (m.range.first > 0) spans += MdSpan.Text(rest.substring(0, m.range.first))
        val hit = m.value
        when {
            m.groups[1] != null -> spans += MdSpan.Code(hit.substring(1, hit.length - 1))
            m.groups[2] != null || m.groups[3] != null -> spans += MdSpan.Bold(mdInline(hit.substring(2, hit.length - 2)))
            m.groups[4] != null -> spans += MdSpan.Italic(mdInline(hit.substring(1, hit.length - 1)))
            else -> {
                val close = hit.indexOf("](")
                val href = hit.substring(close + 2, hit.length - 1)
                spans += if (WEB.containsMatchIn(href)) MdSpan.Link(hit.substring(1, close), href) else MdSpan.Text(hit)
            }
        }
        rest = rest.substring(m.range.last + 1)
    }
    return spans
}

fun mdParse(markdown: String): List<MdBlock> {
    val blocks = mutableListOf<MdBlock>()
    val lines = markdown.replace("\r\n", "\n").replace('\r', '\n').split("\n")
    val paragraph = mutableListOf<String>()
    fun flush() {
        if (paragraph.isNotEmpty()) blocks += MdBlock.Paragraph(mdInline(paragraph.joinToString("\n")))
        paragraph.clear()
    }
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        if (FENCE.containsMatchIn(line)) {
            flush()
            val code = mutableListOf<String>()
            i++
            while (i < lines.size && !FENCE.containsMatchIn(lines[i])) code += lines[i++]
            blocks += MdBlock.CodeBlock(code.joinToString("\n"))
            i++
            continue
        }
        i++
        if (line.isBlank()) {
            flush()
            continue
        }
        val heading = HEADING.find(line)
        if (heading != null) {
            flush()
            blocks += MdBlock.Heading(heading.groupValues[1].length, mdInline(heading.groupValues[2]))
            continue
        }
        if (RULE.matches(line)) {
            flush()
            blocks += MdBlock.Rule
            continue
        }
        val bullet = BULLET.find(line)
        val item = bullet ?: NUMBER.find(line)
        if (item != null) {
            flush()
            val ordered = bullet == null
            val last = blocks.lastOrNull()
            if (last is MdBlock.Bullets && last.ordered == ordered) {
                blocks[blocks.lastIndex] = last.copy(items = last.items + listOf(mdInline(item.groupValues[1])))
            } else {
                blocks += MdBlock.Bullets(ordered, listOf(mdInline(item.groupValues[1])))
            }
            continue
        }
        paragraph += line
    }
    flush()
    return blocks
}
