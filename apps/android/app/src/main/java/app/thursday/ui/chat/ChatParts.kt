package app.thursday.ui.chat

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import app.thursday.MainActivity
import app.thursday.data.Approval
import app.thursday.domain.TaskView
import app.thursday.domain.Tone
import app.thursday.domain.approvalNeedsCheck
import app.thursday.domain.epochMillis
import app.thursday.domain.liveLine
import app.thursday.graph
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.Chip
import app.thursday.ui.common.CopyButton
import app.thursday.ui.common.LineIcon
import app.thursday.ui.common.Look
import app.thursday.ui.common.MarkdownText
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type
import app.thursday.voice.VoiceMode
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** A task in the chat: a status dot, the title, and a small arrow. Opening it shows the steps and the result. */
@Composable
fun TaskCard(task: TaskView, onTrace: () -> Unit) {
    val p = LocalPalette.current
    var collapsed by remember(task.taskId) { mutableStateOf<Boolean?>(null) }
    val folded = collapsed ?: task.terminal
    // Green: done. Red: failed. Orange: needs you or paused. Violet: working. Grey: stopped.
    val status = when {
        task.state == "input_required" -> p.warning
        task.state == "completed" -> p.success
        task.state == "failed" -> p.danger
        task.state == "canceled" -> p.muted
        task.pauseState == "paused" -> p.warning
        else -> p.accent
    }
    Column(
        Modifier.widthIn(max = CARD_MAX).fillMaxWidth().clip(RoundedCornerShape(Radius.md)).plate(p.bg, LocalMessageSolid.current).padding(horizontal = Space.s2, vertical = 2.dp),
        verticalArrangement = Arrangement.spacedBy(Space.s2),
    ) {
        Row(
            Modifier.clip(RoundedCornerShape(Radius.sm)).clickable(onClickLabel = if (folded) "Show steps" else "Hide steps") { collapsed = !folded }.padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Space.s2),
        ) {
            Box(Modifier.size(10.dp).clip(CircleShape).background(status))
            Txt(task.instruction.ifEmpty { "Starting…" }, Modifier.weight(1f, fill = false), weight = FontWeight.SemiBold, size = Type.caption, maxLines = 2)
            LineIcon("chev", p.muted, 16.dp, Modifier.rotate(if (folded) 0f else 90f))
        }
        if (!folded) {
            Column(Modifier.padding(start = 6.dp)) {
                (task.lines + listOfNotNull(liveLine(task))).forEach { line ->
                    val dot = when (line.tone) { Tone.OK -> p.success; Tone.WARN -> p.warning; Tone.RUN -> p.accent; Tone.BAD -> p.danger; Tone.INFO -> p.borderStrong }
                    Row(Modifier.padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
                        StepDot(dot, solid = line.tone != Tone.INFO, pulsing = line.tone == Tone.RUN)
                        Caption(line.text, Modifier.weight(1f).padding(start = Space.s2), color = p.text)
                        if (line.seconds > 0 || line.tone != Tone.RUN) Caption("%.1f s".format(line.seconds), Modifier.padding(start = Space.s2))
                    }
                }
            }
            if (task.summary.isNotEmpty()) MarkdownText(task.summary, Modifier.padding(start = 6.dp), size = Type.caption)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Btn("Open full trace", onTrace, look = Look.PLAIN, small = true)
                if (task.summary.isNotEmpty()) CopyButton(task.summary, what = "result")
            }
        }
    }
}

/** How much of the page colour the message box lays over what is behind it: 0 is clear glass, 1 hides it. */
private const val BOX_SMOKE = 0.45f

/**
 * A soft glow along the edge of a rounded box. Only the edge is drawn, so nothing fills the box: an ordinary shadow
 * would show through a see-through box as a haze inside it.
 */
private fun Modifier.neonEdge(color: Color, corner: Dp): Modifier = drawWithCache {
    val glow = android.graphics.Paint().apply {
        isAntiAlias = true
        style = android.graphics.Paint.Style.STROKE
        strokeWidth = 3.dp.toPx()
        this.color = color.copy(alpha = 0.7f).toArgb()
        maskFilter = android.graphics.BlurMaskFilter(7.dp.toPx(), android.graphics.BlurMaskFilter.Blur.NORMAL)
    }
    onDrawBehind { drawIntoCanvas { it.nativeCanvas.drawRoundRect(0f, 0f, size.width, size.height, corner.toPx(), corner.toPx(), glow) } }
}

/** A step's dot: solid, and pulsing while the step is running (purple), then green, orange or red when it ends. */
@Composable
private fun StepDot(color: Color, solid: Boolean, pulsing: Boolean) {
    val alpha = if (pulsing) {
        val transition = rememberInfiniteTransition(label = "step-dot")
        transition.animateFloat(1f, 0.35f, infiniteRepeatable(tween(800), RepeatMode.Reverse), label = "alpha").value
    } else 1f
    Box(
        Modifier.padding(top = 5.dp).size(10.dp).alpha(alpha).clip(CircleShape)
            .background(if (solid) color else Color.Transparent).border(2.dp, color, CircleShape),
    )
}

/**
 * Approval request. Allowing asks for the phone's fingerprint or lock-screen credential first, unless that check
 * was turned off in this device's settings; denying does not, because it cannot cause harm.
 */
@Composable
fun ApprovalCard(activity: MainActivity, approval: Approval, project: String, instruction: String) {
    val p = LocalPalette.current
    val live = activity.graph.live
    val scope = rememberCoroutineScope()
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(approval.id) {
        while (true) {
            now = System.currentTimeMillis()
            delay(1000)
        }
    }
    val left = maxOf(0L, (epochMillis(approval.expiresAt) - now) / 1000)
    val shell = approval.tool.startsWith("shell")
    val kind = if (shell) "shell command" else if (approval.tool == "fs.delete") "delete" else approval.tool
    val detail = (approval.arguments["command"] ?: approval.arguments["path"] ?: approval.arguments.toString()).toString()

    fun answer(decision: String) {
        busy = true
        error = null
        scope.launch {
            val ok = !approvalNeedsCheck(decision, activity.graph.prefs.approvalCheck) || activity.guard.confirm(
                if (decision == "allow_always") "Always allow ${approval.tool} in this chat" else "Allow this ${kind}",
                approval.summary,
            )
            if (ok) error = live.answer(approval, decision)
            busy = false
        }
    }

    Column(
        Modifier.widthIn(max = CARD_MAX).fillMaxWidth().clip(RoundedCornerShape(Radius.lg)).plate(p.bg, LocalMessageSolid.current, p.warning.copy(alpha = 0.08f))
            .border(1.dp, p.warning, RoundedCornerShape(Radius.lg)).padding(Space.s4),
        verticalArrangement = Arrangement.spacedBy(Space.s3),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Txt("Approval needed · $kind", Modifier.weight(1f), weight = FontWeight.SemiBold)
            Chip(if (left > 0) "%d:%02d left".format(left / 60, left % 60) else "expired", p.warning)
        }
        Txt(approval.summary)
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).background(p.bg).border(1.dp, p.border, RoundedCornerShape(Radius.md)).padding(Space.s3)) {
            Txt(detail, mono = true, size = Type.caption)
        }
        Caption("Runs in $project${if (instruction.isNotEmpty()) " · task “$instruction”" else ""} · asked by the main agent")
        Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
            Btn("Allow once", { answer("allow_once") }, look = Look.PRIMARY, enabled = !busy && left > 0, small = true)
            Btn("Always here", { answer("allow_always") }, enabled = !busy && left > 0, small = true)
            Btn("Deny", { answer("deny") }, look = Look.DANGER, enabled = !busy && left > 0, small = true)
        }
        error?.let { Caption(it, color = p.danger) }
        Caption(
            if (shell) "“Always” for shell lets this chat run any command without asking. You can revoke it in Tools."
            else "“Always” allows ${approval.tool} in this chat without asking. You can revoke it in Tools.",
        )
    }
}

/**
 * The pill message bar with the neon edge. It is smoked glass: what is behind it (the particle line, a message
 * scrolling past) shows through, dimmed so that what is typed in it stays easy to read. Drafts are kept per chat.
 * Mic: tap to start, tap again to send what you said. Speaker: read replies aloud on or off.
 * Direct: the chat's messages go straight to the main agent, word for word. Long-press Send to choose, or tap the pill.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun Composer(
    activity: MainActivity, initial: String, direct: Boolean,
    onDraft: (String) -> Unit, onSend: (String) -> Unit, onDirect: (Boolean) -> Unit,
) {
    val p = LocalPalette.current
    val voice = activity.graph.voice
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf(initial) }
    LaunchedEffect(text) {
        delay(400)
        onDraft(text)
    }
    val recording = voice.mode == VoiceMode.RECORDING
    val transcribing = voice.mode == VoiceMode.TRANSCRIBING
    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) voice.startRecording() else voice.error = "Microphone access was declined. Allow it in the phone's app settings to talk to Thursday."
    }
    fun mic() {
        when {
            recording -> scope.launch { voice.stopRecording().takeIf { it.isNotEmpty() }?.let(onSend) }
            transcribing -> Unit
            ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED -> voice.startRecording()
            else -> micPermission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    Column {
        voice.error?.let { Caption(it, Modifier.fillMaxWidth().padding(horizontal = Space.s4), color = p.danger) }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = Space.s3, vertical = Space.s2)
                .neonEdge(p.accent, 30.dp)
                .clip(RoundedCornerShape(30.dp)).background(p.bg.copy(alpha = BOX_SMOKE)).background(p.accent.copy(alpha = 0.08f))
                .border(1.dp, p.accent, RoundedCornerShape(30.dp)).padding(start = 6.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (voice.available) {
                Box(
                    Modifier.size(40.dp).clip(CircleShape).background(if (recording) p.accentFill else androidx.compose.ui.graphics.Color.Transparent)
                        .border(1.dp, if (recording) p.accent else androidx.compose.ui.graphics.Color.Transparent, CircleShape)
                        .clickable(enabled = !transcribing, onClickLabel = if (recording) "Stop and send what you said" else "Talk to Thursday") { mic() },
                    contentAlignment = Alignment.Center,
                ) { LineIcon("mic", if (recording) p.accentBright else p.muted, 20.dp) }
            }
            BasicTextField(
                text, { text = it },
                Modifier.weight(1f).padding(horizontal = Space.s2, vertical = 8.dp),
                enabled = !recording && !transcribing,
                textStyle = TextStyle(color = p.text, fontSize = Type.base),
                cursorBrush = SolidColor(p.accent),
                maxLines = 5,
                decorationBox = { inner ->
                    if (text.isEmpty()) Txt(if (recording) "Listening… tap the mic to send" else if (transcribing) "Writing down what you said…" else if (direct) "Message the main agent…" else "Message Thursday…", color = p.muted, maxLines = 1)
                    inner()
                },
            )
            if (voice.available) {
                Box(
                    Modifier.size(40.dp).clip(CircleShape).clickable(onClickLabel = "Read replies aloud") { voice.setSpeak(!voice.speakReplies) },
                    contentAlignment = Alignment.Center,
                ) { LineIcon(if (voice.speakReplies) "speaker" else "mute", if (voice.speakReplies) p.accentBright else p.muted, 20.dp) }
            }
            Box(
                Modifier.size(40.dp).clip(CircleShape)
                    .background(if (direct) p.accentFill else Color.Transparent)
                    .border(1.dp, if (direct) p.accent else Color.Transparent, CircleShape)
                    .clickable(onClickLabel = if (direct) "Send to the voice agent again" else "Send straight to the main agent") { onDirect(!direct) },
                contentAlignment = Alignment.Center,
            ) { LineIcon("direct", if (direct) p.accentBright else p.muted, 20.dp) }
            val can = text.isNotBlank() && !recording && !transcribing
            var menu by remember { mutableStateOf(false) }
            Box {
                Box(
                    Modifier.size(42.dp).clip(CircleShape).background(if (can) p.accentFill else Color.Transparent)
                        .border(1.dp, if (can) p.accent else p.border, CircleShape)
                        // A tap sends; a long press (allowed even when empty) chooses where this chat sends.
                        .combinedClickable(
                            onClickLabel = if (direct) "Send to the main agent" else "Send",
                            onLongClickLabel = "Choose where to send",
                            onClick = {
                                if (can) {
                                    onSend(text.trim())
                                    text = ""
                                }
                            },
                            onLongClick = { menu = true },
                        ),
                    contentAlignment = Alignment.Center,
                ) { LineIcon("send", if (can) p.accentBright else p.muted, 20.dp) }
                DropdownMenu(menu, { menu = false }, containerColor = p.bg) {
                    DropdownMenuItem(
                        text = { Txt((if (!direct) "✓  " else "     ") + "Send to the voice agent", size = Type.caption, color = if (!direct) p.accentBright else p.text) },
                        onClick = { menu = false; if (direct) onDirect(false) },
                    )
                    DropdownMenuItem(
                        text = { Txt((if (direct) "✓  " else "     ") + "Send straight to the main agent", size = Type.caption, color = if (direct) p.accentBright else p.text) },
                        onClick = { menu = false; if (!direct) onDirect(true) },
                    )
                }
            }
        }
    }
}
