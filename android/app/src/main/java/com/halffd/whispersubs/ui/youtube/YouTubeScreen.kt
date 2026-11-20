package com.halffd.whispersubs.ui.youtube

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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.halffd.whispersubs.R
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.data.YtChannel
import com.halffd.whispersubs.data.YtVideo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * YouTube discovery and feed: find channels, follow them, watch their feed.
 *
 * Mirrors Flow's pattern — a search surface that doubles as the recommendation
 * feed. Three tabs: Discover (search + results), Subscriptions (followed
 * channels), Feed (ranked videos from those channels).
 *
 * The ranking is the server's (`/api/v1/youtube/feed`): recency, watches,
 * watchable length, live. This screen renders it and shows each item's
 * reasons so the ordering is inspectable rather than magic.
 *
 * Everything degrades to a clear message when no server is configured: the
 * channel/feed section needs a server, and the connect screen is one tap away.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun YouTubeScreen(navController: NavController) {
    val context = LocalContext.current
    val serverConfig = ServerConfig.getInstance(context)
    val apiClient = remember { ApiClient(serverConfig) }
    val configured = remember(serverConfig) { serverConfig.isConfigured() }

    var tab by remember { mutableStateOf(0) }
    var query by remember { mutableStateOf("") }

    // Discover
    var searching by remember { mutableStateOf(false) }
    var searchError by remember { mutableStateOf<String?>(null) }
    var results by remember { mutableStateOf<List<YtChannel>>(emptyList()) }

    // Subscriptions
    var subs by remember { mutableStateOf<List<YtChannel>>(emptyList()) }
    var subsLoading by remember { mutableStateOf(false) }
    var subsError by remember { mutableStateOf<String?>(null) }

    // Feed
    var feed by remember { mutableStateOf<List<YtVideo>>(emptyList()) }
    var feedLoading by remember { mutableStateOf(false) }
    var feedError by remember { mutableStateOf<String?>(null) }

    fun runSearch() {
        val q = query.trim()
        if (q.isBlank() || !configured) return
        searching = true
        searchError = null
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = apiClient.searchYtChannels(q)
            withContext(Dispatchers.Main) {
                searching = false
                result.onSuccess { results = it.results }
                    .onFailure { searchError = it.message ?: "Search failed" }
            }
        }
    }

    fun loadSubs() {
        if (!configured) return
        subsLoading = true
        subsError = null
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = apiClient.getYtSubscriptions()
            withContext(Dispatchers.Main) {
                subsLoading = false
                result.onSuccess { subs = it.subscriptions }
                    .onFailure { subsError = it.message ?: "Failed to load subscriptions" }
            }
        }
    }

    fun loadFeed() {
        if (!configured) return
        feedLoading = true
        feedError = null
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = apiClient.getYtFeed(refresh = true)
            withContext(Dispatchers.Main) {
                feedLoading = false
                result.onSuccess { feed = it.feed }
                    .onFailure { feedError = it.message ?: "Failed to load feed" }
            }
        }
    }

    fun toggleSubscribe(channel: YtChannel) {
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = if (channel.subscribed) {
                apiClient.unsubscribeYt(channel.url)
            } else {
                apiClient.subscribeYt(channel)
            }
            withContext(Dispatchers.Main) {
                result.onSuccess {
                    // Reflect it locally so the row flips without a refetch.
                    results = results.map {
                        if (it.url == channel.url) it.copy(subscribed = !it.subscribed) else it
                    }
                    subs = if (channel.subscribed) {
                        subs.filterNot { it.url == channel.url }
                    } else {
                        listOf(channel) + subs
                    }
                    feed = emptyList()  // stale: rankings change when subs do
                }
            }
        }
    }

    // First load of each tab fetches its own data.
    LaunchedEffect(tab, configured) {
        when (tab) {
            1 -> loadSubs()
            2 -> loadFeed()
            else -> Unit
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("YouTube", fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(
                containerColor = MaterialTheme.colorScheme.surface,
            ),
            actions = {
                IconButton(
                    onClick = {
                        when (tab) {
                            0 -> runSearch()
                            1 -> loadSubs()
                            else -> loadFeed()
                        }
                    }
                ) {
                    Icon(Icons.Filled.Refresh, contentDescription = stringResource(R.string.yt_refresh))
                }
            },
        )

        if (!configured) {
            // The channel/feed APIs are server-side; say so rather than
            // showing an empty screen that looks broken.
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    text = stringResource(R.string.error_no_server),
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.error,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    text = "YouTube search and the feed need a WhisperSubs "
                        + stringResource(R.string.yt_needs_server),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(16.dp))
                Button(onClick = { navController.navigate("connect") }) {
                    Text(stringResource(R.string.connect))
                }
            }
            return@Column
        }

        TabRow(selectedTabIndex = tab) {
            Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text(stringResource(R.string.yt_discover)) })
            Tab(
                selected = tab == 1,
                onClick = { tab = 1 },
                text = { Text(stringResource(R.string.yt_subscriptions)) },
            )
            Tab(selected = tab == 2, onClick = { tab = 2 }, text = { Text(stringResource(R.string.yt_feed)) })
        }

        when (tab) {
            // ---- Discover ----
            0 -> Column(modifier = Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        modifier = Modifier.weight(1f),
                        label = { Text(stringResource(R.string.yt_search_hint)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    )
                    Spacer(Modifier.width(8.dp))
                    IconButton(
                        onClick = { runSearch() },
                        enabled = query.isNotBlank() && !searching,
                    ) {
                        Icon(Icons.Filled.Search, contentDescription = stringResource(R.string.yt_search_channels))
                    }
                }
                when {
                    searching -> CenteredSpinner()
                    searchError != null -> CenteredError(searchError!!) { runSearch() }
                    results.isEmpty() -> CenteredEmpty(
                        stringResource(R.string.yt_empty_discover),
                        stringResource(R.string.yt_empty_discover_hint),
                    )
                    else -> LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(results) { channel ->
                            ChannelCard(
                                channel = channel,
                                onToggleSubscribe = { toggleSubscribe(channel) },
                            )
                        }
                    }
                }
            }

            // ---- Subscriptions ----
            1 -> when {
                subsLoading -> CenteredSpinner()
                subsError != null -> CenteredError(subsError!!) { loadSubs() }
                subs.isEmpty() -> CenteredEmpty(
                    stringResource(R.string.yt_empty_subs),
                    stringResource(R.string.yt_empty_subs_hint),
                )
                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(subs) { channel ->
                        ChannelCard(
                            channel = channel,
                            onToggleSubscribe = { toggleSubscribe(channel) },
                        )
                    }
                }
            }

            // ---- Feed ----
            else -> when {
                feedLoading -> CenteredSpinner()
                feedError != null -> CenteredError(feedError!!) { loadFeed() }
                feed.isEmpty() -> CenteredEmpty(
                    stringResource(R.string.yt_empty_feed),
                    stringResource(R.string.yt_empty_feed_hint),
                )
                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(feed) { video ->
                        FeedCard(
                            video = video,
                            onPlay = {
                                // Feed items are links the server can resolve;
                                // hand one to Search's link path, which knows how
                                // to fetch captions or transcribe it.
                                navController.navigate(
                                    "search?query=" +
                                        android.net.Uri.encode(video.url)
                                )
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ChannelCard(
    channel: YtChannel,
    onToggleSubscribe: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ChannelAvatar(channel)
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = channel.name.ifBlank { "Unknown channel" },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val subs = channel.subscribers
                Text(
                    text = if (subs != null) {
                        stringResource(R.string.yt_subscribers, formatCount(subs))
                    } else {
                        channel.handle
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.width(8.dp))
            if (channel.subscribed) {
                FilledTonalButton(onClick = onToggleSubscribe) {
                    Icon(
                        Icons.Filled.Check,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                    Text(stringResource(R.string.yt_following))
                }
            } else {
                OutlinedButton(onClick = onToggleSubscribe) {
                    Icon(
                        Icons.Filled.PersonAdd,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                    Text(stringResource(R.string.yt_follow))
                }
            }
        }
    }
}

@Composable
private fun FeedCard(video: YtVideo, onPlay: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().clickable(onClick = onPlay)) {
        Row(modifier = Modifier.padding(12.dp)) {
            Box(modifier = Modifier.size(width = 128.dp, height = 72.dp)) {
                AsyncImage(
                    model = ImageRequest.Builder(LocalContext.current)
                        .data(video.thumbnail_url)
                        .crossfade(true)
                        .build(),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier
                        .fillMaxSize()
                        .clip(RoundedCornerShape(8.dp)),
                )
                Icon(
                    Icons.Filled.PlayArrow,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.align(Alignment.Center).size(28.dp),
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = video.title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Medium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = video.channel.ifBlank { "Unknown channel" },
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val minutes = (video.duration ?: 0.0) / 60.0
                if (minutes > 0) {
                    Text(
                        text = stringResource(R.string.yt_minutes, minutes.toInt()),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                val reasons = video.reasons
                if (reasons.isNotEmpty()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = reasons.joinToString(" · "),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                if (video.live) {
                    Text(
                        text = stringResource(R.string.yt_live),
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

@Composable
private fun ChannelAvatar(channel: YtChannel) {
    AsyncImage(
        model = ImageRequest.Builder(LocalContext.current)
            .data(channel.avatar)
            .crossfade(true)
            .build(),
        contentDescription = null,
        contentScale = ContentScale.Crop,
        modifier = Modifier
            .size(48.dp)
            .clip(CircleShape),
    )
}

@Composable
private fun CenteredSpinner() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun CenteredError(message: String, onRetry: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(24.dp),
        ) {
            Text(
                text = message,
                color = MaterialTheme.colorScheme.error,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(8.dp))
            Button(onClick = onRetry) { Text(stringResource(R.string.yt_retry)) }
        }
    }
}

@Composable
private fun CenteredEmpty(title: String, subtitle: String) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(24.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
    }
}

/** 1234 -> "1.2K", 1234567 -> "1.2M". */
private fun formatCount(count: Int): String = when {
    count >= 1_000_000 -> String.format("%.1fM", count / 1_000_000.0)
    count >= 1_000 -> String.format("%.1fK", count / 1_000.0)
    else -> count.toString()
}
