package app.thursday.ui

import app.thursday.domain.epochMillis
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

fun relativeTime(iso: String, now: Long = System.currentTimeMillis()): String {
    val ms = epochMillis(iso)
    if (ms == 0L) return ""
    val seconds = (now - ms) / 1000
    return when {
        seconds < 60 -> "just now"
        seconds < 3600 -> "${seconds / 60} min ago"
        seconds < 86_400 -> "${seconds / 3600} h ago"
        seconds < 172_800 -> "Yesterday"
        else -> DateTimeFormatter.ofPattern("d MMM").withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(ms))
    }
}

fun clock(iso: String): String {
    val ms = epochMillis(iso)
    return if (ms == 0L) "" else DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(ms))
}
