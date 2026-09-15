package com.halffd.whispersubs.ui.local

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.ui.PlayerView
import androidx.navigation.NavController
import androidx.navigation.compose.findNavController
import android.content.Intent
import com.halffd.whispersubs.R
import com.halffd.whispersubs.local.TranscriptionService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

@Composable
fun LocalPlayerScreen(navController: NavController) {
    val context = LocalContext.current
    val exoPlayer = remember { createExoPlayer(context) }
    val isPlaying by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        onDispose { exoPlayer.release() }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(stringResource(R.string.local_tab), fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = Color.Black),
            navigationIcon = {
                IconButton(onClick = { navController.popBackStack() }) {
                    Icon(androidx.compose.material.icons.Icons.Default.ArrowBack, contentDescription = "Back", tint = Color.White)
                }
            }
        )

        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            // Show transcription results or live audio visualization
            Column(
                modifier = Modifier.fillMaxWidth().padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Icon(
                    androidx.compose.material.icons.Icons.Default.Mic,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    size = 80.dp
                )
                Spacer(Modifier.height(16.dp))
                Text(
                    text = "Live Transcription",
                    style = MaterialTheme.typography.headlineMedium,
                    color = Color.White
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    text = "Speak to transcribe...",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            // Player view for audio playback if needed
            AndroidView(
                factory = { ctx ->
                    PlayerView(ctx).apply {
                        player = exoPlayer
                        useController = true
                        controllerShowTimeoutMs = 3000
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(120.dp)
                    .background(Color.Black)
                    .padding(top = 16.dp)
            )
        }

        // Controls
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
                .background(Color(0xCC000000))
                .padding(16.dp, 8.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = {
                val intent = Intent(context, TranscriptionService::class.java).apply {
                    action = TranscriptionService.ACTION_PAUSE
                }
                context.startService(intent)
            }) {
                Icon(
                    androidx.compose.material.icons.Icons.Default.Pause,
                    contentDescription = "Pause",
                    tint = Color.White
                )
            }
            Spacer(Modifier.weight(1f))
            IconButton(
                onClick = {
                    val intent = Intent(context, TranscriptionService::class.java).apply {
                        action = TranscriptionService.ACTION_STOP
                    }
                    context.startService(intent)
                    navController.popBackStack()
                },
                colors = IconButtonDefaults.iconButtonColors(containerColor = MaterialTheme.colorScheme.error)
            ) {
                Icon(
                    androidx.compose.material.icons.Icons.Default.Stop,
                    contentDescription = "Stop",
                    tint = Color.White,
                    size = 32.dp
                )
            }
            Spacer(Modifier.weight(1f))
        }
    }
}

private fun createExoPlayer(context: android.content.Context): ExoPlayer {
    return ExoPlayer.Builder(context).build()
}