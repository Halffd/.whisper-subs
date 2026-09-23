package com.halffd.whispersubs.ui.channels

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
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
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
import androidx.navigation.NavController
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.Channel
import com.halffd.whispersubs.data.OfflineCache
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.ui.common.OfflineBanner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChannelsScreen(navController: NavController) {
    val context = LocalContext.current
    val serverConfig = ServerConfig.getInstance(context)
    val apiClient = remember { ApiClient(serverConfig) }

    var channels by remember { mutableStateOf<List<Channel>>(emptyList()) }
    var isLoading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var searchText by remember { mutableStateOf("") }
    var cachedAtMs by remember { mutableStateOf<Long?>(null) }
    val offlineCache = remember { OfflineCache(context) }

    fun loadChannels() {
        isLoading = true
        error = null
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val result = apiClient.getChannels()
                .also { it.onSuccess { resp -> offlineCache.saveChannels(resp) } }
            val appliedCache = if (result.isFailure) offlineCache.loadChannels() else null
            kotlinx.coroutines.withContext(Dispatchers.Main) {
                isLoading = false
                if (appliedCache != null) {
                    channels = appliedCache.data.channels
                    cachedAtMs = appliedCache.cachedAtMs
                } else {
                    result.onSuccess {
                        channels = it.channels
                        cachedAtMs = null
                    }
                        .onFailure { error = it.message ?: "Failed to load channels" }
                }
            }
        }
    }

    LaunchedEffect(Unit) {
        loadChannels()
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Channels", fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            actions = {
                IconButton(onClick = ::loadChannels) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                }
            }
        )

        TextField(
            value = searchText,
            onValueChange = { searchText = it },
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            placeholder = { Text("Search channels...") },
            leadingIcon = {
                Icon(Icons.Filled.Search, contentDescription = "Search", tint = MaterialTheme.colorScheme.onSurfaceVariant)
            },
            singleLine = true
        )

        OfflineBanner(cachedAtMs = cachedAtMs, onRefresh = ::loadChannels)

        if (isLoading) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (error != null) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(text = error!!, color = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = ::loadChannels) { Text("Retry") }
                }
            }
        } else {
            val filtered = channels.filter {
                it.name.lowercase().contains(searchText.lowercase())
            }
            if (filtered.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(text = "No channels found", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                LazyVerticalGrid(
                    columns = GridCells.Adaptive(340.dp),
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    gridItems(filtered) { channel ->
                        ChannelCard(channel = channel, navController = navController)
                    }
                }
            }
        }
    }
}

@Composable
fun ChannelCard(channel: Channel, navController: NavController) {
    val context = LocalContext.current
    val baseUrl = ServerConfig.getInstance(context).getApiEndpoint()

    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = {
            navController.navigate("channel_videos/${android.net.Uri.encode(channel.name)}")
        }
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surfaceVariant)
            ) {
                AsyncImage(
                    model = ImageRequest.Builder(context)
                        .data("$baseUrl/api/v1/channels/${android.net.Uri.encode(channel.name)}/icon")
                        .crossfade(true)
                        .build(),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize()
                )
            }
            Spacer(Modifier.width(12.dp))

            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = channel.name,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = "${channel.transcribed} transcribed" +
                        if (channel.unfinished > 0) " · ${channel.unfinished} in progress" else "",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            Icon(
                Icons.Filled.ChevronRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}