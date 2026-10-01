package app.thursday.domain

import app.thursday.data.TaskRow

/* Arrange the Trace task list: grouped by chat, by project, or flat. Mirrors the dashboard's grouping.ts. */

data class TaskGroup(val key: String, val label: String, val tasks: List<TaskRow>)

/** Newest first; a group sits where its newest task is. An empty label means the flat list. */
fun groupTasks(tasks: List<TaskRow>, by: String): List<TaskGroup> {
    val sorted = tasks.sortedByDescending { it.createdAt }
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
