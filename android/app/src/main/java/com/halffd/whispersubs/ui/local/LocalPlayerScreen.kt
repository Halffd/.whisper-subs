package com.halffd.whispersubs.ui.local

import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import com.halffd.whispersubs.R
import com.halffd.whispersubs.local.TranscriptionService
import com.halffd.whispersubs.local.TranscriptionService.TranscriptionState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LocalPlayerScreen(navController: NavController) {
    val context = LocalContext.current

    val state by TranscriptionService.sharedState.collectAsState()
    val segments by TranscriptionService.sharedSegments.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0D1117))
    ) {
        TopAppBar(
            title = {
                Text(
                    stringResource(R.string.local_tab),
                    fontWeight = FontWeight.Bold,
                    color = Color.White
                )
            },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = Color.Black),
            navigationIcon = {
                IconButton(onClick = { navController.popBackStack() }) {
                    Icon(Icons.Filled.ArrowBack, contentDescription = "Back", tint = Color.White)
                }
            }
        )

        // Status banner
        val statusText = when (state) {
            is TranscriptionState.Idle -> "Idle - start transcription from the Local tab"
            is TranscriptionState.Transcribing -> "Transcribing..."
            is TranscriptionState.Paused -> "Paused"
            is TranscriptionState.Completed -> "Completed"
            is TranscriptionState.Stopped -> "Stopped"
            is TranscriptionState.Error -> "Error: ${(state as TranscriptionState.Error).message}"
        }
        Text(
            text = statusText,
            color = when (state) {
                is TranscriptionState.Error -> MaterialTheme.colorScheme.error
                is TranscriptionState.Transcribing -> MaterialTheme.colorScheme.primary
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            },
            fontSize = 14.sp,
            modifier = Modifier.fillMaxWidth().padding(16.dp, 8.dp)
        )

        // Transcript feed (scrolling, live-updating)
        if (segments.isEmpty()) {
            Box(modifier = Modifier.weight(1f), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Filled.Mic,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(80.dp)
                    )
                    Spacer(Modifier.size(16.dp))
                    Text(
                        text = "Live Transcription",
                        style = MaterialTheme.typography.headlineMedium,
                        color = Color.White
                    )
                    Spacer(Modifier.size(8.dp))
                    Text(
                        text = "Segments appear here as they are transcribed",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center
                    )
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(segments) { segment ->
                    Card(
                        colors = CardDefaults.cardColors(containerColor = Color(0xFF161B22))
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Text(
                                text = formatTime(segment.startMs) + " - " + formatTime(segment.endMs),
                                fontSize = 11.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Spacer(Modifier.size(4.dp))
                            Text(
                                text = segment.text.trim(),
                                color = Color.White,
                                fontSize = 15.sp
                            )
                        }
                    }
                }
            }
        }

        // Pause / Stop controls
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Button(
                onClick = {
                    val intent = Intent(context, TranscriptionService::class.java).apply {
                        action = TranscriptionService.ACTION_PAUSE
                    }
                    context.startService(intent)
                },
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)
            ) {
                Icon(
                    if (state is TranscriptionState.Paused) Icons.Filled.PlayArrow else Icons.Filled.Pause,
                    contentDescription = if (state is TranscriptionState.Paused) "Resume" else "Pause",
                    modifier = Modifier.size(20.dp)
                )
                Spacer(Modifier.size(8.dp))
                Text(if (state is TranscriptionState.Paused) "Resume" else "Pause")
            }
            Button(
                onClick = {
                    val intent = Intent(context, TranscriptionService::class.java).apply {
                        action = TranscriptionService.ACTION_STOP
                    }
                    context.startService(intent)
                    navController.popBackStack()
                },
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.errorContainer)
            ) {
                Icon(Icons.Filled.Stop, contentDescription = "Stop", modifier = Modifier.size(20.dp))
                Spacer(Modifier.size(8.dp))
                Text("Stop")
            }
        }
    }
}

private fun formatTime(ms: Long): String {
    val totalSeconds = ms / 1000
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds)
    else "%02d:%02d".format(minutes, seconds)
}