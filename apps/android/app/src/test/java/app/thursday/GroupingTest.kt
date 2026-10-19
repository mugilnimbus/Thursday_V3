package app.thursday

import app.thursday.data.TaskRow
import app.thursday.domain.groupTasks
import app.thursday.domain.orderSteps
import org.junit.Assert.assertEquals
import org.junit.Test

class GroupingTest {
    private fun task(id: String, minute: Int, project: String, chat: String) = TaskRow(
        id, "c-$chat", "completed", "none", id, "", "2026-10-01T10:%02d:00+00:00".format(minute), "", chat, "p-$project", project,
    )

    private val tasks = listOf(task("a", 1, "Demo", "Logs"), task("b", 5, "Test", "Game"), task("c", 3, "Demo", "Logs"), task("d", 4, "Demo", "Notes"))

    @Test
    fun groupsByChatWithTheMostRecentGroupFirst() {
        val groups = groupTasks(tasks, "chat")
        assertEquals(listOf("Test › Game", "Demo › Notes", "Demo › Logs"), groups.map { it.label })
        assertEquals(listOf("c", "a"), groups[2].tasks.map { it.id })
    }

    @Test
    fun groupsByProjectOrNotAtAll() {
        assertEquals(listOf("Test" to 1, "Demo" to 3), groupTasks(tasks, "project").map { it.label to it.tasks.size })
        assertEquals(listOf("b", "d", "c", "a"), groupTasks(tasks, "none").single().tasks.map { it.id })
        assertEquals(emptyList<Any>(), groupTasks(emptyList(), "chat"))
    }

    @Test
    fun oldestFirstReversesTheTasksAndTheGroups() {
        val groups = groupTasks(tasks, "chat", newestFirst = false)
        assertEquals(listOf("Demo › Logs", "Demo › Notes", "Test › Game"), groups.map { it.label })
        assertEquals(listOf("a", "c"), groups[0].tasks.map { it.id })
    }

    @Test
    fun stepsCanBeShownLastToFirstWithEachStepsToolCallsReversedToo() {
        val steps = listOf(1 to listOf("list", "read"), 2 to listOf("edit"), 3 to emptyList())
        assertEquals(steps, orderSteps(steps, lastFirst = false) { it.first to it.second.reversed() })
        assertEquals(
            listOf(3 to emptyList(), 2 to listOf("edit"), 1 to listOf("read", "list")),
            orderSteps(steps, lastFirst = true) { it.first to it.second.reversed() },
        )
    }
}
