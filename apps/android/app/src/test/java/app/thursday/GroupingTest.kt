package app.thursday

import app.thursday.data.TaskRow
import app.thursday.domain.groupTasks
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
}
