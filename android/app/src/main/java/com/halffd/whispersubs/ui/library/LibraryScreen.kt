package com.halffd.whispersubs.ui.library

import android.os.Bundle
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import androidx.navigation.compose.findNavController
import com.halffd.whispersubs.R
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.LibraryItem
import com.halffd.whispersubs.data.LibraryResponse
import coil3.compose.AsyncImage
import coil3.request.ImageRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

@Composable
fun LibraryScreen(onNavigateToSettings: () -> Unit) {
    val context = LocalContext.current
    val apiClient: ApiClient = hiltViewModel()
    val navController = findNavController()
    val items by remember { mutableStateOf<List<LibraryItem>>(emptyList()) }
    val isLoading by remember { mutableStateOf(false) }
    val error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        loadLibrary()
    }

    fun loadLibrary() {
        isLoading = true
        error = null
        kotlinx.coroutines.CoroutineScope(Dispatchers.IO).launch {
            val result = apiClient.getLibrary()
            kotlinx.coroutines.withContext(Dispatchers.Main) {
                isLoading = false
                result.onSuccess { items = it.library }
                    .onFailure { error = it.message ?: "Failed to load library" }
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(stringResource(R.string.library_tab), fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            actions = {
                IconButton(onClick = loadLibrary) {
                    Icon(androidx.compose.material.icons.Icons.Default.Refresh, contentDescription = "Refresh")
                }
                IconButton(onClick = onNavigateToSettings) {
                    Icon(androidx.compose.material.icons.Icons.Default.Settings, contentDescription = "Settings")
                }
            }
        )

        if (isLoading) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (error != null) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(text = error!!, color = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = loadLibrary) { Text("Retry") }
                }
            }
        } else if (items.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(androidx.compose.material.icons.Icons.Default.VideoLibrary, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f), size = 64.dp)
                    Spacer(Modifier.height(16.dp))
                    Text(text = stringResource(R.string.no_items), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(items) { item ->
                    LibraryItemCard(item = item, navController = navController)
                }
            }
        }
    }
}

@Composable
fun LibraryItemCard(item: LibraryItem, navController: NavController) {
    val context = LocalContext.current
    val baseUrl = com.halffd.whispersubs.data.ServerConfig.getInstance(context).getApiEndpoint()

    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = {
            val srtUrl = item.urls.srt
            val playerArgs = Bundle().apply {
                putString("itemId", item.id)
                putString("title", item.title)
                putString("sourceUrl", item.source_url ?: "")
                putString("srtUrl", "${baseUrl}$srtUrl")
            }
            navController.navigate("player/${item.id}", playerArgs)
        }
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Thumbnail
            Box(
                modifier = Modifier
                    .size(80.dp, 45.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
            ) {
                item.urls.thumbnail?.let { thumbUrl ->
                    AsyncImage(
                        model = ImageRequest.Builder(LocalContext.current)
                            .data("$baseUrl$thumbUrl")
                            .crossfade(true)
                            .build(),
                        contentDescription = null,
                        contentScale = androidx.compose.ui.layout.ContentScale.Crop,
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
            Spacer(Modifier.width(12.dp))

            // Info
            Column(modifier = Modifier.weight(1f).padding(top = 8.dp, bottom = 8.dp)) {
                Text(
                    text = item.title,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = item.channel,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(4.dp))
                Row {
                    if (item.has_video) {
                        Badge(text = "VIDEO", color = MaterialTheme.colorScheme.primaryContainer)
                        Spacer(Modifier.width(4.dp))
                    }
                    if (item.has_audio) {
                        Badge(text = "AUDIO", color = MaterialTheme.colorScheme.secondaryContainer)
                        Spacer(Modifier.width(4.dp))
                    }
                    if (item.has_thumbnail) {
                        Badge(text = "THUMB", color = MaterialTheme.colorScheme.tertiaryContainer)
                    }
                }
            }

            Icon(
                painter = androidx.compose.ui.graphics.vector.painter.rememberVectorPainter(androidx.compose.material.icons.Icons.Default.ChevronRight),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun Badge(text: String, color: androidx.compose.ui.graphics.Color) {
    Box(
        modifier = Modifier.padding(4.dp, 0.dp).height(20.dp).padding(horizontal = 8.dp),
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