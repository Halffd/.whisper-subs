package com.halffd.whispersubs.ui.search

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
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.DownloadEntry
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.data.SubtitleMatch
import com.halffd.whispersubs.data.SubtitleSearchResult
import com.halffd.whispersubs.data.VideoSearchResult
import kotlinx.coroutines.delay
import com.halffd.whispersubs.local.LocalSearch
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

private val SCOPES = listOf("Local", "Subtitles", "YouTube", "Twitch")
private val SORT_OPTIONS = listOf("date", "views", "duration", "title")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(navController: NavController) {
    val context = LocalContext.current
    val serverConfig = ServerConfig.getInstance(context)
    val apiClient = remember { ApiClient(serverConfig) }

    var scope by rememberSaveable { mutableStateOf("Subtitles") }
    var query by rememberSaveable { mutableStateOf("") }
    var submittedQuery by rememberSaveable { mutableStateOf("") }
    var isSearching by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var sort by rememberSaveable { mutableStateOf("date") }
    var twitchType by rememberSaveable { mutableStateOf("all") }
    var sortMenuOpen by remember { mutableStateOf(false) }

    // Local results (device SRT search)
    var localResults by remember { mutableStateOf<List<LocalSearch.LocalResult>>(emptyList()) }
    // Subtitles / YouTube results
    var videoResults by remember { mutableStateOf<List<SubtitleSearchResult>>(emptyList()) }
    // YouTube / Twitch raw video results
    var onlineResults by remember { mutableStateOf<List<VideoSearchResult>>(emptyList()) }
    var twitchLive by remember { mutableStateOf<VideoSearchResult?>(null) }
    var downloadState by remember { mutableStateOf<DownloadEntry?>(null) }

    fun runSearch() {
        val q = query.trim()
        if (q.isEmpty()) return
        submittedQuery = q
        isSearching = true
        error = null

        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            try {
                when (scope) {
                    "Local" -> {
                        val results = LocalSearch.search(context, q)
                        kotlinx.coroutines.withContext(Dispatchers.Main) {
                            localResults = results
                            isSearching = false
                        }
                    }
                    "Subtitles" -> {
                        val result = apiClient.searchSubtitles(q)
                        kotlinx.coroutines.withContext(Dispatchers.Main) {
                            result.onSuccess { videoResults = it.results }
                                .onFailure { error = it.message ?: "Search failed" }
                            isSearching = false
                        }
                    }
                    "YouTube" -> {
                        val result = apiClient.searchYoutube(q, limit = 15)
                        kotlinx.coroutines.withContext(Dispatchers.Main) {
                            result.onSuccess { onlineResults = it.results }
                                .onFailure { error = it.message ?: "Search failed" }
                            isSearching = false
                        }
                    }
                    "Twitch" -> {
                        // Query format: "channel query" or just "channel"
                        val parts = q.split(" ", limit = 2)
                        val channel = parts[0]
                        val filter = parts.getOrNull(1)
                        val result = apiClient.searchTwitch(
                            channel = channel,
                            q = filter,
                            type = twitchType,
                            sort = sort,
                        )
                        kotlinx.coroutines.withContext(Dispatchers.Main) {
                            result.onSuccess {
                                twitchLive = it.live
                                onlineResults = it.vods
                            }.onFailure { error = it.message ?: "Search failed" }
                            isSearching = false
                        }
                    }
                }
            } catch (e: Exception) {
                kotlinx.coroutines.withContext(Dispatchers.Main) {
                    error = e.message ?: "Search failed"
                    isSearching = false
                }
            }
        }
    }

    fun playOnline(item: VideoSearchResult) {
        val source = item.url ?: return
        // Server-side yt-dlp download, then play the finished file in-app
        val client = ApiClient(ServerConfig.getInstance(context))
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val startResult = client.startDownload(source)
            val entry = kotlinx.coroutines.withContext(Dispatchers.Main) {
                startResult.onSuccess { downloadState = it }
                    .onFailure { e ->
                        Toast.makeText(context, "Download failed: ${e.message}", Toast.LENGTH_SHORT).show()
                    }
                startResult.getOrNull()
            } ?: return@launch

            // Poll until completed/failed
            var current = entry
            while (current.status !in listOf("completed", "failed")) {
                delay(1500)
                val statusResult = client.getDownloadStatus(current.download_id)
                current = statusResult.getOrNull() ?: current
                kotlinx.coroutines.withContext(Dispatchers.Main) {
                    downloadState = current
                }
            }

            kotlinx.coroutines.withContext(Dispatchers.Main) {
                if (current.status == "completed" && current.rel_path != null) {
                    val mediaPath = current.rel_path
                    val route = "player/${Uri.encode(current.download_id)}" +
                        "?srtUrl=${Uri.encode("")}" +
                        "&sourceUrl=${Uri.encode("")}" +
                        "&title=${Uri.encode(current.title ?: source)}" +
                        "&mediaUrl=${Uri.encode("/api/v1/media/file?path=$mediaPath")}"
                    downloadState = null
                    navController.navigate(route)
                } else {
                    downloadState = null
                    Toast.makeText(
                        context,
                        "Download failed: ${current.error ?: "unknown"}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    fun transcribeOnline(item: VideoSearchResult) {
        val source = item.url ?: return
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = ApiClient(ServerConfig.getInstance(context)).startTranscription(source)
            kotlinx.coroutines.withContext(Dispatchers.Main) {
                result.onSuccess { task ->
                    Toast.makeText(context, "Transcription queued: ${task.task_id}", Toast.LENGTH_SHORT).show()
                }.onFailure { e ->
                    Toast.makeText(context, "Failed: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Search", fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
        )

        // Scope tabs
        TabRow(selectedTabIndex = SCOPES.indexOf(scope)) {
            SCOPES.forEach { s ->
                Tab(
                    selected = scope == s,
                    onClick = { scope = s },
                    text = { Text(s, fontSize = 13.sp) }
                )
            }
        }

        // Search bar + sort
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp, 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                modifier = Modifier.weight(1f),
                placeholder = {
                    Text(
                        when (scope) {
                            "Local" -> "Search local transcriptions..."
                            "Subtitles" -> "Search subtitle content..."
                            "YouTube" -> "Search YouTube..."
                            else -> "channel [query] e.g. lirik minecraft"
                        }
                    )
                },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                trailingIcon = {
                    if (query.isNotEmpty()) {
                        IconButton(onClick = { query = "" }) {
                            Icon(Icons.Filled.Close, contentDescription = "Clear")
                        }
                    }
                },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { runSearch() }),
                colors = OutlinedTextFieldDefaults.colors()
            )
            if (scope == "Twitch") {
                Box {
                    IconButton(onClick = { sortMenuOpen = true }) {
                        Icon(Icons.Filled.FilterList, contentDescription = "Sort")
                    }
                    DropdownMenu(expanded = sortMenuOpen, onDismissRequest = { sortMenuOpen = false }) {
                        SORT_OPTIONS.forEach { opt ->
                            DropdownMenuItem(
                                text = { Text(opt.replaceFirstChar { it.uppercase() }) },
                                onClick = {
                                    sort = opt
                                    sortMenuOpen = false
                                    if (submittedQuery.isNotEmpty()) runSearch()
                                }
                            )
                        }
                    }
                }
            }
        }

        // Results
        if (isSearching) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (error != null) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(text = error!!, color = MaterialTheme.colorScheme.error)
            }
        } else {
            when (scope) {
                "Local" -> LocalResultsList(localResults, submittedQuery)
                "Subtitles" -> SubtitleResultsList(videoResults, submittedQuery, navController)
                "YouTube" -> OnlineResultsList(onlineResults, submittedQuery, ::playOnline, ::transcribeOnline)
                "Twitch" -> {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        twitchLive?.let { live ->
                            item {
                                Text(
                                    text = "LIVE NOW",
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.error,
                                    modifier = Modifier.padding(bottom = 4.dp)
                                )
                                OnlineResultCard(live, submittedQuery, ::playOnline, ::transcribeOnline, isLive = true)
                            }
                        }
                        item {
                            Text(
                                text = "VODs (${onlineResults.size})",
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(top = 4.dp, bottom = 4.dp)
                            )
                        }
                        items(onlineResults) { vod ->
                            OnlineResultCard(vod, submittedQuery, ::playOnline, ::transcribeOnline)
                        }
                    }
                }
            }
        }

        // Download progress dialog
        downloadState?.let { entry ->
            androidx.compose.material3.AlertDialog(
                onDismissRequest = { /* downloading; let it finish */ },
                title = { Text("Downloading") },
                text = {
                    Column {
                        Text(
                            text = entry.title ?: entry.source,
                            style = MaterialTheme.typography.bodyMedium,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis
                        )
                        Spacer(Modifier.height(12.dp))
                        val progress = entry.progress?.toFloat()
                        if (progress != null) {
                            androidx.compose.material3.LinearProgressIndicator(
                                progress = { progress.coerceIn(0f, 1f) },
                                modifier = Modifier.fillMaxWidth()
                            )
                        } else {
                            androidx.compose.material3.LinearProgressIndicator(
                                modifier = Modifier.fillMaxWidth()
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                        Text(
                            text = entry.status.replaceFirstChar { it.uppercase() } +
                                (entry.progress?.let { " · ${(it * 100).toInt()}%" } ?: "") +
                                (entry.speed_mbps?.let { " · ${it}MB/s" } ?: ""),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                confirmButton = {},
            )
        }
    }
}

// ---------------------------------------------------------------------------
// Result lists
// ---------------------------------------------------------------------------

@Composable
private fun LocalResultsList(results: List<LocalSearch.LocalResult>, query: String) {
    if (results.isEmpty()) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                text = if (query.isBlank()) "Type a query to search local transcriptions" else "No local matches",
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items(results) { result ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = result.fileName,
                            style = MaterialTheme.typography.titleMedium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f)
                        )
                        androidx.compose.material3.Badge { Text("${result.matchCount}") }
                    }
                    Spacer(Modifier.height(6.dp))
                    result.matches.forEach { match ->
                        Text(
                            text = match.timestamp,
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Text(
                            text = match.snippet,
                            fontSize = 13.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis
                        )
                        Spacer(Modifier.height(6.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun SubtitleResultsList(
    results: List<SubtitleSearchResult>,
    query: String,
    navController: NavController,
) {
    if (results.isEmpty()) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                text = if (query.isBlank()) "Type a query to search subtitle content" else "No matches in subtitles",
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        return
    }
    val context = LocalContext.current
    val baseUrl = ServerConfig.getInstance(context).getApiEndpoint()

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items(results) { result ->
            Card(
                modifier = Modifier.fillMaxWidth(),
                onClick = {
                    // Open the player with this subtitle
                    val srtUrl = if (result.srt_url.startsWith("http")) result.srt_url else "$baseUrl${result.srt_url}"
                    val route = "player/${Uri.encode(result.id)}" +
                        "?srtUrl=${Uri.encode(srtUrl)}" +
                        "&sourceUrl=${Uri.encode(result.source_url ?: "")}" +
                        "&title=${Uri.encode(result.title)}"
                    navController.navigate(route)
                }
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = result.title,
                                style = MaterialTheme.typography.titleMedium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                            Text(
                                text = "${result.channel}${result.date?.let { " · $it" } ?: ""}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        androidx.compose.material3.Badge { Text("${result.match_count}") }
                    }
                    Spacer(Modifier.height(6.dp))
                    result.matches.take(3).forEach { match ->
                        Text(
                            text = match.timestamp,
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Text(
                            text = match.snippet,
                            fontSize = 13.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis
                        )
                        Spacer(Modifier.height(6.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun OnlineResultsList(
    results: List<VideoSearchResult>,
    query: String,
    onPlay: (VideoSearchResult) -> Unit,
    onTranscribe: (VideoSearchResult) -> Unit,
) {
    if (results.isEmpty()) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                text = if (query.isBlank()) "Type a query to search online" else "No results",
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items(results) { item ->
            OnlineResultCard(item, query, onPlay, onTranscribe)
        }
    }
}

@Composable
private fun OnlineResultCard(
    item: VideoSearchResult,
    query: String,
    onPlay: (VideoSearchResult) -> Unit,
    onTranscribe: (VideoSearchResult) -> Unit,
    isLive: Boolean = false,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = { onPlay(item) }
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.Top
        ) {
            Box(
                modifier = Modifier
                    .size(width = 140.dp, height = 80.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
            ) {
                item.thumbnail_url?.let { thumbUrl ->
                    AsyncImage(
                        model = ImageRequest.Builder(LocalContext.current)
                            .data(thumbUrl)
                            .crossfade(true)
                            .build(),
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
            Spacer(Modifier.width(12.dp))

            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.title ?: "",
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(4.dp))
                val stats = listOf(
                    item.channel,
                    item.duration?.takeIf { it > 0 }?.let { formatDuration(it) },
                    item.views?.takeIf { it > 0 }?.let { formatViews(it) },
                ).filterNotNull().joinToString(" · ")
                if (stats.isNotBlank()) {
                    Text(
                        text = stats,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = { onTranscribe(item) },
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                    ) {
                        Text(if (isLive) "Transcribe Live" else "Transcribe")
                    }
                    Button(onClick = { onPlay(item) }) {
                        Icon(Icons.Filled.OpenInNew, contentDescription = "Open", modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Open")
                    }
                }
            }
        }
    }
}

private fun formatDuration(seconds: Double): String {
    val totalSeconds = seconds.toLong()
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val secs = totalSeconds % 60
    return if (hours > 0) String.format("%d:%02d:%02d", hours, minutes, secs)
    else String.format("%02d:%02d", minutes, secs)
}

private fun formatViews(views: Long): String = when {
    views >= 1_000_000 -> String.format("%.1fM", views / 1_000_000.0)
    views >= 1_000 -> String.format("%.1fK", views / 1_000.0)
    else -> "$views"
}