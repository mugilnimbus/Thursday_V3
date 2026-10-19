package app.thursday.domain

import app.thursday.data.TaskRow

/* Arrange Trace: the task list grouped by chat, by project, or flat, newest or oldest first; and one task's steps
   first to last or last to first. Mirrors the dashboard's grouping.ts. */

data class TaskGroup(val key: String, val label: String, val tasks: List<TaskRow>)

/** A group sits where its first task in the chosen order is. An empty label means the flat list. */
fun groupTasks(tasks: List<TaskRow>, by: String, newestFirst: Boolean = true): List<TaskGroup> {
    val sorted = if (newestFirst) tasks.sortedByDescending { it.createdAt } else tasks.sortedBy { it.createdAt }
    if (by == "none") return if (sorted.isEmpty()) emptyList() else listOf(TaskGroup("all", "", sorted))
    val groups = LinkedHashMap<String, MutableList<TaskRow>>()
    val labels = HashMap<String, String>()
    for (task in sorted) {
        val project = task.projectName ?: "Deleted project"
        val key = if (by == "project") task.projectId.orEmpty() else "${task.projectId.orEmpty()}/${task.chatId.orEmpty()}"
        labels[key] = if (by == "project") project else "$project › ${task.chatTitle ?: "Deleted chat"}"
        groups.getOrPut(key) { mutableListOf() }.add(task)
    }
    return groups.map { (key, list) -> TaskGroup(key, labels.getValue(key), list) }
}

/**
 * A task's steps in the order to show them. Last to first puts the newest step on top and, inside each step, its
 * newest tool call first. `reverseTools` returns a copy of a step with its tool calls reversed.
 */
fun <T> orderSteps(steps: List<T>, lastFirst: Boolean, reverseTools: (T) -> T): List<T> =
    if (lastFirst) steps.map(reverseTools).reversed() else steps
