package com.halffd.whispersubs.ui.settings

import androidx.compose.foundation.layout.*
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
import com.halffd.whispersubs.R
import com.halffd.whispersubs.data.ServerConfig

@Composable
fun SettingsScreen() {
    val context = LocalContext.current
    val serverConfig: ServerConfig = hiltViewModel()
    val baseUrl by remember { mutableStateOf(serverConfig.baseUrl ?: "") }
    val apiKey by remember { mutableStateOf(serverConfig.apiKey ?: "") }

    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        TopAppBar(
            title = { Text(stringResource(R.string.settings), fontWeight = FontWeight.Bold) },
            colors = TopAppBarDefaults.mediumTopAppBarColors(containerColor = MaterialTheme.colorScheme.surface)
        )

        Card(
            modifier = Modifier.fillMaxWidth().padding(16.dp)
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(text = "Server Connection", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Text(text = "Current: ${if (baseUrl.isNotBlank()) baseUrl else "Not configured"}", style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(16.dp))
                Button(onClick = {
                    serverConfig.clear()
                    baseUrl = ""
                }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                    Text("Disconnect")
                }
            }
        }

        Card(
            modifier = Modifier.fillMaxWidth().padding(16.dp)
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(text = "About", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Text(text = "WhisperSubs Mobile v1.0", style = MaterialTheme.typography.bodyMedium)
                Text(text = "Connects to WhisperSubs API server", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(8.dp))
                Text(text = "Server: $baseUrl", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f))
            }
        }
    }
}