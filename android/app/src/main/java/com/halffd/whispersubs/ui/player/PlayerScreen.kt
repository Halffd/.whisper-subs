package com.halffd.whispersubs.ui.player

import android.app.Activity
import android.app.PictureInPictureParams
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.media.AudioManager
import android.os.Build
import android.util.Rational
import android.widget.Toast
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Brightness6
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import androidx.navigation.NavController
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.ResumeStore
import com.halffd.whispersubs.data.SrtBlock
import com.halffd.whispersubs.player.SrtParser
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.roundToInt

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
    val activity = remember(context) { context as? Activity }
    val audioManager = remember(context) {
        context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
    }
    val resumeStore = remember { ResumeStore(context) }
    val scope = rememberCoroutineScope()

    // Key used to remember/restore playback position
    val resumeKey = itemId.ifBlank { if (sourceUrl.isNotBlank()) sourceUrl else mediaUrl }

    var isLoading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var srtBlocks by remember { mutableStateOf<List<SrtBlock>>(emptyList()) }
    var srtText by remember { mutableStateOf("") }
    var isLive by remember { mutableStateOf(false) }
    var playerError by remember { mutableStateOf<String?>(null) }
    var playbackSpeed by remember { mutableStateOf(1.0f) }
    var subtitleOffsetMs by remember { mutableLongStateOf(0L) }
    var showSubtitles by remember { mutableStateOf(true) }
    var isPlaying by remember { mutableStateOf(true) }

    // Controls overlay state
    var controlsVisible by remember { mutableStateOf(true) }
    var hideTick by remember { mutableLongStateOf(0L) }
    var isFullscreen by remember { mutableStateOf(false) }
    var isLocked by remember { mutableStateOf(false) }
    var showSpeedMenu by remember { mutableStateOf(false) }
    var showMoreMenu by remember { mutableStateOf(false) }
    var showJumpDialog by remember { mutableStateOf(false) }

    // A-B repeat (PotPlayer-style)
    var repeatA by remember { mutableStateOf<Long?>(null) }
    var repeatB by remember { mutableStateOf<Long?>(null) }

    // Scrubbing state
    var scrubbing by remember { mutableStateOf(false) }
    var scrubTargetMs by remember { mutableLongStateOf(0L) }

    // Gesture feedback indicators
    var seekFeedback by remember { mutableStateOf<SeekFeedback?>(null) }
    var gestureIndicator by remember { mutableStateOf<GestureIndicator?>(null) }

    // Poll playback position/buffered/duration for subtitle sync + seek bar,
    // and persist resume position every 5s while playing (PotPlayer-style)
    var positionMs by remember { mutableLongStateOf(0L) }
    var bufferedMs by remember { mutableLongStateOf(0L) }
    var durationMs by remember { mutableLongStateOf(0L) }
    LaunchedEffect(exoPlayer) {
        var lastSaveMs = 0L
        while (true) {
            positionMs = exoPlayer.currentPosition
            bufferedMs = exoPlayer.bufferedPosition
            val d = exoPlayer.duration
            durationMs = if (d > 0) d else 0L
            if (resumeKey.isNotBlank() && !isLive && exoPlayer.playWhenReady) {
                val now = System.currentTimeMillis()
                if (now - lastSaveMs > 5000) {
                    lastSaveMs = now
                    resumeStore.save(resumeKey, positionMs, durationMs)
                }
            }
            delay(250)
        }
    }

    // A-B repeat loop: snap back to A once playback passes B
    LaunchedEffect(exoPlayer, repeatA, repeatB) {
        val a = repeatA
        val b = repeatB
        if (a != null && b != null) {
            while (true) {
                if (exoPlayer.currentPosition >= b) exoPlayer.seekTo(a)
                delay(50)
            }
        }
    }

    // Auto-hide controls (YouTube-style)
    val anyMenuOpen = showSpeedMenu || showMoreMenu
    LaunchedEffect(controlsVisible, hideTick, anyMenuOpen, scrubbing) {
        if (controlsVisible && !anyMenuOpen && !scrubbing) {
            delay(CONTROLS_AUTO_HIDE_MS)
            controlsVisible = false
        }
    }

    fun bumpHide() {
        hideTick++
    }

    fun seekBy(deltaMs: Long) {
        val maxDur = exoPlayer.duration
        val target = exoPlayer.currentPosition + deltaMs
        exoPlayer.seekTo(if (maxDur > 0) target.coerceIn(0L, maxDur) else target.coerceAtLeast(0L))
    }

    var tapJob by remember { mutableStateOf<Job?>(null) }
    var lastTapTimeMs by remember { mutableLongStateOf(0L) }
    var lastTapX by remember { mutableFloatStateOf(0f) }

    // Double-tap seek (YouTube-style ±10s)
    fun handleDoubleTap(x: Float, boxWidth: Float) {
        tapJob?.cancel()
        val forward = x > boxWidth / 2f
        seekBy(if (forward) 10_000L else -10_000L)
        seekFeedback = SeekFeedback(forward, System.currentTimeMillis())
        bumpHide()
    }

    // Export/share current subtitles (SRT or plain text)
    fun shareSubtitles(format: String) {
        val content = when (format) {
            "txt" -> srtBlocks.joinToString("\n") { it.text }
            else -> srtText.ifBlank {
                // Live case: raw SRT was never fetched; rebuild from blocks
                srtBlocks.joinToString("\n") { b ->
                    "${b.index}\n${srtTimestamp(b.start)} --> ${srtTimestamp(b.end)}\n${b.text}\n"
                }
            }
        }
        if (content.isBlank()) {
            Toast.makeText(context, "No subtitles yet", Toast.LENGTH_SHORT).show()
            return
        }
        val sendIntent = Intent().apply {
            action = Intent.ACTION_SEND
            putExtra(Intent.EXTRA_TEXT, content)
            type = "text/plain"
        }
        context.startActivity(
            Intent.createChooser(sendIntent, "Share subtitles (${format.uppercase()})")
        )
    }

    // Resume position (PotPlayer-style continue)
    fun restoreResumePosition() {
        if (isLive || resumeKey.isBlank()) return
        val saved = resumeStore.load(resumeKey)
        if (saved > 0L) {
            exoPlayer.seekTo(saved)
            Toast.makeText(context, "Resumed from ${formatMs(saved)}", Toast.LENGTH_SHORT).show()
        }
    }

    // Subtitle-line navigation (PotPlayer Alt+Left/Right)
    fun seekToPrevSubtitle() {
        if (srtBlocks.isEmpty()) return
        val cur = positionMs / 1000.0
        val prev = srtBlocks.lastOrNull { it.start < cur - 0.5 }
        if (prev != null) {
            exoPlayer.seekTo((prev.start * 1000).toLong().coerceAtLeast(0L))
        } else {
            Toast.makeText(context, "No previous subtitle", Toast.LENGTH_SHORT).show()
        }
    }

    fun seekToNextSubtitle() {
        if (srtBlocks.isEmpty()) return
        val cur = positionMs / 1000.0
        val next = srtBlocks.firstOrNull { it.start > cur + 0.5 }
        if (next != null) {
            exoPlayer.seekTo((next.start * 1000).toLong())
        } else {
            Toast.makeText(context, "No next subtitle", Toast.LENGTH_SHORT).show()
        }
    }

    // Picture-in-picture (YouTube-style mini playback)
    fun enterPip() {
        val act = activity ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val params = PictureInPictureParams.Builder()
                .setAspectRatio(Rational(16, 9))
                .build()
            act.enterPictureInPictureMode(params)
        }
    }

    LaunchedEffect(itemId, sourceUrl, srtUrl) {
        isLive = srtUrl.contains("/api/v1/tasks/") && srtUrl.contains("/subtitles/stream")

        // Fetch SRT (static for library, growing for live)
        if (srtUrl.isNotBlank() && !isLive) {
            apiClient.fetchSrtText(srtUrl).onSuccess { srt ->
                srtText = srt
                srtBlocks = SrtParser.parseSrt(srt)
            }
        }

        // Resolve playback source
        if (mediaUrl.isNotBlank()) {
            // Pre-downloaded file: play directly (no yt-dlp resolution)
            isLoading = false
            controlsVisible = true
            exoPlayer.setMediaItem(MediaItem.fromUri(mediaUrl))
            exoPlayer.prepare()
            restoreResumePosition()
            exoPlayer.playWhenReady = true
        } else if (sourceUrl.isNotBlank()) {
            apiClient.getPlayInfo(sourceUrl, if (isLive) null else srtUrl)
                .onSuccess { resp ->
                    isLoading = false
                    controlsVisible = true
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
                    restoreResumePosition()
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

    // Player error + play-state listener
    DisposableEffect(exoPlayer) {
        val listener = object : Player.Listener {
            override fun onPlayerError(error: PlaybackException) {
                playerError = error.message
            }

            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
                isPlaying = playWhenReady
            }
        }
        exoPlayer.addListener(listener)
        onDispose {
            if (resumeKey.isNotBlank()) {
                val dur = exoPlayer.duration
                resumeStore.save(resumeKey, exoPlayer.currentPosition, if (dur > 0) dur else 0L)
            }
            exoPlayer.removeListener(listener)
            exoPlayer.release()
        }
    }

    // Fullscreen: landscape orientation + immersive system bars
    LaunchedEffect(isFullscreen) {
        val act = activity ?: return@LaunchedEffect
        val win = act.window
        val controller = WindowCompat.getInsetsController(win, win.decorView)
        if (isFullscreen) {
            act.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            WindowCompat.setDecorFitsSystemWindows(win, false)
            controller.systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller.hide(WindowInsetsCompat.Type.systemBars())
        } else {
            act.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
            WindowCompat.setDecorFitsSystemWindows(win, true)
            controller.show(WindowInsetsCompat.Type.systemBars())
        }
    }

    // Restore orientation + system bars when leaving the screen
    DisposableEffect(Unit) {
        onDispose {
            val win = activity?.window
            if (win != null) {
                val controller = WindowCompat.getInsetsController(win, win.decorView)
                activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                WindowCompat.setDecorFitsSystemWindows(win, true)
                controller.show(WindowInsetsCompat.Type.systemBars())
            }
        }
    }

    // Current subtitle with offset applied at lookup time
    val currentSubtitle: SrtBlock? = if (showSubtitles && srtBlocks.isNotEmpty()) {
        val posSec = positionMs / 1000.0 + (subtitleOffsetMs / 1000.0)
        srtBlocks.firstOrNull { posSec >= it.start && posSec < it.end }
    } else {
        null
    }

    // PiP: hide chrome/gestures, video fills the mini window
    val inPip = PipState.isInPip

    // Unified gesture handler: tap toggles controls, double-tap seeks ±10s,
    // horizontal drag scrubs, vertical drag adjusts brightness (left half) / volume (right half)
    val gestureModifier = Modifier.pointerInput(exoPlayer, isLive, inPip) {
        if (inPip) return@pointerInput
        val boxWidth = size.width.toFloat().coerceAtLeast(1f)
        val boxHeight = size.height.toFloat().coerceAtLeast(1f)
        val slop = viewConfiguration.touchSlop
        awaitEachGesture {
            val down = awaitFirstDown()
            if (down.isConsumed) return@awaitEachGesture
            var isTap = true
            var dragging = false
            var mode = 0 // 0=scrub, 1=brightness, 2=volume
            var scrubStartMs = 0L
            var startVolume = 0
            var startBrightness = 0.5f
            var accumX = 0f
            var accumY = 0f
            while (true) {
                val event = awaitPointerEvent()
                val change = event.changes.firstOrNull() ?: break
                if (!change.pressed) {
                    // Gesture ended
                    if (isTap && !change.isConsumed) {
                        val now = System.currentTimeMillis()
                        if (now - lastTapTimeMs < DOUBLE_TAP_WINDOW_MS &&
                            abs(down.position.x - lastTapX) < 120f
                        ) {
                            // Double tap: seek ±10s
                            lastTapTimeMs = 0L
                            if (!isLocked) handleDoubleTap(down.position.x, boxWidth)
                        } else {
                            lastTapTimeMs = now
                            lastTapX = down.position.x
                            if (isLocked) {
                                controlsVisible = !controlsVisible
                                bumpHide()
                            } else {
                                // Delay so a follow-up tap can register as double-tap
                                tapJob?.cancel()
                                tapJob = scope.launch {
                                    delay(DOUBLE_TAP_WINDOW_MS)
                                    controlsVisible = !controlsVisible
                                    bumpHide()
                                }
                            }
                        }
                    }
                    break
                }
                val dx = change.positionChange().x
                val dy = change.positionChange().y
                accumX += dx
                accumY += dy
                if (!dragging && !isLocked &&
                    (abs(accumX) > slop || abs(accumY) > slop)
                ) {
                    isTap = false
                    dragging = true
                    mode = when {
                        abs(accumX) >= abs(accumY) -> 0
                        down.position.x < boxWidth / 2f -> 1
                        else -> 2
                    }
                    when (mode) {
                        0 -> {
                            scrubStartMs = exoPlayer.currentPosition
                            scrubbing = true
                        }
                        1 -> {
                            val attrs = activity?.window?.attributes
                            startBrightness = attrs?.screenBrightness?.takeIf { it >= 0f } ?: 0.5f
                        }
                        else -> {
                            startVolume = audioManager
                                ?.getStreamVolume(AudioManager.STREAM_MUSIC) ?: 0
                        }
                    }
                }
                if (dragging) {
                    when (mode) {
                        0 -> {
                            if (durationMs > 0) {
                                val target = scrubStartMs + (accumX / boxWidth * durationMs).toLong()
                                scrubTargetMs = target.coerceIn(0L, durationMs)
                                exoPlayer.seekTo(scrubTargetMs)
                            }
                        }
                        1 -> {
                            val act = activity
                            if (act != null) {
                                val value = (startBrightness - accumY / boxHeight).coerceIn(0.01f, 1f)
                                act.window.attributes =
                                    act.window.attributes.apply { screenBrightness = value }
                                gestureIndicator =
                                    GestureIndicator(false, value, System.currentTimeMillis())
                            }
                        }
                        else -> {
                            val am = audioManager
                            if (am != null) {
                                val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                                val value = (startVolume - accumY / boxHeight * max)
                                    .roundToInt().coerceIn(0, max)
                                am.setStreamVolume(AudioManager.STREAM_MUSIC, value, 0)
                                gestureIndicator =
                                    GestureIndicator(true, value / max.toFloat(), System.currentTimeMillis())
                            }
                        }
                    }
                    change.consume()
                }
            }
            if (dragging && mode == 0) {
                scrubbing = false
                controlsVisible = true
                bumpHide()
            }
        }
    }

    Box(modifier = Modifier.fillMaxSize().background(Color(0xFF0D1117))) {
        Column(modifier = Modifier.fillMaxSize()) {
            if (!isFullscreen && !inPip) {
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
            }

            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                Box(
                    modifier = Modifier
                        .then(
                            if (isFullscreen || inPip) Modifier.fillMaxSize()
                            else Modifier.fillMaxWidth().aspectRatio(16f / 9f)
                        )
                        .background(Color.Black)
                        .then(gestureModifier)
                ) {
                    // Video surface (controls handled by our overlay, not PlayerView)
                    AndroidView(
                        factory = { ctx ->
                            PlayerView(ctx).apply {
                                player = exoPlayer
                                useController = false
                            }
                        },
                        modifier = Modifier.fillMaxSize()
                    )

                    // Double-tap seek indicator (YouTube-style ripple)
                    seekFeedback?.let { fb ->
                        val alphaAnim = remember(fb.timestamp) { Animatable(1f) }
                        LaunchedEffect(fb.timestamp) {
                            alphaAnim.animateTo(0f, animationSpec = tween(700, easing = LinearEasing))
                        }
                        Box(
                            modifier = Modifier
                                .align(if (fb.forward) Alignment.CenterEnd else Alignment.CenterStart)
                                .fillMaxHeight(0.55f)
                                .fillMaxWidth(0.28f)
                                .graphicsLayer { alpha = alphaAnim.value }
                                .background(Color(0x66FFFFFF), RoundedCornerShape(24.dp)),
                            contentAlignment = Alignment.Center
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Icon(
                                    if (fb.forward) Icons.Filled.Forward10 else Icons.Filled.Replay10,
                                    contentDescription = null,
                                    tint = Color.White,
                                    modifier = Modifier.size(40.dp)
                                )
                                Text(
                                    if (fb.forward) "+10s" else "-10s",
                                    color = Color.White,
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.Medium
                                )
                            }
                        }
                    }

                    // Brightness/volume gesture indicator
                    gestureIndicator?.let { gi ->
                        val alphaAnim = remember(gi.timestamp) { Animatable(1f) }
                        LaunchedEffect(gi.timestamp) {
                            delay(500)
                            alphaAnim.animateTo(0f, animationSpec = tween(400, easing = LinearEasing))
                        }
                        Box(
                            modifier = Modifier
                                .align(Alignment.Center)
                                .graphicsLayer { alpha = alphaAnim.value }
                                .background(Color(0x99000000), RoundedCornerShape(16.dp))
                                .padding(20.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Icon(
                                    if (gi.isVolume) Icons.Filled.VolumeUp else Icons.Filled.Brightness6,
                                    contentDescription = null,
                                    tint = Color.White,
                                    modifier = Modifier.size(32.dp)
                                )
                                Spacer(Modifier.height(10.dp))
                                Box(
                                    Modifier
                                        .width(140.dp)
                                        .height(6.dp)
                                        .background(Color.White.copy(alpha = 0.3f), RoundedCornerShape(3.dp))
                                ) {
                                    Box(
                                        Modifier
                                            .fillMaxWidth(gi.value.coerceIn(0f, 1f))
                                            .fillMaxHeight()
                                            .background(Color.White, RoundedCornerShape(3.dp))
                                    )
                                }
                                Spacer(Modifier.height(6.dp))
                                Text(
                                    "${(gi.value * 100).roundToInt()}%",
                                    color = Color.White,
                                    fontSize = 12.sp
                                )
                            }
                        }
                    }

                    // Scrub position preview
                    if (scrubbing) {
                        Text(
                            text = formatMs(scrubTargetMs),
                            color = Color.White,
                            fontSize = 24.sp,
                            fontWeight = FontWeight.Medium,
                            modifier = Modifier
                                .align(Alignment.Center)
                                .background(Color(0x99000000), RoundedCornerShape(10.dp))
                                .padding(horizontal = 16.dp, vertical = 8.dp)
                        )
                    }

                    // Subtitle overlay (position-synced with offset)
                    currentSubtitle?.let { block ->
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .align(Alignment.BottomCenter)
                                .padding(
                                    bottom = if (controlsVisible) 120.dp else 32.dp,
                                    start = 16.dp,
                                    end = 16.dp
                                ),
                            contentAlignment = Alignment.BottomCenter
                        ) {
                            androidx.compose.material3.Card(
                                colors = androidx.compose.material3.CardDefaults.cardColors(
                                    containerColor = Color(0xCC000000)
                                ),
                                elevation = androidx.compose.material3.CardDefaults.cardElevation(
                                    defaultElevation = 8.dp
                                )
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
                                .padding(
                                    bottom = if (controlsVisible) 120.dp else 32.dp,
                                    start = 16.dp,
                                    end = 16.dp
                                ),
                            contentAlignment = Alignment.BottomCenter
                        ) {
                            androidx.compose.material3.Card(
                                colors = androidx.compose.material3.CardDefaults.cardColors(
                                    containerColor = Color(0xCC000000)
                                ),
                                elevation = androidx.compose.material3.CardDefaults.cardElevation(
                                    defaultElevation = 8.dp
                                )
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

                    // Loading / error states
                    if (isLoading) {
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            CircularProgressIndicator(color = Color.White)
                        }
                    } else if (error != null) {
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier.padding(24.dp)
                            ) {
                                Text(
                                    text = error ?: "",
                                    color = MaterialTheme.colorScheme.error,
                                    textAlign = TextAlign.Center
                                )
                                Spacer(Modifier.height(8.dp))
                                Text(
                                    text = "Subtitles still stream if available",
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    fontSize = 12.sp
                                )
                            }
                        }
                    }

                    // Full YouTube/PotPlayer-style controls overlay
                    VideoControlsOverlay(
                        exoPlayer = exoPlayer,
                        isPlaying = isPlaying,
                        title = title,
                        isLive = isLive,
                        isFullscreen = isFullscreen,
                        visible = controlsVisible && !isLoading && error == null && !inPip,
                        locked = isLocked,
                        playbackSpeed = playbackSpeed,
                        subtitleOffsetMs = subtitleOffsetMs,
                        showSubtitles = showSubtitles,
                        repeatA = repeatA,
                        repeatB = repeatB,
                        positionMs = positionMs,
                        bufferedMs = bufferedMs,
                        durationMs = durationMs,
                        scrubbing = scrubbing,
                        scrubTargetMs = scrubTargetMs,
                        showSpeedMenu = showSpeedMenu,
                        onSpeedMenu = { showSpeedMenu = it },
                        showMoreMenu = showMoreMenu,
                        onMoreMenu = { showMoreMenu = it },
                        onBack = {
                            if (isFullscreen) isFullscreen = false else navController.popBackStack()
                        },
                        onToggleFullscreen = { isFullscreen = !isFullscreen },
                        onTogglePlay = { exoPlayer.playWhenReady = !isPlaying },
                        onSkip = { delta -> seekBy(delta) },
                        onScrubFraction = { fraction ->
                            if (durationMs > 0) {
                                scrubbing = true
                                scrubTargetMs =
                                    (fraction * durationMs).toLong().coerceIn(0L, durationMs)
                                exoPlayer.seekTo(scrubTargetMs)
                            }
                        },
                        onScrubEnd = {
                            scrubbing = false
                            controlsVisible = true
                            bumpHide()
                        },
                        onSpeedChange = { playbackSpeed = it },
                        onOffsetChange = { subtitleOffsetMs = it },
                        onSubtitlesToggle = { showSubtitles = !showSubtitles },
                        onSetRepeatA = {
                            repeatA = positionMs
                            bumpHide()
                        },
                        onSetRepeatB = {
                            val a = repeatA
                            if (a != null && positionMs <= a) {
                                // B before A: swap so the region stays valid
                                repeatB = a
                                repeatA = positionMs
                            } else {
                                repeatB = positionMs
                            }
                            bumpHide()
                        },
                        onClearRepeat = {
                            repeatA = null
                            repeatB = null
                            bumpHide()
                        },
                        onJumpDialog = { showJumpDialog = true },
                        onShare = { fmt -> shareSubtitles(fmt) },
                        onPrevSubtitle = { seekToPrevSubtitle() },
                        onNextSubtitle = { seekToNextSubtitle() },
                        onPip = { enterPip() },
                        onToggleLock = { isLocked = !isLocked },
                        onInteraction = { bumpHide() },
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            }
        }

        // PotPlayer-style jump-to-time dialog
        if (showJumpDialog) {
            JumpToTimeDialog(
                onDismiss = { showJumpDialog = false },
                onJump = { t ->
                    exoPlayer.seekTo(if (durationMs > 0) t.coerceIn(0L, durationMs) else t)
                    showJumpDialog = false
                }
            )
        }
    }
}

/** SRT timestamp: HH:MM:SS,mmm */
private fun srtTimestamp(sec: Double): String {
    val totalMs = (sec * 1000).toLong()
    val h = totalMs / 3_600_000
    val m = (totalMs % 3_600_000) / 60_000
    val s = (totalMs % 60_000) / 1000
    val ms = totalMs % 1000
    return "%02d:%02d:%02d,%03d".format(h, m, s, ms)
}
