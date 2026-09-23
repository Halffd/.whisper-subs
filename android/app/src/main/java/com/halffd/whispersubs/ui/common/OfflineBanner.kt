package com.halffd.whispersubs.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.WifiOff
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

/**
 * Banner shown when content came from [OfflineCache] because the server
 * was unreachable. Recomputes the age label every minute.
 */
@Composable
fun OfflineBanner(cachedAtMs: Long?, onRefresh: () -> Unit) {
    if (cachedAtMs == null) return

    var nowMs by remember(cachedAtMs) { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(cachedAtMs) {
        while (true) {
            delay(60_000)
            nowMs = System.currentTimeMillis()
        }
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.tertiaryContainer)
            .padding(horizontal = 16.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            Icons.Filled.WifiOff,
            contentDescription = "Offline",
            tint = MaterialTheme.colorScheme.onTertiaryContainer,
            modifier = Modifier.size(18.dp)
        )
        Spacer(Modifier.width(10.dp))
        Text(
            text = "Offline — cached data from ${formatAge(nowMs - cachedAtMs)}",
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onTertiaryContainer,
            modifier = Modifier.weight(1f)
        )
        TextButton(onClick = onRefresh) {
            Text("Refresh", fontSize = 13.sp)
        }
    }
}

internal fun formatAge(ms: Long): String {
    val seconds = (ms / 1000).coerceAtLeast(0)
    return when {
        seconds < 60 -> "just now"
        seconds < 3600 -> "${seconds / 60}m ago"
        seconds < 86400 -> "${seconds / 3600}h ago"
        else -> "${seconds / 86400}d ago"
    }
}
