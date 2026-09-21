package com.halffd.whispersubs.ui.player

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Forward30
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import androidx.navigation.NavController
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.PlayResponse
import com.halffd.whispersubs.data.SrtBlock
import com.halffd.whispersubs.player.SrtParser

@OptIn(ExperimentalMaterial3Api::class, UnstableApi::class)
@Composable
fun PlayerScreen(
    itemId: String,
    sourceUrl: String,
    srtUrl: String,
    title: String,
    navController: NavController,
) {
    val context = LocalContext.current
    val serverConfig = com.halffd.whispersubs.data.ServerConfig.getInstance(context)
    val apiClient = remember { ApiClient(serverConfig) }

    val exoPlayer = remember { ExoPlayer.Builder(context).build() }

    var playResponse by remember { mutableStateOf<PlayResponse?>(null) }
    var isLoading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var srtBlocks by remember { mutableStateOf<List<SrtBlock>>(emptyList()) }
    var isLive by remember { mutableStateOf(false) }
    var playerError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(itemId, sourceUrl, srtUrl) {
        isLive = srtUrl.contains("/api/v1/tasks/") && srtUrl.contains("/subtitles/stream")

        // Fetch SRT (static for library, growing for live)
        if (srtUrl.isNotBlank() && !isLive) {
            apiClient.fetchSrtText(srtUrl).onSuccess { srt ->
                srtBlocks = SrtParser.parseSrt(srt)
            }
        }

        // Resolve playback source
        if (sourceUrl.isNotBlank()) {
            apiClient.getPlayInfo(sourceUrl, if (isLive) null else srtUrl)
                .onSuccess { resp ->
                    playResponse = resp
                    isLoading = false
                    val playUrl = apiClient.absoluteUrl(resp.play_url)
                    val mediaItem = if (resp.protocol == "hls") {
                        MediaItem.fromUri(playUrl).buildUpon()
                            .setMimeType("application/x-mpegURL")
                            .build()
                    } else {
                        MediaItem.fromUri(playUrl)
                    }
                    exoPlayer.setMediaItem(mediaItem)
                    exoPlayer.prepare()
                    exoPlayer.playWhenReady = true
                }
                .onFailure { e ->
                    isLoading = false
                    error = e.message ?: "Failed to resolve stream"
                }
        } else {
            isLoading = false
            error = "No playback source available"
        }

        // Subscribe to SSE for live transcription
        if (isLive) {
            val taskId = itemId
            apiClient.subscribeSse(
                taskId = taskId,
                onSegment = { segment ->
                    srtBlocks = srtBlocks + segment
                },
                onDone = { /* stream complete */ },
                onError = { msg -> playerError = msg },
            )
        }
    }

    // Player error listener
    DisposableEffect(exoPlayer) {
        val listener = object : Player.Listener {
            override fun onPlayerError(error: PlaybackException) {
                playerError = error.message
            }
        }
        exoPlayer.addListener(listener)
        onDispose {
            exoPlayer.removeListener(listener)
            exoPlayer.release()
        }
    }

    Column(modifier = Modifier.fillMaxSize().background(Color(0xFF0D1117))) {
        TopAppBar(
            title = {
                Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis, color = Color.White)
            },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = Color.Black),
            navigationIcon = {
                IconButton(onClick = {
                    navController.popBackStack()
                }) {
                    Icon(Icons.Filled.ArrowBack, contentDescription = "Back", tint = Color.White)
                }
            }
        )

        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            if (isLoading) {
                CircularProgressIndicator(color = Color.White)
            } else if (error != null) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(24.dp)) {
                    Text(
                        text = error ?: "",
                        color = MaterialTheme.colorScheme.error,
                        textAlign = TextAlign.Center
                    )
                    Spacer(Modifier.size(8.dp))
                    Text(
                        text = "Subtitles still stream below if available",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 12.sp
                    )
                }
            } else {
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
                        .aspectRatio(16f / 9f)
                        .background(Color.Black)
                )
            }

            // Live subtitle overlay (bottom)
            if (srtBlocks.isNotEmpty()) {
                val latest = srtBlocks.last()
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 96.dp),
                    contentAlignment = Alignment.BottomCenter
                ) {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = Color(0xCC000000)),
                        elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
                    ) {
                        Text(
                            text = latest.text,
                            color = Color.White,
                            fontSize = 18.sp,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(16.dp)
                        )
                    }
                }
            }

            playerError?.let { msg ->
                Text(
                    text = msg,
                    color = MaterialTheme.colorScheme.error,
                    fontSize = 12.sp,
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .padding(8.dp)
                )
            }
        }

        if (!isLoading && error == null) {
            PlayerControls(exoPlayer = exoPlayer)
        }
    }
}

@Composable
fun PlayerControls(exoPlayer: ExoPlayer) {
    var isPlaying by remember { mutableStateOf(exoPlayer.playWhenReady) }

    DisposableEffect(exoPlayer) {
        val listener = object : Player.Listener {
            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
                isPlaying = playWhenReady
            }
        }
        exoPlayer.addListener(listener)
        onDispose { exoPlayer.removeListener(listener) }
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        IconButton(onClick = { exoPlayer.seekTo(exoPlayer.currentPosition - 10_000) }) {
            Icon(Icons.Filled.Replay10, contentDescription = "Rewind 10s", tint = Color.White)
        }
        Spacer(Modifier.weight(1f))
        IconButton(
            onClick = { exoPlayer.playWhenReady = !isPlaying },
            colors = IconButtonDefaults.iconButtonColors(containerColor = MaterialTheme.colorScheme.primary)
        ) {
            Icon(
                if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                contentDescription = if (isPlaying) "Pause" else "Play",
                tint = Color.White,
                modifier = Modifier.size(32.dp)
            )
        }
        Spacer(Modifier.weight(1f))
        IconButton(onClick = { exoPlayer.seekTo(exoPlayer.currentPosition + 30_000) }) {
            Icon(Icons.Filled.Forward30, contentDescription = "Forward 30s", tint = Color.White)
        }
    }
}