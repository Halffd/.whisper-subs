package com.halffd.whispersubs.ui.local

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.border
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.halffd.whispersubs.R
import com.halffd.whispersubs.data.ApiClient
import com.halffd.whispersubs.data.MediaLinks
import com.halffd.whispersubs.data.ServerConfig
import com.halffd.whispersubs.local.LocalTranscriptionViewModel
import com.halffd.whispersubs.local.ModelManager
import com.halffd.whispersubs.local.StreamSource
import com.halffd.whispersubs.local.TranscriptionService
import com.halffd.whispersubs.local.WhisperModel

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun LocalScreen(navController: NavController) {
    val context = LocalContext.current
    val viewModel: LocalTranscriptionViewModel = hiltViewModel()

    val uiState by viewModel.state.collectAsState()

    LaunchedEffect(Unit) {
        viewModel.loadModels()
    }

    fun startFileTranscription(uri: android.net.Uri) {
        val model = uiState.selectedModel ?: return
        val intent = Intent(context, TranscriptionService::class.java).apply {
            action = TranscriptionService.ACTION_START
            putExtra(TranscriptionService.EXTRA_MODEL_ID, model.id)
            putExtra(TranscriptionService.EXTRA_SOURCE_PATH, uri.toString())
            putExtra(TranscriptionService.EXTRA_LANGUAGE, "en")
            putExtra(TranscriptionService.EXTRA_TRANSLATE, false)
            putExtra(TranscriptionService.EXTRA_THREADS, 4)
        }
        context.startForegroundService(intent)
        navController.navigate("local_player")
    }

    val pickAudio = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            result.data?.data?.let { uri -> startFileTranscription(uri) }
        }
    }

    val pickVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            result.data?.data?.let { uri -> startFileTranscription(uri) }
        }
    }

    fun launchMicService() {
        val model = uiState.selectedModel ?: return
        val intent = Intent(context, TranscriptionService::class.java).apply {
            action = TranscriptionService.ACTION_START
            putExtra(TranscriptionService.EXTRA_MODEL_ID, model.id)
            putExtra(TranscriptionService.EXTRA_LANGUAGE, "en")
        }
        context.startForegroundService(intent)
        navController.navigate("local_player")
    }

    // RECORD_AUDIO is a runtime permission: ask for it and start capture only
    // once it is granted, otherwise the service dies before recording.
    val micPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            launchMicService()
        } else {
            Toast.makeText(
                context,
                "Microphone permission is required for live transcription",
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    fun startMicTranscription() {
        val model = uiState.selectedModel ?: return
        val granted = ContextCompat.checkSelfPermission(
            context, Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) {
            launchMicService()
        } else {
            micPermission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    val selectedIsDownloaded =
        uiState.selectedModel?.let { ModelManager.isModelDownloaded(context, it.id) } == true

    // Stream/URL source (fetched on device, or queued on the server).
    var urlInput by remember { mutableStateOf("") }
    var isStreaming by remember { mutableStateOf(false) }
    var streamProgress by remember { mutableStateOf(0f) }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(stringResource(R.string.local_tab), fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            actions = {
                IconButton(onClick = { viewModel.loadModels() }) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                }
            }
        )

        uiState.error?.let { msg ->
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp)
                    .border(1.dp, MaterialTheme.colorScheme.error, RoundedCornerShape(8.dp))
                    .padding(12.dp)
            ) {
                Text(text = msg, color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
            }
        }

        Text(
            text = "On-device models (whisper.cpp)",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.fillMaxWidth().padding(16.dp, 16.dp, 16.dp, 0.dp)
        )

        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            items(uiState.models) { model ->
                ModelCard(
                    model = model,
                    isDownloaded = ModelManager.isModelDownloaded(context, model.id),
                    isSelected = uiState.selectedModel?.id == model.id,
                    isDownloading = uiState.isDownloading && uiState.selectedModel?.id == model.id,
                    progress = uiState.downloadProgress,
                    onClick = { viewModel.selectModel(model) },
                    onDownload = { viewModel.downloadModel(model) },
                    onDelete = { viewModel.deleteModel(model) }
                )
            }
        }

        // Quick actions (enabled when a downloaded model is selected)
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Button(
                    onClick = {
                        pickAudio.launch(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                            type = "audio/*"
                            addCategory(Intent.CATEGORY_OPENABLE)
                        })
                    },
                    modifier = Modifier.weight(1f),
                    enabled = selectedIsDownloaded
                ) {
                    Text("Audio")
                }
                Button(
                    onClick = {
                        pickVideo.launch(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                            type = "video/*"
                            addCategory(Intent.CATEGORY_OPENABLE)
                        })
                    },
                    modifier = Modifier.weight(1f),
                    enabled = selectedIsDownloaded
                ) {
                    Text("Video")
                }
            }
            // Stream/URL source. Two paths:
            //  1. Device-side: a direct media URL (.mp3/.m4a/.mp4/m3u8) is
            //     fetched by StreamSource into the cache and transcribed
            //     locally — no server needed.
            //  2. Server-side: a page link (YouTube/Twitch/…) needs yt-dlp,
            //     which lives on the server, so it is queued there and the
            //     finished file shows up in Local when ready.
            OutlinedTextField(
                value = urlInput,
                onValueChange = { urlInput = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Stream or media URL (m3u8, mp3, mp4…)") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                enabled = selectedIsDownloaded,
            )
            if (isStreaming) {
                Column(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = "Fetching stream… ${(streamProgress * 100).toInt()}%",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.height(4.dp))
                    LinearProgressIndicator(
                        progress = { streamProgress },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
            Button(
                onClick = {
                    val link = urlInput.trim()
                    val model = uiState.selectedModel ?: return@Button
                    if (StreamSource.isFetchable(link)) {
                        isStreaming = true
                        streamProgress = 0f
                        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
                            val uri = StreamSource.fetch(
                                context,
                                link,
                                onProgress = { read, total ->
                                    if (total > 0) {
                                        streamProgress = (read.toFloat() / total).coerceIn(0f, 1f)
                                    }
                                },
                            )
                            withContext(Dispatchers.Main) {
                                isStreaming = false
                                if (uri != null) {
                                    startFileTranscription(uri)
                                } else {
                                    Toast.makeText(
                                        context,
                                        "Could not fetch that stream",
                                        Toast.LENGTH_LONG,
                                    ).show()
                                }
                            }
                        }
                    } else {
                        val api = ApiClient(ServerConfig.getInstance(context))
                        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
                            val entry = api.startDownload(link)
                            withContext(Dispatchers.Main) {
                                entry.onSuccess {
                                    Toast.makeText(
                                        context,
                                        "Resolving ${MediaLinks.label(link)} — it will appear in Local when ready",
                                        Toast.LENGTH_LONG,
                                    ).show()
                                }.onFailure {
                                    Toast.makeText(
                                        context,
                                        "Could not start that link: ${it.message}",
                                        Toast.LENGTH_LONG,
                                    ).show()
                                }
                            }
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = selectedIsDownloaded && urlInput.isNotBlank(),
            ) {
                Text("Transcribe from URL")
            }
            Button(
                onClick = ::startMicTranscription,
                modifier = Modifier.fillMaxWidth(),
                enabled = selectedIsDownloaded,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)
            ) {
                Text("Live Microphone Transcription")
            }
        }
    }
}

@Composable
fun ModelCard(
    model: WhisperModel,
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
            .border(
                width = if (isSelected) 2.dp else 0.dp,
                color = MaterialTheme.colorScheme.primary,
                shape = RoundedCornerShape(12.dp)
            ),
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
                    CircularProgressIndicator(
                        progress = { progress },
                        modifier = Modifier.size(24.dp)
                    )
                } else if (isDownloaded) {
                    Icon(
                        Icons.Filled.CheckCircle,
                        contentDescription = "Downloaded",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(24.dp)
                    )
                } else {
                    Icon(
                        Icons.Filled.Download,
                        contentDescription = "Download",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(24.dp)
                    )
                }
            }

            if (isDownloading) {
                LinearProgressIndicator(
                    progress = { progress },
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
                )
            } else if (isDownloaded) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
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
            } else {
                TextButton(onClick = onDownload) {
                    Text("Download (${model.sizeMb} MB)")
                }
            }
        }
    }
}