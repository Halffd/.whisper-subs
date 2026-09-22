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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Forward30
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.Subtitles
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.runtime.mutableLongStateOf
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
import kotlinx.coroutines.delay

private val SPEED_OPTIONS = listOf(0.5f, 0.75f, 1.0f, 1.25f, 1.5f, 2.0f)
private val OFFSET_OPTIONS = listOf(-5000L, -2000L, -1000L, -500L, 0L, 500L, 1000L, 2000L, 5000L)

@OptIn(ExperimentalMaterial3Api::class, UnstableApi::class)
@Composable
fun PlayerScreen(
    itemId: String,
    sourceUrl: String,
    srtUrl: String,
    title: String,
    navController: NavController,
    mediaUrl: String = "",
) {
    val context = LocalContext.current
    val serverConfig = com.halffd.whispersubs.data.ServerConfig.getInstance(context)
    val apiClient = remember { ApiClient(serverConfig) }

    val exoPlayer = remember { ExoPlayer.Builder(context).build() }

    var isLoading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var srtBlocks by remember { mutableStateOf<List<SrtBlock>>(emptyList()) }
    var isLive by remember { mutableStateOf(false) }
    var playerError by remember { mutableStateOf<String?>(null) }
    var playbackSpeed by remember { mutableStateOf(1.0f) }
    var subtitleOffsetMs by remember { mutableLongStateOf(0L) }
    var showSubtitles by remember { mutableStateOf(true) }

    // Current playback position, polled for subtitle sync
    var positionMs by remember { mutableLongStateOf(0L) }
    LaunchedEffect(exoPlayer) {
        while (true) {
            positionMs = exoPlayer.currentPosition
            delay(250)
        }
    }

    LaunchedEffect(itemId, sourceUrl, srtUrl) {
        isLive = srtUrl.contains("/api/v1/tasks/") && srtUrl.contains("/subtitles/stream")

        // Fetch SRT (static for library, growing for live)
        if (srtUrl.isNotBlank() && !isLive) {
            apiClient.fetchSrtText(srtUrl).onSuccess { srt ->
                srtBlocks = SrtParser.parseSrt(srt)
            }
        }

        // Resolve playback source
        if (mediaUrl.isNotBlank()) {
            // Pre-downloaded file: play directly (no yt-dlp resolution)
            isLoading = false
            exoPlayer.setMediaItem(MediaItem.fromUri(mediaUrl))
            exoPlayer.prepare()
            exoPlayer.playWhenReady = true
        } else if (sourceUrl.isNotBlank()) {
            apiClient.getPlayInfo(sourceUrl, if (isLive) null else srtUrl)
                .onSuccess { resp ->
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
            apiClient.subscribeSse(
                taskId = itemId,
                onSegment = { segment ->
                    srtBlocks = srtBlocks + segment
                },
                onDone = { /* stream complete */ },
                onError = { msg -> playerError = msg },
            )
        }
    }

    // Apply playback speed changes
    LaunchedEffect(playbackSpeed) {
        exoPlayer.setPlaybackSpeed(playbackSpeed)
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

    // Current subtitle with offset applied at lookup time
    val currentSubtitle: SrtBlock? = if (showSubtitles && srtBlocks.isNotEmpty()) {
        val posSec = positionMs / 1000.0 + (subtitleOffsetMs / 1000.0)
        srtBlocks.firstOrNull { posSec >= it.start && posSec < it.end }
    } else {
        null
    }

    Column(modifier = Modifier.fillMaxSize().background(Color(0xFF0D1117))) {
        TopAppBar(
            title = {
                Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis, color = Color.White)
            },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = Color.Black),
            navigationIcon = {
                IconButton(onClick = { navController.popBackStack() }) {
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
                    Spacer(Modifier.height(8.dp))
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

            // Subtitle overlay (position-synced with offset)
            currentSubtitle?.let { block ->
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 96.dp, start = 16.dp, end = 16.dp),
                    contentAlignment = Alignment.BottomCenter
                ) {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = Color(0xCC000000)),
                        elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
                    ) {
                        Text(
                            text = block.text,
                            color = Color.White,
                            fontSize = 18.sp,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(16.dp)
                        )
                    }
                }
            }

            // For live streams without playback (SRT-only), show latest segment
            if (isLive && currentSubtitle == null && srtBlocks.isNotEmpty()) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 96.dp, start = 16.dp, end = 16.dp),
                    contentAlignment = Alignment.BottomCenter
                ) {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = Color(0xCC000000)),
                        elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
                    ) {
                        Text(
                            text = srtBlocks.last().text,
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
            PlayerControls(
                exoPlayer = exoPlayer,
                playbackSpeed = playbackSpeed,
                onSpeedChange = { playbackSpeed = it },
                subtitleOffsetMs = subtitleOffsetMs,
                onOffsetChange = { subtitleOffsetMs = it },
                showSubtitles = showSubtitles,
                onSubtitlesToggle = { showSubtitles = !showSubtitles },
            )
        }
    }
}

@Composable
fun PlayerControls(
    exoPlayer: ExoPlayer,
    playbackSpeed: Float,
    onSpeedChange: (Float) -> Unit,
    subtitleOffsetMs: Long,
    onOffsetChange: (Long) -> Unit,
    showSubtitles: Boolean,
    onSubtitlesToggle: () -> Unit,
) {
    var isPlaying by remember { mutableStateOf(exoPlayer.playWhenReady) }
    var showSpeedMenu by remember { mutableStateOf(false) }
    var showOffsetMenu by remember { mutableStateOf(false) }

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
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        IconButton(onClick = { exoPlayer.seekTo(maxOf(0L, exoPlayer.currentPosition - 10_000)) }) {
            Icon(Icons.Filled.Replay10, contentDescription = "Rewind 10s", tint = Color.White)
        }

        // Playback speed menu
        Box {
            DropdownMenu(
                expanded = showSpeedMenu,
                onDismissRequest = { showSpeedMenu = false }
            ) {
                SPEED_OPTIONS.forEach { speed ->
                    DropdownMenuItem(
                        text = { Text("${speed}x" + if (speed == playbackSpeed) " ✓" else "") },
                        onClick = {
                            onSpeedChange(speed)
                            showSpeedMenu = false
                        }
                    )
                }
            }
            IconButton(
                onClick = { showSpeedMenu = true },
                colors = IconButtonDefaults.iconButtonColors(
                    containerColor = if (playbackSpeed != 1.0f) MaterialTheme.colorScheme.primaryContainer else Color.Transparent
                )
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Filled.Speed,
                        contentDescription = "Playback speed: ${playbackSpeed}x",
                        tint = if (playbackSpeed != 1.0f) MaterialTheme.colorScheme.primary else Color.White,
                        modifier = Modifier.size(22.dp)
                    )
                    Text("${playbackSpeed}x", color = Color.White, fontSize = 9.sp)
                }
            }
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

        // Subtitle sync (offset) menu
        Box {
            DropdownMenu(
                expanded = showOffsetMenu,
                onDismissRequest = { showOffsetMenu = false }
            ) {
                OFFSET_OPTIONS.forEach { offset ->
                    DropdownMenuItem(
                        text = {
                            Text(
                                when {
                                    offset == 0L -> "No offset"
                                    offset > 0 -> "+${offset / 1000.0}s"
                                    else -> "${offset / 1000.0}s"
                                } + if (offset == subtitleOffsetMs) " ✓" else ""
                            )
                        },
                        onClick = {
                            onOffsetChange(offset)
                            showOffsetMenu = false
                        }
                    )
                }
            }
            IconButton(
                onClick = { showOffsetMenu = true },
                colors = IconButtonDefaults.iconButtonColors(
                    containerColor = if (subtitleOffsetMs != 0L) MaterialTheme.colorScheme.primaryContainer else Color.Transparent
                )
            ) {
                Icon(
                    Icons.Filled.Subtitles,
                    contentDescription = if (subtitleOffsetMs == 0L) "Subtitle sync" else "Subtitle offset: ${subtitleOffsetMs / 1000.0}s",
                    tint = if (subtitleOffsetMs != 0L) MaterialTheme.colorScheme.primary else Color.White,
                    modifier = Modifier.size(22.dp)
                )
            }
        }

        // Subtitle visibility toggle
        IconButton(onClick = onSubtitlesToggle) {
            Icon(
                Icons.Filled.Subtitles,
                contentDescription = if (showSubtitles) "Hide subtitles" else "Show subtitles",
                tint = if (showSubtitles) Color.White else Color.White.copy(alpha = 0.4f),
                modifier = Modifier.size(22.dp)
            )
        }

        IconButton(onClick = { exoPlayer.seekTo(exoPlayer.currentPosition + 30_000) }) {
            Icon(Icons.Filled.Forward30, contentDescription = "Forward 30s", tint = Color.White)
        }
    }

    // Offset info line
    if (subtitleOffsetMs != 0L) {
        Text(
            text = "Subtitle offset: " + (if (subtitleOffsetMs > 0) "+" else "") + "${subtitleOffsetMs / 1000.0}s",
            color = MaterialTheme.colorScheme.primary,
            fontSize = 11.sp,
            modifier = Modifier.fillMaxWidth().padding(start = 16.dp, bottom = 8.dp)
        )
    }
}