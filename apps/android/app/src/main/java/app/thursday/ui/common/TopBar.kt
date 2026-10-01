package app.thursday.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.thursday.ui.theme.LocalPalette
import app.thursday.ui.theme.Space

@Composable
fun TopBar(title: String, onBack: (() -> Unit)? = null, actions: @Composable RowScope.() -> Unit = {}) {
    val p = LocalPalette.current
    Column {
        Row(
            Modifier.fillMaxWidth().height(52.dp).padding(horizontal = Space.s2),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Space.s2),
        ) {
            if (onBack != null) IconButton("back", "Back", onBack) else Box(Modifier.size(Space.s2))
            Txt(title, Modifier.weight(1f), weight = FontWeight.SemiBold, maxLines = 1)
            actions()
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(p.border))
    }
}

@Composable
fun IconButton(icon: String, label: String, onClick: () -> Unit, tint: androidx.compose.ui.graphics.Color? = null) {
    val p = LocalPalette.current
    Box(
        Modifier.size(40.dp).clip(RoundedCornerShape(8.dp)).clickable(onClickLabel = label, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { LineIcon(icon, tint ?: p.muted) }
}
