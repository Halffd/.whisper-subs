package com.halffd.whispersubs.ui.search

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tv
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
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
import com.halffd.whispersubs.data.CaptionFetchResponse
import com.halffd.whispersubs.data.CaptionTrackInfo
import com.halffd.whispersubs.data.DownloadEntry
import com.halffd.whispersubs.data.MediaLinks
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.data.SubtitleMatch
import com.halffd.whispersubs.data.SubtitleSearchResult
import com.halffd.whispersubs.data.Suggestion
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
fun SearchScreen(navController: NavController, initialQuery: String = "") {
    val context = LocalContext.current
    val serverConfig = ServerConfig.getInstance(context)
    val apiClient = remember { ApiClient(serverConfig) }

    var scope by rememberSaveable { mutableStateOf("Subtitles") }
    var query by rememberSaveable { mutableStateOf(initialQuery) }
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
    // Human captions found for a pasted link: no transcription needed.
    var captionState by remember { mutableStateOf<CaptionFetchResponse?>(null) }
    var linkLabel by remember { mutableStateOf("") }
    // Tracks the user may pick from before anything is fetched.
    var captionChoices by remember { mutableStateOf<List<CaptionTrackInfo>>(emptyList()) }
    var allCaptionTracks by remember { mutableStateOf<List<CaptionTrackInfo>>(emptyList()) }
    var pendingLinkUrl by remember { mutableStateOf("") }
    var pendingDest by remember { mutableStateOf("") }
    // Automatic tracks are opt-in, like the CLI's --fetch-auto.
    var includeAutomatic by remember { mutableStateOf(false) }

    /** Fetch the chosen track; empty language -> best available (server-side). */
    fun fetchCaptionTrack(track: CaptionTrackInfo) {
        val link = pendingLinkUrl
        if (link.isBlank()) return
        captionChoices = emptyList()
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val fetched = apiClient.fetchCaptions(
                link,
                dest = pendingDest,
                langs = track.lang,
                allowAutomatic = track.automatic,
            )
            withContext(Dispatchers.Main) {
                fetched.onSuccess { result -> captionState = result }
                    .onFailure { queueLinkDownload(link) }
            }
        }
    }

    /** Queue a link for server-side download + transcription (no captions). */
    fun queueLinkDownload(url: String) {
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = apiClient.startDownload(url)
            kotlinx.coroutines.withContext(Dispatchers.Main) {
                result.onSuccess { entry -> downloadState = entry }
                    .onFailure { error = it.message ?: "Could not start that link" }
                isSearching = false
            }
        }
    }

    // Suggestions / history (autocomplete)
    var searchFocused by remember { mutableStateOf(false) }
    var suggestions by remember { mutableStateOf<List<Suggestion>>(emptyList<>())

    // Debounced autocomplete fetch while the search field is focused
    LaunchedEffect(query, searchFocused) {
        if (!searchFocused) return@LaunchedEffect
        delay(300)
        apiClient.getSuggestions(query.trim())
            .onSuccess { suggestions = it.suggestions }
    }

    fun runSearch() {
        val q = query.trim()
        if (q.isEmpty()) return
        submittedQuery = q
        isSearching = true
        error = null
        searchFocused = false
        suggestions = emptyList()

        // A pasted URL is not a keyword search: hand it straight to the
        val url = q.takeIf { MediaLinks.isMediaUrl(it) }
        if (url != null) {
            linkLabel = MediaLinks.label(url)
            pendingLinkUrl = url
            // The server writes the SRT under its captions dir using this
            // as a filename, so strip path/query characters.
            pendingDest = "app_" + linkLabel.map {
                if (it.isLetterOrDigit() || it in "._-") it else '_'
            }.joinToString("").take(64)
            // List what exists before choosing: a video with human captions in
            // several languages should let the user pick, not silently take
            // the first match. No captions at all falls through to download.
            CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
                val listed = apiClient.listCaptions(url)
                withContext(Dispatchers.Main) {
                    isSearching = false
                    listed.onSuccess { response ->
                        allCaptionTracks = response.tracks
                        // Human tracks up front; automatic are opt-in.
                        captionChoices = response.tracks.filter { !it.automatic }
                        if (captionChoices.isEmpty()) {
                            queueLinkDownload(url)
                        }
                    }.onFailure { queueLinkDownload(url) }
                }
            }
            return
        }

        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            // Record in per-user history (fire-and-forget)
            apiClient.recordSearchHistory(q, scope.lowercase())
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

    // A deep link (widget tap or whispersubs:// URL) hands over a query;
    // run it once on entry so the user lands on results, not an empty field.
    LaunchedEffect(initialQuery) {
        if (initialQuery.isNotBlank()) runSearch()
    }

    // Poll a queued link download until it completes, fails, or is dismissed.
    LaunchedEffect(downloadState?.download_id) {
        val entry = downloadState ?: return@LaunchedEffect
        if (entry.status == "completed" || entry.status == "failed") return@LaunchedEffect
        while (true) {
            delay(1500)
            val result = apiClient.getDownloadStatus(entry.download_id)
            val latest = result.getOrNull() ?: break
            downloadState = latest
            if (latest.status == "completed" || latest.status == "failed") break
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
                modifier = Modifier
                    .weight(1f)
                    .onFocusChanged { searchFocused = it.isFocused },
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

        // Results (suggestions panel takes over while the field is focused)
        if (searchFocused && suggestions.isNotEmpty()) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp)
            ) {
                item {
                    Text(
                        text = if (query.isBlank()) "Recent searches" else "Suggestions",
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(bottom = 4.dp)
                    )
                }
                items(suggestions) { s ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                query = s.text
                                runSearch()
                            }
                            .background(
                                MaterialTheme.colorScheme.surface,
                                RoundedCornerShape(8.dp)
                            )
                            .padding(12.dp, 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Icon(
                            imageVector = when (s.source) {
                                "history" -> Icons.Filled.History
                                "channel" -> Icons.Filled.Tv
                                else -> Icons.Filled.VideoLibrary
                            },
                            contentDescription = s.source,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(20.dp)
                        )
                        Text(
                            text = s.text,
                            fontSize = 14.sp,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
            }
        } else if (isSearching) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (captionChoices.isNotEmpty()) {
            CaptionChoiceCard(
                label = linkLabel,
                tracks = captionChoices,
                hasAutomatic = allCaptionTracks.any { it.automatic },
                includeAutomatic = includeAutomatic,
                onToggleAutomatic = { enabled ->
                    includeAutomatic = enabled
                    captionChoices = allCaptionTracks.filter {
                        !it.automatic || enabled
                    }
                },
                onPick = { fetchCaptionTrack(it) },
                onTranscribeInstead = {
                    captionChoices = emptyList()
                    val link = pendingLinkUrl
                    if (link.isNotBlank()) queueLinkDownload(link)
                },
            )
        } else if (captionState != null) {
            // Human captions found for the pasted link: playback can start
            // immediately, no transcription needed.
            CaptionResultCard(
                caption = captionState!!,
                label = linkLabel,
                onDismiss = { captionState = null },
            )
        } else if (downloadState != null) {
            // A pasted link went to the server-side download queue: show its
            // progress, and play/transcribe it once it finishes.
            LinkDownloadCard(
                entry = downloadState!!,
                onCancel = { downloadState = null },
            )
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
                            val dateSuffix = result.date?.let { " · $it" } ?: ""
                            Text(
                                text = "${result.channel}$dateSuffix",
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

/**
 * Progress card for a pasted link handed to the server-side download queue.
 * Reuses the same download entry the library/home screens show, so a link
 * behaves like any other source: queue -> file -> player.
 */
@Composable
private fun LinkDownloadCard(entry: DownloadEntry, onCancel: () -> Unit) {
    val statusLabel = when (entry.status) {
        "pending" -> "Queued"
        "processing" -> "Downloading"
        "merging" -> "Merging audio"
        "completed" -> "Ready"
        "failed" -> "Failed"
        else -> entry.status
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = entry.title ?: MediaLinks.label(entry.source),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = MediaLinks.label(entry.source),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (entry.status == "completed" || entry.status == "failed") {
                    if (entry.status == "completed") {
                        Icon(
                            Icons.Filled.CheckCircle,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(20.dp),
                        )
                    } else {
                        Icon(
                            Icons.Filled.Error,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.error,
                            modifier = Modifier.size(20.dp),
                        )
                    }
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = statusLabel,
                        style = MaterialTheme.typography.labelLarge,
                        color = if (entry.status == "failed") {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.primary
                        },
                    )
                } else {
                    CircularProgressIndicator(
                        progress = { ((entry.progress ?: 0.0) / 100.0).toFloat() },
                        modifier = Modifier.size(20.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = "$statusLabel ${(entry.progress ?: 0.0).toInt()}%",
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            }
            entry.progress?.let { p ->
                Spacer(Modifier.height(8.dp))
                LinearProgressIndicator(
                    progress = { (p / 100.0).toFloat() },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            entry.speed_mbps?.let { speed ->
                Spacer(Modifier.height(6.dp))
                Text(
                    text = String.format("%.1f MB/s", speed),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            entry.error?.let { err ->
                Spacer(Modifier.height(6.dp))
                Text(
                    text = err,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Spacer(Modifier.height(12.dp))
            TextButton(onClick = onCancel) { Text("Dismiss") }
        }
    }
}

/**
 * A pasted link whose human captions were fetched straight from YouTube:
 * subtitles are ready without transcribing anything.
 */
@Composable
private fun CaptionResultCard(
    caption: CaptionFetchResponse,
    label: String,
    onDismiss: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = label.ifBlank { caption.rel_path ?: "Link" },
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Filled.CheckCircle,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.width(8.dp))
                val captionLang = caption.lang ?: "?"
                Text(
                    text = "Captions ready ($captionLang) — no transcription needed",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            if (caption.automatic) {
                Spacer(Modifier.height(6.dp))
                Text(
                    text = "Automatic captions: quality varies, timestamps may drift",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Spacer(Modifier.height(12.dp))
            TextButton(onClick = onDismiss) { Text("Dismiss") }
        }
    }
}

/**
 * A pasted link's caption tracks, before anything is fetched: the user picks
 * a language (or skips captions and transcribes instead).
 */
@Composable
private fun CaptionChoiceCard(
    label: String,
    tracks: List<CaptionTrackInfo>,
    hasAutomatic: Boolean,
    includeAutomatic: Boolean,
    onToggleAutomatic: (Boolean) -> Unit,
    onPick: (CaptionTrackInfo) -> Unit,
    onTranscribeInstead: () -> Unit,
) {
    // One row per language; YouTube lists several formats for the same
    // language, and the server converts the cheapest, so show the format too.
    val byLang = tracks.groupBy { it.lang.lower().split("-")[0] }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            val heading = label.ifBlank { "this link" }
            Text(
                text = "Captions for $heading",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "Pick a language, or transcribe instead.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (hasAutomatic) {
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Switch(
                        checked = includeAutomatic,
                        onCheckedChange = onToggleAutomatic,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = "Include automatic captions",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        byLang.forEach { (lang, options) ->
            item {
                val best = options.minByOrNull { formatRank(it.ext) }
                    ?: options.first()
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onPick(best) },
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = best.lang,
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.Medium,
                            modifier = Modifier.weight(1f),
                        )
                        if (best.automatic) {
                            Text(
                                text = "auto",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.error,
                            )
                            Spacer(Modifier.width(8.dp))
                        }
                        Icon(
                            Icons.Filled.Download,
                            contentDescription = "Use ${best.lang}",
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(20.dp),
                        )
                    }
                }
            }
        }
        item {
            Spacer(Modifier.height(8.dp))
            TextButton(
                onClick = onTranscribeInstead,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Transcribe instead (ignore captions)") }
        }
    }
}

private fun formatRank(ext: String): Int = when (ext) {
    "srt" -> 0
    "vtt" -> 1
    else -> 2
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