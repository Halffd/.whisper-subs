package com.halffd.whispersubs.ui.player

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.HighQuality
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.PlayCircleOutline
import androidx.compose.material.icons.filled.Subtitles
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.halffd.whispersubs.R
import com.halffd.whispersubs.data.SrtBlock

/** Width at which the player switches to the side-pane layout (Material 3 Expanded). */
private val WIDE_BREAKPOINT_DP = 840.dp
private val PANE_WIDTH_DP = 380.dp

/** Everything the pane knows about the current video; all of it resolved by PlayerScreen. */
class VideoInfo(
    val title: String,
    val channel: String?,
    val durationText: String?,
    val resolutionText: String?,
    val formatNote: String?,
    val sourceUrl: String,
    val srtPath: String,
    val subtitleCount: Int,
    val transcriptPreview: List<SrtBlock>,
    val currentSubtitle: SrtBlock?,
    val isLive: Boolean,
)

/** One labelled metadata line (duration, resolution, ...). */
@Composable
private fun MetaRow(
    icon: ImageVector,
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp)
        )
        Spacer(Modifier.width(12.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(96.dp)
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
    }
}

/** A titled block inside the pane. Sections without data are never composed at all. */
@Composable
private fun PaneSection(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface
        )
        Spacer(Modifier.height(8.dp))
        content()
    }
}

/** Card holding the playback facts that are already known: duration, resolution, format. */
@Composable
private fun PlaybackFactsCard(info: VideoInfo, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            if (info.isLive) {
                Text(
                    text = stringResource(R.string.pane_live_badge),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.error
                )
            }
            info.durationText?.let { duration ->
                MetaRow(
                    icon = Icons.Filled.Timer,
                    label = stringResource(R.string.info_duration),
                    value = duration
                )
            }
            info.resolutionText?.let { resolution ->
                MetaRow(
                    icon = Icons.Filled.HighQuality,
                    label = stringResource(R.string.info_resolution),
                    value = resolution
                )
            }
            info.formatNote?.takeIf { it.isNotBlank() }?.let { note ->
                MetaRow(
                    icon = Icons.Filled.PlayCircleOutline,
                    label = stringResource(R.string.pane_label_format),
                    value = note
                )
            }
            if (info.subtitleCount > 0) {
                MetaRow(
                    icon = Icons.Filled.Subtitles,
                    label = stringResource(R.string.info_subtitles),
                    value = stringResource(R.string.info_cue_count, info.subtitleCount)
                )
            }
        }
    }
}

/** Opening subtitles cues, timestamped — the only "description" this app can offer. */
@Composable
private fun TranscriptPreviewSection(cues: List<SrtBlock>, modifier: Modifier = Modifier) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        cues.forEach { cue ->
            Column(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "${formatMs((cue.start * 1000).toLong())} - " +
                        formatMs((cue.end * 1000).toLong()),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = cue.text,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        }
    }
}

/** Tappable row that hands the source URL to the browser. */
@Composable
private fun SourceRow(url: String, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.Filled.Link,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp)
        )
        Spacer(Modifier.width(12.dp))
        Text(
            text = url,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
        Icon(
            imageVector = Icons.Filled.OpenInNew,
            contentDescription = stringResource(R.string.info_open_source),
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier
                .size(36.dp)
                .clickable { openInBrowser(context, url) }
                .padding(8.dp)
        )
    }
}

/**
 * The side pane. Only sections backed by data the app already has are composed;
 * chapters, comments and description have no API here, so they are omitted entirely
 * instead of being rendered as empty placeholders.
 */
@Composable
fun VideoInfoPane(info: VideoInfo, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // ---- Title / uploader row (Flow keeps this above the action row) ----
        Column(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = info.title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis
            )
            val channel = info.channel
            if (!channel.isNullOrBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = channel,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }

        PlaybackFactsCard(info = info)

        if (info.transcriptPreview.isNotEmpty()) {
            PaneSection(title = stringResource(R.string.info_transcript_preview)) {
                TranscriptPreviewSection(info.transcriptPreview)
            }
        }

        info.currentSubtitle?.let { cue ->
            PaneSection(title = stringResource(R.string.info_now_playing)) {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Text(
                        text = cue.text,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(12.dp)
                    )
                }
            }
        }

        if (info.sourceUrl.isNotBlank()) {
            PaneSection(title = stringResource(R.string.info_source)) {
                SourceRow(url = info.sourceUrl)
            }
        }

        if (info.srtPath.isNotBlank()) {
            PaneSection(title = stringResource(R.string.pane_section_subtitle_file)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Filled.Description,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp)
                    )
                    Spacer(Modifier.width(12.dp))
                    Text(
                        text = info.srtPath,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }
        }
    }
}

/**
 * Hosts the player content and the info pane in the arrangement the current width
 * calls for. The player keeps its existing sizing and modifiers; only the space it
 * is given changes:
 *
 * - Expanded (>= 840.dp): video pinned left, pane in its own scroll column right.
 * - Compact: player on top, pane below, both inside one scrolling column.
 */
@Composable
fun AdaptivePlayerLayout(
    info: VideoInfo,
    player: @Composable () -> Unit,
    modifier: Modifier = Modifier,
    showPane: Boolean = true,
    topBar: @Composable () -> Unit = {},
    paneContentPadding: PaddingValues = PaddingValues(16.dp),
) {
    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        if (maxWidth >= WIDE_BREAKPOINT_DP) {
            // Wide: video pinned left, pane in its own scroll column right.
            Column(modifier = Modifier.fillMaxSize()) {
                topBar()
                Row(modifier = Modifier.fillMaxSize()) {
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxHeight(),
                        contentAlignment = Alignment.Center
                    ) {
                        player()
                    }
                    if (showPane) {
                        Surface(
                            modifier = Modifier
                                .width(PANE_WIDTH_DP)
                                .fillMaxHeight(),
                            color = MaterialTheme.colorScheme.surface
                        ) {
                            PaneScroll(info = info, contentPadding = paneContentPadding)
                        }
                    }
                }
            }
        } else {
            // Compact: player on top, pane below in one scrolling column.
            Column(modifier = Modifier.fillMaxSize()) {
                topBar()
                Box(
                    modifier = Modifier
                        .then(if (showPane) Modifier.fillMaxWidth() else Modifier.fillMaxSize()),
                    contentAlignment = Alignment.Center
                ) {
                    player()
                }
                if (showPane) {
                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f),
                        color = MaterialTheme.colorScheme.surface
                    ) {
                        PaneScroll(info = info, contentPadding = paneContentPadding)
                    }
                }
            }
        }
    }
}

/** Pane content inside its own vertical scroll container. */
@Composable
private fun PaneScroll(info: VideoInfo, contentPadding: PaddingValues) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(contentPadding)
    ) {
        VideoInfoPane(info = info)
    }
}

private fun openInBrowser(context: Context, url: String) {
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
    context.startActivity(intent)
}
