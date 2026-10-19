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

enum class MdAlign { LEFT, CENTER, RIGHT }

sealed interface MdBlock {
    data class Heading(val level: Int, val spans: List<MdSpan>) : MdBlock
    data class Paragraph(val spans: List<MdSpan>) : MdBlock
    /** `start` is the number a numbered list begins at: one that carries on after something else keeps its numbers. */
    data class Bullets(val ordered: Boolean, val items: List<List<MdSpan>>, val start: Int = 1) : MdBlock
    data class CodeBlock(val text: String) : MdBlock
    data class Table(val align: List<MdAlign>, val head: List<List<MdSpan>>, val rows: List<List<List<MdSpan>>>) : MdBlock
    data object Rule : MdBlock
}

private val INLINE = Regex("""(`[^`\n]+`)|(\*\*[^*\n]+?\*\*)|(__[^_\n]+?__)|(\*[^*\s][^*\n]*?\*)|(\[[^\]\n]+]\([^)\s]+\))""")
private val BULLET = Regex("""^\s*[-*+•]\s+(.*)$""")
private val NUMBER = Regex("""^\s*(\d+)[.)]\s+(.*)$""")
private val HEADING = Regex("""^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$""")
private val FENCE = Regex("""^\s*```""")
private val RULE = Regex("""^\s*([-*_])(\s*\1){2,}\s*$""")
private val WEB = Regex("^https?://", RegexOption.IGNORE_CASE)
private val DIVIDER_CELL = Regex("^:?-+:?$")

/**
 * Column widths for a table that should fit in `available`. `natural` is what each column would like (its widest
 * cell on one line) and `floors` the least it can take without breaking a word. When the table is too wide, each
 * column gives up width in proportion to what it can spare; a table whose floors alone are too wide stays wider
 * than `available`, and the caller lets it scroll.
 */
fun fitColumns(natural: IntArray, floors: IntArray, available: Int): IntArray {
    val over = natural.sum() - available
    val spare = natural.indices.sumOf { natural[it] - floors[it] }
    if (over <= 0 || spare <= 0) return natural
    val share = minOf(over, spare).toDouble() / spare
    return IntArray(natural.size) { natural[it] - kotlin.math.ceil((natural[it] - floors[it]) * share).toInt() }
}

/** The cells of one table row. A pipe inside `code` or written as \| belongs to its cell. */
fun mdTableCells(line: String): List<String> {
    val cells = mutableListOf<String>()
    val cell = StringBuilder()
    var code = false
    val text = line.trim()
    var i = 0
    while (i < text.length) {
        val c = text[i]
        if (c == '\\' && i + 1 < text.length && text[i + 1] == '|') {
            cell.append('|')
            i++
        } else if (c == '|' && !code) {
            cells += cell.toString().trim()
            cell.clear()
        } else {
            if (c == '`') code = !code
            cell.append(c)
        }
        i++
    }
    cells += cell.toString().trim()
    if (text.startsWith("|")) cells.removeAt(0)
    if (text.endsWith("|") && !text.endsWith("\\|") && cells.isNotEmpty()) cells.removeAt(cells.lastIndex)
    return cells
}

/** How each column is aligned, when the line is the row of dashes under a table's heading; otherwise null. */
private fun tableDivider(line: String): List<MdAlign>? {
    if ('|' !in line && ':' !in line) return null // a bare "---" is a rule, not a one-column table
    val cells = mdTableCells(line)
    if (cells.isEmpty() || !cells.all(DIVIDER_CELL::matches)) return null
    return cells.map { if (it.endsWith(":")) (if (it.startsWith(":")) MdAlign.CENTER else MdAlign.RIGHT) else MdAlign.LEFT }
}

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
        // A table: a row of cells, then a row of dashes with as many cells, then the rows until one has no pipe.
        // (`i` already points at the line after this one.)
        val align = if ('|' in line && i < lines.size) tableDivider(lines[i]) else null
        val head = if (align != null) mdTableCells(line) else emptyList()
        if (align != null && head.size == align.size) {
            flush()
            val rows = mutableListOf<List<List<MdSpan>>>()
            i++
            while (i < lines.size && '|' in lines[i] && lines[i].isNotBlank()) {
                val cells = mdTableCells(lines[i++])
                rows += head.indices.map { column -> mdInline(cells.getOrElse(column) { "" }) }
            }
            blocks += MdBlock.Table(align, head.map(::mdInline), rows)
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
        val number = if (bullet == null) NUMBER.find(line) else null
        if (bullet != null || number != null) {
            flush()
            val ordered = bullet == null
            val text = mdInline(bullet?.groupValues?.get(1) ?: number!!.groupValues[2])
            val last = blocks.lastOrNull()
            if (last is MdBlock.Bullets && last.ordered == ordered) {
                blocks[blocks.lastIndex] = last.copy(items = last.items + listOf(text))
            } else {
                // A list that carries on after something else ("4." after a few bullets) keeps the number it starts at.
                blocks += MdBlock.Bullets(ordered, listOf(text), start = number?.groupValues?.get(1)?.toIntOrNull() ?: 1)
            }
            continue
        }
        paragraph += line
    }
    flush()
    return blocks
}
