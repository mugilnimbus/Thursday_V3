package app.thursday.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/* Colors and scales from the shared design system (apps/dashboard/src/lib/styles/tokens.css). */

@Immutable
data class Palette(
    val bg: Color,
    val text: Color,
    val muted: Color,
    val border: Color,
    val borderStrong: Color,
    val accent: Color,
    val accentBright: Color,
    val accentFill: Color,
    val accentSoft: Color,
    val success: Color,
    val warning: Color,
    val danger: Color,
    val panelTop: Color,
    val calm: Color = Color(0xFF2DD4BF),
    val info: Color = Color(0xFF4D8DFF),
    val warm: Color = Color(0xFFF5B544),
    val alert: Color = Color(0xFFFF5C8A),
    val dark: Boolean,
)

val Black = Palette(
    bg = Color(0xFF000000), text = Color(0xFFF6F3FB), muted = Color(0xFFBDB5CB), border = Color(0xFF2B2637),
    borderStrong = Color(0xFF463D5C), accent = Color(0xFF9B63FF), accentBright = Color(0xFFC9A8FF),
    accentFill = Color(0x2E9B63FF), accentSoft = Color(0x1F9B63FF), success = Color(0xFF72EDB0),
    warning = Color(0xFFF1C96C), danger = Color(0xFFFF6D91), panelTop = Color(0x249B63FF), dark = true,
)

val White = Palette(
    bg = Color(0xFFFFFFFF), text = Color(0xFF100E16), muted = Color(0xFF4B4557), border = Color(0xFFD9D2E6),
    borderStrong = Color(0xFF8D81A6), accent = Color(0xFF6A2FD0), accentBright = Color(0xFF4C1D95),
    accentFill = Color(0x1A6A2FD0), accentSoft = Color(0x146A2FD0), success = Color(0xFF0F6B41),
    warning = Color(0xFF7A4B00), danger = Color(0xFFA51C40), panelTop = Color(0xFFF3EDFF),
    calm = Color(0xFF0D9488), info = Color(0xFF2563EB), warm = Color(0xFFD97706), alert = Color(0xFFE11D48), dark = false,
)

object Space {
    val s1 = 4.dp
    val s2 = 8.dp
    val s3 = 13.dp
    val s4 = 21.dp
    val s5 = 34.dp
}

object Radius {
    val sm = 8.dp
    val md = 13.dp
    val lg = 21.dp
}

object Type {
    val caption = 13.sp
    val base = 16.sp
    val title = 21.sp
    val large = 26.sp
    val mono = FontFamily.Monospace
}

val LocalPalette = staticCompositionLocalOf { Black }

@Composable
fun ThursdayTheme(theme: String, content: @Composable () -> Unit) {
    val p = if (theme == "white") White else Black
    val scheme = if (p.dark) {
        darkColorScheme(primary = p.accent, onPrimary = Color.White, background = p.bg, surface = p.bg, onBackground = p.text, onSurface = p.text, error = p.danger, outline = p.borderStrong)
    } else {
        lightColorScheme(primary = p.accent, onPrimary = Color.White, background = p.bg, surface = p.bg, onBackground = p.text, onSurface = p.text, error = p.danger, outline = p.borderStrong)
    }
    val body = TextStyle(fontSize = Type.base, color = p.text, fontWeight = if (p.dark) FontWeight.Normal else FontWeight.Medium, lineHeight = 22.sp)
    CompositionLocalProvider(LocalPalette provides p) {
        MaterialTheme(colorScheme = scheme, typography = MaterialTheme.typography.copy(bodyLarge = body, bodyMedium = body), content = content)
    }
}
