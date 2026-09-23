package com.halffd.whispersubs.ui.library

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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Smartphone
import androidx.compose.material.icons.filled.VideoLibrary
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.halffd.whispersubs.R
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.LibraryItem
import com.halffd.whispersubs.data.LocalLibraryRepository
import com.halffd.whispersubs.data.OfflineCache
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.ui.common.OfflineBanner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(
    navController: NavController,
    onNavigateToSettings: () -> Unit,
) {
    val context = LocalContext.current
    val serverConfig = ServerConfig.getInstance(context)
    val apiClient: ApiClient = hiltViewModel()
    val localRepo: LocalLibraryRepository = hiltViewModel()
    val offlineCache = remember { OfflineCache(context) }

    var serverItems by remember { mutableStateOf<List<LibraryItem>>(emptyList()) }
    var localItems by remember { mutableStateOf<List<LibraryItem>>(emptyList()) }
    var isLoading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var cachedAtMs by remember { mutableStateOf<Long?>(null) }

    fun loadAll() {
        isLoading = true
        error = null
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val serverResult = apiClient.getLibrary()
                .also { it.onSuccess { resp -> offlineCache.saveLibrary(resp) } }
            val appliedCache = if (serverResult.isFailure) offlineCache.loadLibrary() else null
            val localResult = localRepo.getLocalItems()
            kotlinx.coroutines.withContext(Dispatchers.Main) {
                isLoading = false
                if (appliedCache != null) {
                    // Offline: serve the last successful response with a banner
                    serverItems = appliedCache.data.library
                    cachedAtMs = appliedCache.cachedAtMs
                } else {
                    serverResult.onSuccess {
                        serverItems = it.library
                        cachedAtMs = null
                    }
                        .onFailure { error = it.message ?: "Failed to load library" }
                }
                localResult.onSuccess { localItems = it }
                    .onFailure { e ->
                        if (error == null) error = e.message ?: "Failed to load local library"
                    }
            }
        }
    }

    androidx.compose.runtime.LaunchedEffect(Unit) {
        loadAll()
    }

    val allItems = remember(serverItems, localItems) {
        (serverItems + localItems).sortedByDescending { it.size_bytes }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(stringResource(R.string.library_tab), fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            actions = {
                IconButton(onClick = ::loadAll) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                }
                IconButton(onClick = onNavigateToSettings) {
                    Icon(androidx.compose.material.icons.Icons.Filled.Settings, contentDescription = "Settings")
                }
            }
        )

        OfflineBanner(cachedAtMs = cachedAtMs, onRefresh = ::loadAll)

        if (isLoading) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (error != null) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(text = error!!, color = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.height(8.dp))
                    androidx.compose.material3.Button(onClick = ::loadAll) { Text("Retry") }
                }
            }
        } else if (allItems.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Filled.VideoLibrary,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                        modifier = Modifier.size(64.dp)
                    )
                    Spacer(Modifier.height(16.dp))
                    Text(text = stringResource(R.string.no_items), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        } else {
            // Adaptive grid: 1 column on phones, 2+ on tablets/foldables
            LazyVerticalGrid(
                columns = GridCells.Adaptive(340.dp),
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                gridItems(allItems) { item ->
                    LibraryItemCard(item = item, navController = navController)
                }
            }
        }
    }
}

@Composable
fun LibraryItemCard(item: LibraryItem, navController: NavController) {
    val context = LocalContext.current
    val isLocal = item.id.startsWith("local:")
    val baseUrl = ServerConfig.getInstance(context).getApiEndpoint()

    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = {
            val route: String = if (isLocal) {
                // Local file - use file:// URI directly
                "player/${android.net.Uri.encode(item.id)}" +
                    "?srtUrl=${android.net.Uri.encode(item.urls.srt)}" +
                    "&sourceUrl=${android.net.Uri.encode(item.source_url ?: "")}" +
                    "&title=${android.net.Uri.encode(item.title)}"
            } else {
                val baseUrl = ServerConfig.getInstance(context).getApiEndpoint()
                "player/${android.net.Uri.encode(item.id)}" +
                    "?srtUrl=${android.net.Uri.encode("$baseUrl${item.urls.srt}")}" +
                    "&sourceUrl=${android.net.Uri.encode(item.source_url ?: "")}" +
                    "&title=${android.net.Uri.encode(item.title)}"
            }
            navController.navigate(route)
        }
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Thumbnail / Local indicator
            Box(
                modifier = Modifier
                    .size(width = 80.dp, height = 45.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
            ) {
                if (isLocal) {
                    androidx.compose.material3.Icon(
                        Icons.Filled.Smartphone,
                        contentDescription = "Local",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(24.dp).padding(8.dp)
                    )
                } else {
                    item.urls.thumbnail?.let { thumbUrl ->
                        AsyncImage(
                            model = ImageRequest.Builder(LocalContext.current)
                                .data("$baseUrl$thumbUrl")
                                .crossfade(true)
                                .build(),
                            contentDescription = null,
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.fillMaxSize()
                        )
                    }
                }
            }
            Spacer(Modifier.width(12.dp))

            // Info
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.title,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = if (isLocal) "Local Transcription" else item.channel,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(4.dp))
                Row {
                    if (item.has_video) Badge("VIDEO")
                    if (item.has_audio) Badge("AUDIO")
                    if (item.has_thumbnail) Badge("THUMB")
                    if (isLocal) Badge("LOCAL", MaterialTheme.colorScheme.tertiaryContainer)
                }
            }

            Icon(
                Icons.Filled.ChevronRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun Badge(text: String, color: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.primaryContainer) {
    Box(
        modifier = Modifier.padding(horizontal = 4.dp).height(20.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = text,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}