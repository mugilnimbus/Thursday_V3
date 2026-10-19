package app.thursday

import app.thursday.domain.MdAlign
import app.thursday.domain.MdBlock
import app.thursday.domain.MdSpan
import app.thursday.domain.fitColumns
import app.thursday.domain.mdInline
import app.thursday.domain.mdParse
import app.thursday.domain.mdTableCells
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
    fun aNumberedListThatCarriesOnKeepsItsNumbers() {
        val blocks = mdParse("2. second\n3. third\n- a note\n4. fourth\n5. fifth")
        assertEquals(listOf(2 to true, 1 to false, 4 to true), blocks.map { (it as MdBlock.Bullets).start to it.ordered })
    }

    @Test
    fun readsATableHeadingRowDashesThenRows() {
        val blocks = mdParse("Files:\n\n| File | Purpose | Lines |\n|:--|:-:|--:|\n| `train.py` | **Training** loop | 120 |\n| watch_model.py | Monitoring |\nDone.")
        assertEquals(listOf("Paragraph", "Table", "Paragraph"), blocks.map { it::class.simpleName })
        val table = blocks[1] as MdBlock.Table
        assertEquals(listOf(MdAlign.LEFT, MdAlign.CENTER, MdAlign.RIGHT), table.align)
        assertEquals(listOf(listOf(MdSpan.Text("File")), listOf(MdSpan.Text("Purpose")), listOf(MdSpan.Text("Lines"))), table.head)
        assertEquals(listOf(MdSpan.Code("train.py")), table.rows[0][0])
        assertEquals(listOf(MdSpan.Bold(listOf(MdSpan.Text("Training"))), MdSpan.Text(" loop")), table.rows[0][1])
        assertEquals("a row with a cell missing is filled out", listOf(listOf(MdSpan.Text("watch_model.py")), listOf(MdSpan.Text("Monitoring")), emptyList()), table.rows[1])
    }

    @Test
    fun aPipeInCodeOrEscapedStaysInItsCellAndOuterPipesAreOptional() {
        assertEquals(listOf("`a | b`", "x | y"), mdTableCells("| `a | b` | x \\| y |"))
        val table = mdParse("Name | Value\n--- | ---\none | 1")[0] as MdBlock.Table
        assertEquals(listOf(listOf(listOf(MdSpan.Text("one")), listOf(MdSpan.Text("1")))), table.rows)
    }

    @Test
    fun otherLinesWithPipesOrDashesAreNotATable() {
        assertEquals(listOf("Paragraph", "Rule"), mdParse("use a | b to pipe\n---").map { it::class.simpleName })
        assertEquals(listOf("Paragraph"), mdParse("| only a heading row |").map { it::class.simpleName })
        assertEquals("the dashes must have as many cells as the heading", listOf("Paragraph"), mdParse("| a | b |\n|---|").map { it::class.simpleName })
        assertEquals("a table that is still being written has no rows yet", listOf("Table"), mdParse("| a | b |\n|---|---|").map { it::class.simpleName })
    }

    @Test
    fun aTableThatIsTooWideGivesUpSpareWidthToFitAndScrollsOnlyWhenItCannot() {
        assertEquals("it fits already: nothing changes", listOf(110, 75, 120), fitColumns(intArrayOf(110, 75, 120), intArrayOf(60, 60, 60), 320).toList())
        val fitted = fitColumns(intArrayOf(110, 75, 220), intArrayOf(100, 70, 80), 314)
        assertEquals("the column with the most to spare gives the most", listOf(104, 72, 137), fitted.toList())
        assertTrue(fitted.sum() <= 314)
        assertEquals("no column goes below what its longest word needs", listOf(100, 70, 80), fitColumns(intArrayOf(110, 75, 220), intArrayOf(100, 70, 80), 200).toList())
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
