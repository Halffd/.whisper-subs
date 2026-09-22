package com.halffd.whispersubs.ui.channels

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.ChannelVideo
import com.halffd.whispersubs.data.ChannelVideosResponse
import com.halffd.whispersubs.data.ServerConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChannelVideosScreen(channelName: String, navController: NavController) {
    val context = LocalContext.current
    val serverConfig = ServerConfig.getInstance(context)
    val apiClient = remember { ApiClient(serverConfig) }

    var data by remember { mutableStateOf<ChannelVideosResponse?>(null) }
    var isLoading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun load(refresh: Boolean = false) {
        isLoading = true
        error = null
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = apiClient.getChannelVideos(channelName, refresh)
            kotlinx.coroutines.withContext(Dispatchers.Main) {
                isLoading = false
                result.onSuccess { data = it }
                    .onFailure { error = it.message ?: "Failed to load videos" }
            }
        }
    }

    LaunchedEffect(channelName) {
        load()
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = {
                Text(
                    data?.channel_name ?: channelName,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            navigationIcon = {
                IconButton(onClick = { navController.popBackStack() }) {
                    Icon(Icons.Filled.ArrowBack, contentDescription = "Back")
                }
            },
            actions = {
                IconButton(onClick = { load(true) }) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                }
            }
        )

        val header = data
        if (header != null && !isLoading) {
            Text(
                text = "${header.subscribers?.let { formatViews(it) + " · " } ?: ""}" +
                    "${header.transcribed_count}/${header.total} transcribed",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.fillMaxWidth().padding(16.dp, 4.dp, 16.dp, 0.dp)
            )
        }

        if (isLoading) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (error != null) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(text = error!!, color = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = { load(false) }) { Text("Retry") }
                }
            }
        } else if (data == null || data!!.videos.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(text = "No videos found", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            val videos = data!!.videos
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(videos) { video ->
                    VideoCard(video = video, navController = navController)
                }
            }
        }
    }
}

@Composable
fun VideoCard(video: ChannelVideo, navController: NavController) {
    val context = LocalContext.current
    val serverConfig = ServerConfig.getInstance(context)

    fun openPlayer() {
        val baseUrl = serverConfig.getApiEndpoint()
        val srtUrl = video.srt_url?.let {
            if (it.startsWith("http")) it else "$baseUrl$it"
        } ?: ""
        val sourceUrl = video.source_url ?: ""
        val route = "player/${Uri.encode(video.id)}" +
            "?srtUrl=${Uri.encode(srtUrl)}" +
            "&sourceUrl=${Uri.encode(sourceUrl)}" +
            "&title=${Uri.encode(video.title)}"
        navController.navigate(route)
    }

    fun downloadSrt() {
        val baseUrl = serverConfig.getApiEndpoint()
        val srtUrl = video.srt_url?.let {
            if (it.startsWith("http")) it else "$baseUrl$it"
        } ?: return
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(srtUrl)))
    }

    fun startTranscription() {
        val source = video.source_url ?: return
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = serverConfig.let { ApiClient(it).startTranscription(source) }
            kotlinx.coroutines.withContext(Dispatchers.Main) {
                result.onSuccess { task ->
                    Toast.makeText(context, "Transcription queued: ${task.task_id}", Toast.LENGTH_SHORT).show()
                }.onFailure { e ->
                    Toast.makeText(context, "Failed: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    fun openSource() {
        val source = video.source_url ?: return
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(source)))
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = { if (video.transcribed && video.srt_url != null) openPlayer() }
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.Top
            ) {
                // Thumbnail
                Box(
                    modifier = Modifier
                        .size(width = 160.dp, height = 90.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                ) {
                    video.thumbnail_url?.let { thumbUrl ->
                        val fullUrl = if (thumbUrl.startsWith("http")) thumbUrl
                        else "${serverConfig.getApiEndpoint()}$thumbUrl"
                        AsyncImage(
                            model = ImageRequest.Builder(context)
                                .data(fullUrl)
                                .crossfade(true)
                                .build(),
                            contentDescription = null,
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.fillMaxSize()
                        )
                    }
                }
                Spacer(Modifier.width(12.dp))

                // Info
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = video.title,
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis
                    )
                    Spacer(Modifier.height(4.dp))

                    val stats = listOf(
                        video.date,
                        video.duration?.takeIf { it > 0 }?.let { formatDuration(it) },
                        video.views?.takeIf { it > 0 }?.let { formatViews(it) },
                        video.likes?.takeIf { it > 0 }?.let { formatViews(it).replace("views", "likes") },
                    ).filterNotNull().joinToString(" · ")
                    if (stats.isNotBlank()) {
                        Text(
                            text = stats,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Spacer(Modifier.height(8.dp))

                    if (video.transcribed) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            video.model?.let { Badge(it, MaterialTheme.colorScheme.secondaryContainer) }
                            if (video.has_video) Badge("VIDEO", MaterialTheme.colorScheme.primaryContainer)
                            if (video.has_audio) Badge("AUDIO", MaterialTheme.colorScheme.secondaryContainer)
                            Badge("SUB", MaterialTheme.colorScheme.tertiaryContainer)
                        }
                    } else {
                        Badge("NOT TRANSCRIBED", MaterialTheme.colorScheme.errorContainer)
                    }

                    Spacer(Modifier.height(10.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        if (video.transcribed && video.srt_url != null) {
                            Button(
                                onClick = ::openPlayer,
                                modifier = Modifier.weight(1f),
                                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                            ) {
                                Icon(Icons.Filled.PlayArrow, contentDescription = "Play", modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Play")
                            }
                            Button(
                                onClick = ::downloadSrt,
                                modifier = Modifier.weight(1f)
                            ) {
                                Icon(Icons.Filled.Download, contentDescription = "Download", modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("SRT")
                            }
                        } else if (video.source_url != null) {
                            Button(
                                onClick = ::startTranscription,
                                modifier = Modifier.weight(1f),
                                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                            ) {
                                Text("Transcribe")
                            }
                            Button(
                                onClick = ::openSource,
                                modifier = Modifier.weight(1f)
                            ) {
                                Icon(Icons.Filled.OpenInNew, contentDescription = "Open", modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Open")
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun Badge(text: String, color: androidx.compose.ui.graphics.Color) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(10.dp))
            .background(color.copy(alpha = 0.35f))
            .padding(horizontal = 8.dp, vertical = 2.dp)
    ) {
        Text(
            text = text,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface
        )
    }
}

fun formatDuration(seconds: Double): String {
    val totalSeconds = seconds.toLong()
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val secs = totalSeconds % 60
    return if (hours > 0) String.format("%d:%02d:%02d", hours, minutes, secs)
    else String.format("%02d:%02d", minutes, secs)
}

fun formatViews(views: Long): String = when {
    views >= 1_000_000 -> String.format("%.1fM views", views / 1_000_000.0)
    views >= 1_000 -> String.format("%.1fK views", views / 1_000.0)
    else -> "$views views"
}