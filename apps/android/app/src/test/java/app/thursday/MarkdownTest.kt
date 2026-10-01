package app.thursday

import app.thursday.domain.MdBlock
import app.thursday.domain.MdSpan
import app.thursday.domain.mdInline
import app.thursday.domain.mdParse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MarkdownTest {
    @Test
    fun readsAnAgentReply() {
        val blocks = mdParse("Done. Summary:\n\n### 1. `README.md` (High level)\n*   **Core**: roles\n*   **Loop**: the cycle\n\nAll good.")
        assertEquals(listOf("Paragraph", "Heading", "Bullets", "Paragraph"), blocks.map { it::class.simpleName })
        val heading = blocks[1] as MdBlock.Heading
        assertEquals(3, heading.level)
        assertEquals(MdSpan.Code("README.md"), heading.spans[1])
        val list = blocks[2] as MdBlock.Bullets
        assertEquals(2, list.items.size)
        assertTrue(list.items[0][0] is MdSpan.Bold)
    }

    @Test
    fun keepsCodeFencesVerbatimAndNumbersLists() {
        val blocks = mdParse("1. one\n2. two\n\n```py\nx = **not bold**\n```")
        assertEquals(true, (blocks[0] as MdBlock.Bullets).ordered)
        assertEquals(MdBlock.CodeBlock("x = **not bold**"), blocks[1])
    }

    @Test
    fun onlyWebAddressesBecomeLinks() {
        val spans = mdInline("[docs](https://example.com/a) and [bad](javascript:x)")
        assertEquals(MdSpan.Link("docs", "https://example.com/a"), spans[0])
        assertEquals(MdSpan.Text("[bad](javascript:x)"), spans[2])
    }

    @Test
    fun cutOffOrOddTextStaysAsText() {
        assertEquals(listOf(MdBlock.Paragraph(listOf(MdSpan.Text("an **unfinished bold")))), mdParse("an **unfinished bold"))
        assertEquals(listOf(MdBlock.Paragraph(listOf(MdSpan.Text("<b>2 * 3 * 4</b>")))), mdParse("<b>2 * 3 * 4</b>"))
    }
}
