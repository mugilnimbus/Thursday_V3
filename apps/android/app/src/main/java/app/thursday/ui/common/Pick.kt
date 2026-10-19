package app.thursday.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.thursday.data.ApiException
import app.thursday.data.FolderListing
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space
import app.thursday.ui.theme.Type

/** A drop-down list of (value, label) choices, like the dashboard's select. Shows the chosen label. */
@Composable
fun Pick(
    label: String,
    options: List<Pair<String, String>>,
    selected: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    mono: Boolean = false,
) {
    val p = LocalPalette.current
    var open by remember { mutableStateOf(false) }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(Space.s1)) {
        Txt(label, color = p.muted, size = Type.caption, weight = FontWeight.SemiBold)
        Box {
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.md)).border(1.dp, p.borderStrong, RoundedCornerShape(Radius.md))
                    .clickable { open = true }.padding(horizontal = Space.s3, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Txt(options.firstOrNull { it.first == selected }?.second ?: selected, Modifier.weight(1f), maxLines = 1, mono = mono, size = if (mono) Type.caption else Type.base)
                LineIcon("chev", p.muted, 16.dp)
            }
            DropdownMenu(open, { open = false }, Modifier.background(p.panelTop).heightIn(max = 360.dp)) {
                options.forEach { (value, text) ->
                    DropdownMenuItem(
                        text = { Txt(text, color = if (value == selected) p.accentBright else p.text, mono = mono, size = if (mono) Type.caption else Type.base) },
                        onClick = { open = false; onSelect(value) },
                    )
                }
            }
        }
    }
}

/**
 * Browse the folders of the PC (never files) and pick one. `load` asks the gateway for a folder's sub-folders.
 * Where another program keeps its models (LM Studio) is offered as a shortcut at the top.
 */
@Composable
fun FolderBrowser(start: String, load: suspend (String) -> FolderListing, onPick: (String) -> Unit, onCancel: () -> Unit) {
    val p = LocalPalette.current
    var listing by remember { mutableStateOf<FolderListing?>(null) }
    var target by remember { mutableStateOf<String?>(start) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(target) {
        val to = target ?: return@LaunchedEffect
        try {
            // An empty start means the PC user's home folder; the drives are one step up from any drive root.
            listing = if (to.isEmpty() && listing == null) load(load("").home) else load(to)
            error = null
        } catch (e: ApiException) {
            error = e.message
        }
    }
    val current = listing
    Column(verticalArrangement = Arrangement.spacedBy(Space.s2)) {
        Txt(current?.path?.ifEmpty { "This PC" } ?: "…", mono = true, size = Type.caption)
        error?.let { Caption(it, color = p.danger) }
        current?.modelFolders?.filter { it.path != current.path }?.forEach { shortcut ->
            ListBox {
                ListRow(onClick = { target = shortcut.path }) {
                    LineIcon("folder", p.accentBright, 18.dp)
                    Column(Modifier.weight(1f)) {
                        Txt(shortcut.name, weight = FontWeight.Medium, maxLines = 1)
                        Caption(shortcut.path, maxLines = 2)
                    }
                    LineIcon("chev", p.muted, 16.dp)
                }
            }
        }
        if (current != null) ListBox {
            current.parent?.let { parent ->
                ListRow(onClick = { target = parent }) {
                    LineIcon("back", p.muted, 18.dp)
                    Caption(if (parent.isEmpty()) "This PC (drives)" else "Up one folder")
                }
            }
            current.folders.forEach { folder ->
                ListRow(onClick = { target = folder.path }) {
                    LineIcon("folder", p.accentBright, 18.dp)
                    Txt(folder.name, Modifier.weight(1f), maxLines = 1)
                    LineIcon("chev", p.muted, 16.dp)
                }
            }
            if (current.folders.isEmpty()) ListRow { Caption("No folders inside this one.") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(Space.s2)) {
            Btn("Use this folder", { current?.path?.let(onPick) }, look = Look.PRIMARY, small = true, enabled = !current?.path.isNullOrEmpty())
            Btn("Cancel", onCancel, look = Look.PLAIN, small = true)
        }
    }
}
