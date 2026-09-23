package com.halffd.whispersubs.ui.player

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Brightness6
import androidx.compose.material.icons.filled.ClosedCaption
import androidx.compose.material.icons.filled.ClosedCaptionOff
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.Forward30
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.FullscreenExit
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.Replay30
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import kotlinx.coroutines.delay
import kotlin.math.abs
import kotlin.math.roundToInt

internal const val CONTROLS_AUTO_HIDE_MS = 3500L
internal const val DOUBLE_TAP_WINDOW_MS = 300L
private const val MAX_OFFSET_MS = 30_000L
private val SPEED_OPTIONS = listOf(0.25f, 0.5f, 0.75f, 1.0f, 1.25f, 1.5f, 1.75f, 2.0f, 2.5f, 3.0f)
private val OFFSET_PRESETS = listOf(-10_000L, -5000L, -2000L, -1000L, 0L, 1000L, 2000L, 5000L, 10_000L)
private val AB_COLOR = Color(0xFFFF5252)

/** Double-tap seek feedback (YouTube-style ±10s ripple). */
data class SeekFeedback(val forward: Boolean, val timestamp: Long)

/** Brightness/volume gesture feedback. */
data class GestureIndicator(val isVolume: Boolean, val value: Float, val timestamp: Long)

/** Formats ms as m:ss or h:mm:ss. */
fun formatMs(ms: Long): String {
    val totalSeconds = ms / 1000
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds)
    else "%d:%02d".format(minutes, seconds)
}

/** Parses "mm:ss" or "hh:mm:ss" (or bare seconds) into milliseconds. */
fun parseTimeInput(input: String): Long? {
    val parts = input.trim().split(":").map { it.trim().filter { c -> c.isDigit() } }
    if (parts.isEmpty() || parts.any { it.isEmpty() }) return null
    val nums = parts.mapNotNull { it.toLongOrNull() }
    if (nums.size != parts.size) return null
    val seconds = when (nums.size) {
        1 -> nums[0]
        2 -> nums[0] * 60 + nums[1]
        3 -> nums[0] * 3600 + nums[1] * 60 + nums[2]
        else -> return null
    }
    return if (seconds >= 0) seconds * 1000 else null
}

private fun speedLabel(speed: Float): String =
    if (speed % 1f == 0f) "${speed.toInt()}x" else "${speed}x"

private fun offsetLabel(ms: Long): String = when {
    ms == 0L -> "No offset (sync)"
    ms > 0 -> "+${ms / 1000.0}s"
    else -> "${ms / 1000.0}s"
}

/**
 * Full YouTube/PotPlayer-style controls overlay.
 *
 * Auto-hides after [CONTROLS_AUTO_HIDE_MS]; tap toggles visibility. Includes:
 * - Custom seek bar with buffered track, draggable thumb, and A-B repeat markers
 * - Center play/pause with ±10s/±30s skips (±10s hidden for live)
 * - Speed menu (0.25x-3x), CC toggle, more menu (jump to time, A-B repeat, subtitle sync)
 * - Fullscreen toggle, lock mode
 *
 * Gestures (tap, double-tap seek, scrub, brightness/volume drags) are handled by the
 * parent video container so the overlay's background stays gesture-transparent.
 */
@OptIn(UnstableApi::class)
@Composable
fun VideoControlsOverlay(
    exoPlayer: ExoPlayer,
    isPlaying: Boolean,
    title: String,
    isLive: Boolean,
    isFullscreen: Boolean,
    visible: Boolean,
    locked: Boolean,
    playbackSpeed: Float,
    subtitleOffsetMs: Long,
    showSubtitles: Boolean,
    repeatA: Long?,
    repeatB: Long?,
    positionMs: Long,
    bufferedMs: Long,
    durationMs: Long,
    scrubbing: Boolean,
    scrubTargetMs: Long,
    showSpeedMenu: Boolean,
    onSpeedMenu: (Boolean) -> Unit,
    showMoreMenu: Boolean,
    onMoreMenu: (Boolean) -> Unit,
    onBack: () -> Unit,
    onToggleFullscreen: () -> Unit,
    onTogglePlay: () -> Unit,
    onSkip: (Long) -> Unit,
    onScrubFraction: (Float) -> Unit,
    onScrubEnd: () -> Unit,
    onSpeedChange: (Float) -> Unit,
    onOffsetChange: (Long) -> Unit,
    onSubtitlesToggle: () -> Unit,
    onSetRepeatA: () -> Unit,
    onSetRepeatB: () -> Unit,
    onClearRepeat: () -> Unit,
    onJumpDialog: () -> Unit,
    onToggleLock: () -> Unit,
    onInteraction: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (!visible) return

    // ===== Lock mode: only unlock pill =====
    if (locked) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Box(
                modifier = Modifier
                    .background(Color(0x99000000), RoundedCornerShape(24.dp))
                    .clickable { onToggleLock() }
                    .padding(horizontal = 24.dp, vertical = 16.dp),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Filled.Lock,
                        contentDescription = "Unlock controls",
                        tint = Color.White,
                        modifier = Modifier.size(36.dp)
                    )
                    Spacer(Modifier.height(6.dp))
                    Text("Tap to unlock", color = Color.White, fontSize = 12.sp)
                }
            }
        }
        return
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    0f to Color.Black.copy(alpha = 0.65f),
                    0.2f to Color.Transparent,
                    0.72f to Color.Transparent,
                    1f to Color.Black.copy(alpha = 0.75f)
                )
            )
    ) {
        // ===== Top row: back + title =====
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.TopCenter)
                .padding(horizontal = 4.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = { onBack(); onInteraction() }) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "Back", tint = Color.White)
            }
            Text(
                text = title,
                color = Color.White,
                fontSize = 16.sp,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f)
            )
        }

        // ===== Center controls: ±10s/±30s flanking play/pause =====
        Row(
            modifier = Modifier.fillMaxSize(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (!isLive) {
                IconButton(onClick = { onSkip(-30_000L); onInteraction() }) {
                    Icon(Icons.Filled.Replay30, contentDescription = "Back 30s", tint = Color.White)
                }
                Spacer(Modifier.width(12.dp))
                IconButton(onClick = { onSkip(-10_000L); onInteraction() }) {
                    Icon(Icons.Filled.Replay10, contentDescription = "Back 10s", tint = Color.White)
                }
                Spacer(Modifier.width(24.dp))
            }
            IconButton(onClick = { onTogglePlay(); onInteraction() }) {
                Icon(
                    if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                    contentDescription = if (isPlaying) "Pause" else "Play",
                    tint = Color.White,
                    modifier = Modifier.size(64.dp)
                )
            }
            if (!isLive) {
                Spacer(Modifier.width(24.dp))
                IconButton(onClick = { onSkip(10_000L); onInteraction() }) {
                    Icon(Icons.Filled.Forward10, contentDescription = "Forward 10s", tint = Color.White)
                }
                Spacer(Modifier.width(12.dp))
                IconButton(onClick = { onSkip(30_000L); onInteraction() }) {
                    Icon(Icons.Filled.Forward30, contentDescription = "Forward 30s", tint = Color.White)
                }
            }
        }

        // ===== Bottom: seek bar + time + buttons =====
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomCenter)
                .padding(horizontal = 12.dp, vertical = 8.dp)
        ) {
            if (!isLive) {
                val displayPos = if (scrubbing) scrubTargetMs else positionMs
                SeekBarTrack(
                    durationMs = durationMs,
                    positionMs = displayPos,
                    bufferedMs = bufferedMs,
                    repeatA = repeatA,
                    repeatB = repeatB,
                    onSeekFraction = onScrubFraction,
                    onScrubEnd = onScrubEnd,
                    onInteraction = onInteraction,
                )
                Spacer(Modifier.height(2.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(formatMs(displayPos), color = Color.White, fontSize = 12.sp)
                    Text(" / ", color = Color.White.copy(alpha = 0.6f), fontSize = 12.sp)
                    Text(formatMs(durationMs), color = Color.White.copy(alpha = 0.6f), fontSize = 12.sp)
                    if (repeatA != null && repeatB != null) {
                        Spacer(Modifier.width(10.dp))
                        Icon(
                            Icons.Filled.Replay10,
                            contentDescription = "A-B repeat active",
                            tint = AB_COLOR,
                            modifier = Modifier.size(14.dp)
                        )
                        Text(
                            "${formatMs(repeatA)}-${formatMs(repeatB)}",
                            color = AB_COLOR,
                            fontSize = 11.sp
                        )
                    }
                    Spacer(Modifier.weight(1f))
                    SpeedButton(showSpeedMenu, onSpeedMenu, playbackSpeed, onSpeedChange, onInteraction)
                    SubtitlesButton(showSubtitles, onSubtitlesToggle, onInteraction)
                    MoreMenuButton(
                        expanded = showMoreMenu,
                        onExpanded = onMoreMenu,
                        isLive = isLive,
                        repeatA = repeatA,
                        repeatB = repeatB,
                        subtitleOffsetMs = subtitleOffsetMs,
                        onOffsetChange = onOffsetChange,
                        onSetRepeatA = onSetRepeatA,
                        onSetRepeatB = onSetRepeatB,
                        onClearRepeat = onClearRepeat,
                        onJumpDialog = onJumpDialog,
                        onInteraction = onInteraction,
                    )
                    FullscreenButton(isFullscreen, onToggleFullscreen, onInteraction)
                }
            } else {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("LIVE", color = AB_COLOR, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                    Spacer(Modifier.weight(1f))
                    SpeedButton(showSpeedMenu, onSpeedMenu, playbackSpeed, onSpeedChange, onInteraction)
                    SubtitlesButton(showSubtitles, onSubtitlesToggle, onInteraction)
                    MoreMenuButton(
                        expanded = showMoreMenu,
                        onExpanded = onMoreMenu,
                        isLive = isLive,
                        repeatA = repeatA,
                        repeatB = repeatB,
                        subtitleOffsetMs = subtitleOffsetMs,
                        onOffsetChange = onOffsetChange,
                        onSetRepeatA = onSetRepeatA,
                        onSetRepeatB = onSetRepeatB,
                        onClearRepeat = onClearRepeat,
                        onJumpDialog = onJumpDialog,
                        onInteraction = onInteraction,
                    )
                    FullscreenButton(isFullscreen, onToggleFullscreen, onInteraction)
                }
            }
        }
    }
}

@Composable
private fun SpeedButton(
    expanded: Boolean,
    onExpanded: (Boolean) -> Unit,
    speed: Float,
    onSpeedChange: (Float) -> Unit,
    onInteraction: () -> Unit,
) {
    Box {
        DropdownMenu(expanded = expanded, onDismissRequest = { onExpanded(false) }) {
            SPEED_OPTIONS.forEach { option ->
                DropdownMenuItem(
                    text = { Text(speedLabel(option) + if (option == speed) " ✓" else "") },
                    onClick = {
                        onSpeedChange(option)
                        onExpanded(false)
                        onInteraction()
                    }
                )
            }
        }
        IconButton(onClick = { onExpanded(true); onInteraction() }) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(
                    Icons.Filled.Speed,
                    contentDescription = "Playback speed: ${speedLabel(speed)}",
                    tint = if (speed != 1.0f) MaterialTheme.colorScheme.primary else Color.White,
                    modifier = Modifier.size(20.dp)
                )
                Text(speedLabel(speed), color = Color.White, fontSize = 9.sp)
            }
        }
    }
}

@Composable
private fun SubtitlesButton(
    show: Boolean,
    onToggle: () -> Unit,
    onInteraction: () -> Unit,
) {
    IconButton(onClick = { onToggle(); onInteraction() }) {
        Icon(
            if (show) Icons.Filled.ClosedCaption else Icons.Filled.ClosedCaptionOff,
            contentDescription = if (show) "Hide subtitles" else "Show subtitles",
            tint = if (show) Color.White else Color.White.copy(alpha = 0.45f),
            modifier = Modifier.size(22.dp)
        )
    }
}

@Composable
private fun MoreMenuButton(
    expanded: Boolean,
    onExpanded: (Boolean) -> Unit,
    isLive: Boolean,
    repeatA: Long?,
    repeatB: Long?,
    subtitleOffsetMs: Long,
    onOffsetChange: (Long) -> Unit,
    onSetRepeatA: () -> Unit,
    onSetRepeatB: () -> Unit,
    onClearRepeat: () -> Unit,
    onJumpDialog: () -> Unit,
    onInteraction: () -> Unit,
) {
    Box {
        DropdownMenu(expanded = expanded, onDismissRequest = { onExpanded(false) }) {
            DropdownMenuItem(
                text = { Text("Jump to time…") },
                onClick = {
                    onExpanded(false)
                    onJumpDialog()
                    onInteraction()
                }
            )
            if (!isLive) {
                HorizontalDivider()
                DropdownMenuItem(
                    text = { Text("Subtitle sync: 0.5s earlier") },
                    onClick = {
                        onOffsetChange((subtitleOffsetMs - 500L).coerceIn(-MAX_OFFSET_MS, MAX_OFFSET_MS))
                        onExpanded(false)
                        onInteraction()
                    }
                )
                DropdownMenuItem(
                    text = { Text("Subtitle sync: 0.5s later") },
                    onClick = {
                        onOffsetChange((subtitleOffsetMs + 500L).coerceIn(-MAX_OFFSET_MS, MAX_OFFSET_MS))
                        onExpanded(false)
                        onInteraction()
                    }
                )
                DropdownMenuItem(
                    text = { Text("Subtitle sync: reset" + if (subtitleOffsetMs != 0L) " (now ${offsetLabel(subtitleOffsetMs)})" else "") },
                    onClick = {
                        onOffsetChange(0L)
                        onExpanded(false)
                        onInteraction()
                    }
                )
                HorizontalDivider()
                DropdownMenuItem(
                    text = { Text("Set A-B start" + (repeatA?.let { " @ ${formatMs(it)}" } ?: " at playhead")) },
                    onClick = {
                        onSetRepeatA()
                        onExpanded(false)
                        onInteraction()
                    }
                )
                DropdownMenuItem(
                    text = { Text("Set A-B end" + (repeatB?.let { " @ ${formatMs(it)}" } ?: " at playhead")) },
                    onClick = {
                        onSetRepeatB()
                        onExpanded(false)
                        onInteraction()
                    }
                )
                if (repeatA != null || repeatB != null) {
                    DropdownMenuItem(
                        text = { Text("Clear A-B repeat") },
                        onClick = {
                            onClearRepeat()
                            onExpanded(false)
                            onInteraction()
                        }
                    )
                }
            }
        }
        IconButton(onClick = { onExpanded(true); onInteraction() }) {
            Icon(Icons.Filled.MoreVert, contentDescription = "More options", tint = Color.White)
        }
    }
}

@Composable
private fun FullscreenButton(
    fullscreen: Boolean,
    onToggle: () -> Unit,
    onInteraction: () -> Unit,
) {
    IconButton(onClick = { onToggle(); onInteraction() }) {
        Icon(
            if (fullscreen) Icons.Filled.FullscreenExit else Icons.Filled.Fullscreen,
            contentDescription = if (fullscreen) "Exit fullscreen" else "Enter fullscreen",
            tint = Color.White
        )
    }
}

/**
 * Custom seek bar: buffered track, played track, draggable thumb, A-B repeat markers.
 * Tap seeks; horizontal drag scrubs continuously (live seek via [onSeekFraction]).
 */
@Composable
private fun SeekBarTrack(
    durationMs: Long,
    positionMs: Long,
    bufferedMs: Long,
    repeatA: Long?,
    repeatB: Long?,
    onSeekFraction: (Float) -> Unit,
    onScrubEnd: () -> Unit,
    onInteraction: () -> Unit,
) {
    var widthPx by remember { mutableFloatStateOf(1f) }
    val playedFraction = if (durationMs > 0) (positionMs.toFloat() / durationMs).coerceIn(0f, 1f) else 0f
    val bufferedFraction = if (durationMs > 0) (bufferedMs.toFloat() / durationMs).coerceIn(0f, 1f) else 0f
    val hasRepeat = repeatA != null && repeatB != null && durationMs > 0

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(28.dp)
            .onSizeChanged { widthPx = it.width.toFloat().coerceAtLeast(1f) }
            .pointerInput(durationMs) {
                detectTapGestures { offset ->
                    onInteraction()
                    onSeekFraction((offset.x / widthPx).coerceIn(0f, 1f))
                }
            }
            .pointerInput(durationMs) {
                detectHorizontalDragGestures(
                    onDragStart = { onInteraction() },
                    onDragEnd = { onScrubEnd() },
                    onDragCancel = { onScrubEnd() },
                ) { change, _ ->
                    onSeekFraction((change.position.x / widthPx).coerceIn(0f, 1f))
                    change.consume()
                }
            },
        contentAlignment = Alignment.CenterStart
    ) {
        // Track background
        Box(
            Modifier
                .fillMaxWidth()
                .height(4.dp)
                .background(Color.White.copy(alpha = 0.25f), RoundedCornerShape(2.dp))
        )
        // Buffered track
        if (bufferedFraction > 0f) {
            Box(
                Modifier
                    .fillMaxWidth(bufferedFraction)
                    .height(4.dp)
                    .background(Color.White.copy(alpha = 0.4f), RoundedCornerShape(2.dp))
            )
        }
        // A-B repeat region
        if (hasRepeat) {
            val startFrac = (repeatA / durationMs.toFloat()).coerceIn(0f, 1f)
            val regionWidth = ((repeatB / durationMs.toFloat()).coerceIn(0f, 1f) - startFrac).coerceAtLeast(0f)
            if (regionWidth > 0f) {
                Box(
                    Modifier
                        .offset { IntOffset((startFrac * widthPx).roundToInt(), 0) }
                        .fillMaxWidth(regionWidth)
                        .fillMaxHeight()
                        .background(AB_COLOR.copy(alpha = 0.3f))
                )
            }
        }
        // Played track (above A-B region)
        Box(
            Modifier
                .fillMaxWidth(playedFraction)
                .height(4.dp)
                .background(Color.White, RoundedCornerShape(2.dp))
        )
        // A / B markers
        repeatA?.let { a ->
            if (durationMs > 0) {
                val frac = (a / durationMs.toFloat()).coerceIn(0f, 1f)
                Box(
                    Modifier
                        .offset { IntOffset(((frac * widthPx) - 1.5.dp.toPx()).roundToInt(), 0) }
                        .fillMaxHeight()
                        .width(3.dp)
                        .background(AB_COLOR)
                )
            }
        }
        repeatB?.let { b ->
            if (durationMs > 0) {
                val frac = (b / durationMs.toFloat()).coerceIn(0f, 1f)
                Box(
                    Modifier
                        .offset { IntOffset(((frac * widthPx) - 1.5.dp.toPx()).roundToInt(), 0) }
                        .fillMaxHeight()
                        .width(3.dp)
                        .background(AB_COLOR)
                )
            }
        }
        // Thumb
        Box(
            Modifier
                .offset { IntOffset(((playedFraction * widthPx) - 6.dp.toPx()).roundToInt(), 0) }
                .size(12.dp)
                .background(Color.White, CircleShape)
        )
    }
}

/** PotPlayer-style jump-to-time dialog ("mm:ss" or "hh:mm:ss"). */
@Composable
fun JumpToTimeDialog(
    onDismiss: () -> Unit,
    onJump: (Long) -> Unit,
) {
    var timeInput by remember { mutableStateOf("") }
    val parsed = parseTimeInput(timeInput)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Jump to time") },
        text = {
            Column {
                Text(
                    "Enter a position as mm:ss or hh:mm:ss",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = timeInput,
                    onValueChange = { timeInput = it },
                    label = { Text("mm:ss") },
                    singleLine = true,
                    isError = timeInput.isNotBlank() && parsed == null,
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = parsed != null,
                onClick = { parsed?.let(onJump) },
            ) { Text("Jump") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}
