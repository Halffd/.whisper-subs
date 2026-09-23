package com.halffd.whispersubs.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
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
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit
) {
    val context = LocalContext.current
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }
    MaterialTheme(
        colorScheme = colorScheme,
        content = content
    )
}