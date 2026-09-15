package com.halffd.whispersubs.ui.local

import android.content.Intent
import android.net.Uri
import androidx.activity.result.contract.ActivityResultContracts
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
import com.halffd.whispersubs.local.LocalTranscriptionViewModel
import com.halffd.whispersubs.local.ModelManager
import com.halffd.whispersubs.local.TranscriptionService
import kotlinx.coroutines.launch

@Composable
fun LocalScreen() {
    val context = LocalContext.current
    val viewModel: LocalTranscriptionViewModel = hiltViewModel()
    val navController = findNavController()

    val models by viewModel.models.observeAsState(initial = emptyList())
    val downloadedModels by viewModel.downloadedModels.observeAsState(initial = emptyList())
    val selectedModel by viewModel.selectedModel.observeAsState()
    val downloadProgress by viewModel.downloadProgress.observeAsState()
    val isDownloading by viewModel.isDownloading.observeAsState(initial = false)
    val error by viewModel.error.observeAsState()

    LaunchedEffect(Unit) {
        viewModel.loadModels()
    }

    val pickAudio = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == android.app.Activity.RESULT_OK) {
            result.data?.data?.let { uri ->
                startTranscription(uri)
            }
        }
    }

    val pickVideo = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == android.app.Activity.RESULT_OK) {
            result.data?.data?.let { uri ->
                startTranscription(uri)
            }
        }
    }

    fun startTranscription(uri: Uri) {
        selectedModel?.let { model ->
            val intent = Intent(context, TranscriptionService::class.java).apply {
                action = TranscriptionService.ACTION_START
                putExtra(TranscriptionService.EXTRA_MODEL_ID, model.id)
                putExtra(TranscriptionService.EXTRA_SOURCE_PATH, uri.toString())
                putExtra(TranscriptionService.EXTRA_LANGUAGE, "en")
                putExtra(TranscriptionService.EXTRA_TRANSLATE, false)
                putExtra(TranscriptionService.EXTRA_THREADS, 4)
            }
            context.startForegroundService(intent)
            navController.navigate("player/local")
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(stringResource(R.string.local_tab), fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            actions = {
                IconButton(onClick = { viewModel.loadModels() }) {
                    Icon(androidx.compose.material.icons.Icons.Default.Refresh, contentDescription = "Refresh")
                }
            }
        )

        error?.let { msg ->
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp)
                    .background(MaterialTheme.colorScheme.errorContainer)
                    .padding(16.dp)
            ) {
                Text(text = msg, color = MaterialTheme.colorScheme.onErrorContainer)
            }
        }

        // Available models section
        Text(
            text = "Available Models",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.fillMaxWidth().padding(16.dp, 16.dp, 16.dp, 0)
        )

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            items(models) { model ->
                val isDownloaded = ModelManager.isModelDownloaded(context, model.id)
                ModelCard(
                    model = model,
                    isDownloaded = isDownloaded,
                    isSelected = selectedModel?.id == model.id,
                    isDownloading = isDownloading && selectedModel?.id == model.id,
                    progress = downloadProgress,
                    onClick = { viewModel.selectModel(model) },
                    onDownload = { viewModel.downloadModel(model) },
                    onDelete = { viewModel.deleteModel(model) }
                )
            }
        }

        // Quick actions
        if (selectedModel != null && ModelManager.isModelDownloaded(context, selectedModel!!.id)) {
            Spacer(Modifier.height(8.dp))
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(text = "Quick Actions", style = MaterialTheme.typography.titleMedium)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Button(
                        onClick = { pickAudio.launch(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                            type = "audio/*"
                            addCategory(Intent.CATEGORY_OPENABLE)
                        }) },
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                    ) {
                        Text("Transcribe Audio")
                    }
                    Button(
                        onClick = { pickVideo.launch(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                            type = "video/*"
                            addCategory(Intent.CATEGORY_OPENABLE)
                        }) },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Transcribe Video")
                    }
                }
                Button(
                    onClick = {
                        val intent = Intent(context, TranscriptionService::class.java).apply {
                            action = TranscriptionService.ACTION_START
                            putExtra(TranscriptionService.EXTRA_MODEL_ID, selectedModel!!.id)
                            putExtra(TranscriptionService.EXTRA_LANGUAGE, "en")
                        }
                        context.startForegroundService(intent)
                        navController.navigate("player/local")
                    },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)
                ) {
                    Text("Live Microphone Transcription")
                }
            }
        }
    }
}

@Composable
fun ModelCard(
    model: com.halffd.whispersubs.local.ModelManager.WhisperModel,
    isDownloaded: Boolean,
    isSelected: Boolean,
    isDownloading: Boolean,
    progress: Float,
    onClick: () -> Unit,
    onDownload: () -> Unit,
    onDelete: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .border(if (isSelected) 2.dp else 0.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(12.dp)),
        onClick = onClick,
        elevation = CardDefaults.cardElevation(defaultElevation = if (isSelected) 4.dp else 1.dp)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = model.name,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = model.description,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                if (isDownloading) {
                    CircularProgressIndicator(progress = progress, modifier = Modifier.size(24.dp))
                } else if (isDownloaded) {
                    Icon(
                        androidx.compose.material.icons.Icons.Default.CheckCircle,
                        contentDescription = "Downloaded",
                        tint = MaterialTheme.colorScheme.primary,
                        size = 24.dp
                    )
                } else {
                    Icon(
                        androidx.compose.material.icons.Icons.Default.Download,
                        contentDescription = "Download",
                        tint = MaterialTheme.colorScheme.primary,
                        size = 24.dp
                    )
                }
            }

            if (isDownloaded) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        text = "Downloaded",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = onDelete) {
                        Text("Delete")
                    }
                }
            } else if (!isDownloading) {
                TextButton(onClick = onDownload) {
                    Text("Download (${model.sizeMb} MB)")
                }
            }

            if (progress > 0f && progress < 1f && isDownloading) {
                LinearProgressIndicator(progress = progress, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
            }
        }
    }
}