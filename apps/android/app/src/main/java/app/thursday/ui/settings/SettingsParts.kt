package app.thursday.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.thursday.ui.common.Btn
import app.thursday.ui.common.Caption
import app.thursday.ui.common.LineIcon
import app.thursday.ui.common.ListBox
import app.thursday.ui.common.Look
import app.thursday.ui.common.Panel
import app.thursday.ui.common.SectionTitle
import app.thursday.ui.common.TopBar
import app.thursday.ui.common.Txt
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Radius
import app.thursday.ui.theme.Space

// The layout pieces every settings page is built from.

/** One settings page: a title bar with Back, an optional Save at the top right, and its settings in a scrolling column. */
@Composable
internal fun SettingsPage(
    title: String,
    onBack: () -> Unit,
    save: (() -> Unit)? = null,
    saveEnabled: Boolean = false,
    saveLabel: String = "Save",
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        TopBar(title, onBack = if (LocalBesideList.current) null else onBack) {
            if (save != null) Btn(saveLabel, save, look = if (saveEnabled) Look.PRIMARY else Look.PLAIN, enabled = saveEnabled, small = true)
        }
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(Space.s4),
            verticalArrangement = Arrangement.spacedBy(Space.s3),
            content = content,
        )
    }
}

/** A row of the settings list: an icon, a title, a line saying how it is set now, and a chevron. `marked`: its page is open beside the list. */
@Composable
internal fun ListEntry(icon: String, title: String, summary: String, marked: Boolean = false, onClick: () -> Unit) {
    val p = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().defaultMinSize(minHeight = 64.dp).background(if (marked) p.accentSoft else Color.Transparent).clickable(onClick = onClick)
            .padding(horizontal = Space.s3, vertical = Space.s2),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Space.s3),
    ) {
        Box(Modifier.size(36.dp).clip(RoundedCornerShape(Radius.md)).background(p.accentFill), contentAlignment = Alignment.Center) {
            LineIcon(icon, p.accentBright, 20.dp)
        }
        Column(Modifier.weight(1f)) {
            Txt(title, weight = FontWeight.Medium, maxLines = 1)
            if (summary.isNotEmpty()) Caption(summary, maxLines = 1)
        }
        LineIcon("chev", p.muted, 16.dp)
    }
}

@Composable
internal fun Divider() = Box(Modifier.fillMaxWidth().padding(start = 64.dp).height(1.dp).background(LocalPalette.current.border))

/** A group of list rows under a small heading. */
@Composable
internal fun ListGroup(title: String, rows: List<@Composable () -> Unit>) {
    Column(verticalArrangement = Arrangement.spacedBy(Space.s2)) {
        SectionTitle(title, Modifier.padding(start = Space.s2))
        ListBox {
            rows.forEachIndexed { index, row ->
                if (index > 0) Divider()
                row()
            }
        }
    }
}

/** A titled group of settings on a page. */
@Composable
internal fun Group(title: String, content: @Composable ColumnScope.() -> Unit) {
    Panel(Modifier.fillMaxWidth()) {
        SectionTitle(title)
        content()
    }
}

/** Two settings side by side. */
@Composable
internal fun Side(left: @Composable (Modifier) -> Unit, right: @Composable (Modifier) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(Space.s3)) {
        left(Modifier.weight(1f))
        right(Modifier.weight(1f))
    }
}

@Composable
internal fun SwitchRow(title: String, help: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    val p = LocalPalette.current
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Space.s3)) {
        Column(Modifier.weight(1f)) {
            Txt(title)
            Caption(help)
        }
        Switch(checked, onChange, colors = SwitchDefaults.colors(checkedTrackColor = p.accentFill, checkedThumbColor = p.accentBright, checkedBorderColor = p.accent))
    }
}

@Composable
internal fun RowScope.Fill() = Box(Modifier.weight(1f))
