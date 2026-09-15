package com.halffd.whispersubs.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFF58A6FF),
    onPrimary = Color.Black,
    primaryContainer = Color(0xFF1F3A5F),
    onPrimaryContainer = Color.White,
    secondary = Color(0xFF8B949E),
    onSecondary = Color.Black,
    secondaryContainer = Color(0xFF21262D),
    onSecondaryContainer = Color.White,
    tertiary = Color(0xFFD29922),
    onTertiary = Color.Black,
    background = Color(0xFF0D1117),
    onBackground = Color(0xFFE6EDF3),
    surface = Color(0xFF161B22),
    onSurface = Color(0xFFE6EDF3),
    surfaceVariant = Color(0xFF21262D),
    onSurfaceVariant = Color(0xFF8B949E),
    outline = Color(0xFF30363D),
    error = Color(0xFFDA3633),
    onError = Color.White,
    errorContainer = Color(0xFF490202),
    onErrorContainer = Color(0xFFFFDAD6)
)

private val LightColorScheme = lightColorScheme(
    primary = Color(0xFF0969DA),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD0E5FF),
    onPrimaryContainer = Color.Black,
    secondary = Color(0xFF57606A),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE4E8EC),
    onSecondaryContainer = Color.Black,
    tertiary = Color(0xFF9A6700),
    onTertiary = Color.White,
    background = Color(0xFFFFFFFF),
    onBackground = Color(0xFF1F2328),
    surface = Color(0xFFF6F8FA),
    onSurface = Color(0xFF1F2328),
    surfaceVariant = Color(0xFFE4E8EC),
    onSurfaceVariant = Color(0xFF57606A),
    outline = Color(0xFF8B949E),
    error = Color(0xFFDA3633),
    onError = Color.White,
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF490202)
)

@Composable
fun WhisperSubsTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    val view = LocalContext.current
    if (!darkTheme && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        view.setTheme(android.R.style.Theme_Material_Light_NoActionBar)
    }
    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}

object Typography {
    val titleLarge = androidx.compose.material3.TypographyDefaults.titleLarge
    val titleMedium = androidx.compose.material3.TypographyDefaults.titleMedium
    val bodyLarge = androidx.compose.material3.TypographyDefaults.bodyLarge
    val bodyMedium = androidx.compose.material3.TypographyDefaults.bodyMedium
    val labelLarge = androidx.compose.material3.TypographyDefaults.labelLarge
}