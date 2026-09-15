package com.halffd.whispersubs.ui.live

import android.os.Bundle
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
import com.halffd.whispersubs.data.LiveTask
import com.halffd.whispersubs.data.LiveResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

@Composable
fun LiveScreen(onNavigateToSettings: () -> Unit) {
    val context = LocalContext.current
    val apiClient: ApiClient = hiltViewModel()
    val navController = findNavController()
    val liveTasks by remember { mutableStateOf<List<LiveTask>>(emptyList()) }
    val isLoading by remember { mutableStateOf(false) }
    val error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        loadLiveTasks()
    }

    fun loadLiveTasks() {
        isLoading = true
        error = null
        kotlinx.coroutines.CoroutineScope(Dispatchers.IO).launch {
            val result = apiClient.getLiveTasks()
            kotlinx.coroutines.withContext(Dispatchers.Main) {
                isLoading = false
                result.onSuccess { liveTasks = it.live }
                    .onFailure { error = it.message ?: "Failed to load live tasks" }
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(stringResource(R.string.live_tab), fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            actions = {
                IconButton(onClick = loadLiveTasks) {
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
                    Button(onClick = loadLiveTasks) { Text("Retry") }
                }
            }
        } else if (liveTasks.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(androidx.compose.material.icons.Icons.Default.FiberManualRecord, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f), size = 64.dp)
                    Spacer(Modifier.height(16.dp))
                    Text(text = "No live transcriptions running", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    Text(text = "Start a live job from the server", fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f))
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(liveTasks) { task ->
                    LiveTaskCard(task = task, navController = navController)
                }
            }
        }
    }
}

@Composable
fun LiveTaskCard(task: LiveTask, navController: NavController) {
    val context = LocalContext.current
    val baseUrl = com.halffd.whispersubs.data.ServerConfig.getInstance(context).getApiEndpoint()

    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = {
            val srtUrl = task.subs_url ?: ""
            val playerArgs = Bundle().apply {
                putString("itemId", task.task_id)
                putString("title", task.source)
                putString("sourceUrl", task.source)
                putString("srtUrl", "${baseUrl}$srtUrl")
            }
            navController.navigate("player/${task.task_id}", playerArgs)
        }
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .clip(androidx.compose.foundation.shape.CircleShape)
                    .background(
                        if (task.status == "processing") MaterialTheme.colorScheme.primaryContainer
                        else if (task.status == "pending") MaterialTheme.colorScheme.tertiaryContainer
                        else MaterialTheme.colorScheme.errorContainer
                    ),
                contentAlignment = Alignment.Center
            ) {
                if (task.is_live) {
                    Icon(
                        androidx.compose.material.icons.Icons.Default.FiberManualRecord,
                        contentDescription = "Live",
                        tint = MaterialTheme.colorScheme.error,
                        size = 20.dp
                    )
                } else {
                    CircularProgressIndicator(
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp)
                    )
                }
            }
            Spacer(Modifier.width(12.dp))

            Column(modifier = Modifier.weight(1f).padding(top = 8.dp, bottom = 8.dp)) {
                Text(
                    text = task.source.takeLast(50),
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(2.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = task.status.uppercase(),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(Modifier.width(8.dp))
                    if (task.has_subtitles == true) {
                        Badge(text = "SUBS", color = MaterialTheme.colorScheme.primaryContainer)
                    }
                    Text(
                        text = "Model: ${task.model_name}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                    )
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