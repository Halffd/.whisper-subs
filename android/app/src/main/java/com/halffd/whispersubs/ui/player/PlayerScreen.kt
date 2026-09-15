package com.halffd.whispersubs.ui.player

import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.media3.common.MimeTypes
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.exoplayer.source.hls.HlsMediaSource
import androidx.media3.exoplayer.text.Cue
import androidx.media3.exoplayer.text.SubtitleView
import androidx.media3.exoplayer.ui.PlayerView
import androidx.media3.ui.PlayerControlView
import androidx.navigation.NavController
import androidx.navigation.compose.findNavController
import com.google.android.exoplayer2.source.MediaSourceFactory
import com.halffd.whispersubs.R
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.PlayResponse
import com.halffd.whispersubs.data.SrtBlock
import com.halffd.whispersubs.data.SubtitleSnapshot
import com.halffd.whispersubs.player.SrtParser
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.*

@OptIn(UnstableApi::class)
@Composable
fun PlayerScreen(
    itemId: String,
    sourceUrl: String,
    srtUrl: String,
    title: String
) {
    val context = LocalContext.current
    val apiClient: ApiClient = hiltViewModel()
    val navController = findNavController()

    val exoPlayer = remember { createExoPlayer(context) }
    val playResponse by remember { mutableStateOf<PlayResponse?>(null) }
    val isLoading by remember { mutableStateOf(true) }
    val error by remember { mutableStateOf<String?>(null) }
    val srtBlocks by remember { mutableStateOf<List<SrtBlock>>(emptyList()) }
    val isLive by remember { mutableStateOf(false) }
    val showSubtitles by remember { mutableStateOf(true) }

    // Load play info and SRT
    LaunchedEffect(Unit) {
        loadPlayInfo()
        loadSrt()
    }

    fun loadPlayInfo() {
        isLive = srtUrl.contains("/api/v1/tasks/") && srtUrl.contains("/subtitles/stream")
        if (sourceUrl.isNotBlank()) {
            kotlinx.coroutines.CoroutineScope(Dispatchers.IO).launch {
                val result = apiClient.getPlayInfo(sourceUrl, srtUrl)
                kotlinx.coroutines.withContext(Dispatchers.Main) {
                    result.onSuccess { playResponse = it
                        isLoading = false
                        preparePlayer(it)
                    }.onFailure { e ->
                        isLoading = false
                        error = e.message ?: "Failed to load"
                    }
                }
            }
        } else {
            // Local media - use srtUrl directly
            isLoading = false
            prepareLocalPlayer()
        }
    }

    fun loadSrt() {
        kotlinx.coroutines.CoroutineScope(Dispatchers.IO).launch {
            val baseUrl = com.halffd.whispersubs.data.ServerConfig.getInstance(context).getApiEndpoint()
            val fullSrtUrl = if (srtUrl.startsWith("http")) srtUrl else "$baseUrl$srtUrl"
            val request = Request.Builder().url(fullSrtUrl).build()
            val client = OkHttpClient()
            val response = client.newCall(request).execute()
            if (response.isSuccessful) {
                val body = response.body?.string() ?: ""
                val blocks = SrtParser.parseSrt(body)
                kotlinx.coroutines.withContext(Dispatchers.Main) {
                    srtBlocks = blocks
                }
            }
        }
    }

    fun preparePlayer(response: PlayResponse) {
        val playUrl = response.play_url
        val mediaItem = when {
            playUrl.contains("m3u8") || response.protocol == "hls" -> {
                MediaItem.fromUri(Uri.parse(playUrl))
            }
            response.protocol == "https" && playUrl.contains("/api/v1/proxy") -> {
                // Use our proxy which supports Range
                MediaItem.fromUri(Uri.parse(playUrl))
            }
            else -> MediaItem.fromUri(Uri.parse(playUrl))
        }
        exoPlayer.setMediaItem(mediaItem)
        exoPlayer.prepare()
        exoPlayer.playWhenReady = true
    }

    fun prepareLocalPlayer() {
        val baseUrl = com.halffd.whispersubs.data.ServerConfig.getInstance(context).getApiEndpoint()
        val mediaUrl = srtUrl.replace("/subs/file", "/media/file")
        val mediaItem = MediaItem.fromUri(Uri.parse("$baseUrl$mediaUrl"))
        exoPlayer.setMediaItem(mediaItem)
        exoPlayer.prepare()
        exoPlayer.playWhenReady = true
    }

    // SSE subscription for live subtitles
    LaunchedEffect(isLive) {
        if (isLive && playResponse?.srt_url != null) {
            val taskId = itemId
            val job = CoroutineScope(Dispatchers.IO).launch {
                val channel = apiClient.connectSse(taskId)
                while (true) {
                    val segment = channel.receive()
                    kotlinx.coroutines.withContext(Dispatchers.Main) {
                        srtBlocks = srtBlocks + segment
                    }
                }
            }
            onDispose { job.cancel() }
        }
    }

    // Update subtitle overlay with latest block
    LaunchedEffect(srtBlocks) {
        if (!srtBlocks.isEmpty() && exoPlayer.playWhenReady) {
            // Subtitle view is handled by PlayerView automatically for sidecar subs
            // For live overlay we render manually below
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(title, maxLines = 1, overflow = androidx.compose.ui.text.TextOverflow.Ellipsis) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = Color.Black),
            navigationIcon = {
                IconButton(onClick = { navController.popBackStack() }) {
                    Icon(androidx.compose.material.icons.Icons.Default.ArrowBack, contentDescription = "Back", tint = Color.White)
                }
            }
        )

        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            if (isLoading) {
                CircularProgressIndicator(color = Color.White)
            } else if (error != null) {
                Text(text = error!!, color = MaterialTheme.colorScheme.error, textAlign = androidx.compose.ui.text.TextAlign.Center, modifier = Modifier.padding(24.dp))
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

                // Live subtitle overlay
                if (isLive && srtBlocks.isNotEmpty() && showSubtitles) {
                    val latest = srtBlocks.last()
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp)
                            .align(Alignment.BottomCenter),
                        contentAlignment = Alignment.BottomCenter
                    ) {
                        Card(
                            modifier = Modifier.padding(bottom = 100.dp),
                            colors = CardDefaults.cardColors(containerColor = Color(0xCC000000)),
                            elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
                        ) {
                            Text(
                                text = latest.text,
                                color = Color.White,
                                fontSize = 18.sp,
                                style = MaterialTheme.typography.bodyLarge,
                                textAlign = androidx.compose.ui.text.TextAlign.Center,
                                modifier = Modifier.padding(16.dp)
                            )
                        }
                    }
                }
            }
        }

        // Controls
        if (!isLoading && error == null) {
            PlayerControls(exoPlayer = exoPlayer)
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            exoPlayer.release()
        }
    }
}

@Composable
fun PlayerControls(exoPlayer: ExoPlayer) {
    val isPlaying = remember { mutableStateOf(exoPlayer.playWhenReady) }
    LaunchedEffect(exoPlayer) {
        exoPlayer.addListener(object : Player.Listener {
            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
                isPlaying.value = playWhenReady
            }
        })
        onDispose { exoPlayer.removeListener(this) }
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp)
            .background(Color(0xCC000000))
            .padding(16.dp, 8.dp),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        IconButton(onClick = { exoPlayer.seekTo(exoPlayer.currentPosition - 10_000) }) {
            Icon(androidx.compose.material.icons.Icons.Default.Replay10, contentDescription = "Rewind 10s", tint = Color.White)
        }
        Spacer(Modifier.weight(1f))
        IconButton(
            onClick = { exoPlayer.playWhenReady = !isPlaying.value },
            colors = IconButtonDefaults.iconButtonColors(containerColor = MaterialTheme.colorScheme.primary)
        ) {
            Icon(
                if (isPlaying.value) androidx.compose.material.icons.Icons.Default.Pause else androidx.compose.material.icons.Icons.Default.PlayArrow,
                contentDescription = if (isPlaying.value) "Pause" else "Play",
                tint = Color.White,
                size = 32.dp
            )
        }
        Spacer(Modifier.weight(1f))
        IconButton(onClick = { exoPlayer.seekTo(exoPlayer.currentPosition + 30_000) }) {
            Icon(androidx.compose.material.icons.Icons.Default.Forward30, contentDescription = "Forward 30s", tint = Color.White)
        }
    }
}

private fun createExoPlayer(context: Context): ExoPlayer {
    return ExoPlayer.Builder(context).build()
}