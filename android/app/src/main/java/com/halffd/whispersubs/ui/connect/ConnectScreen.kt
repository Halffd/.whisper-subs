package com.halffd.whispersubs.ui.connect

import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
fun ConnectScreen(onConnected: () -> Unit) {
    val context = LocalContext.current
    val serverConfig: ServerConfig = hiltViewModel()
    val baseUrl by remember { mutableStateOf(serverConfig.baseUrl ?: "") }
    val apiKey by remember { mutableStateOf(serverConfig.apiKey ?: "") }
    val error by remember { mutableStateOf<String?>(null) }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            // TODO: Implement QR scan with CameraX + ML Kit
            android.widget.Toast.makeText(context, "QR scan: use /connect page on phone browser instead", android.widget.Toast.LENGTH_LONG).show()
        }
    }

    fun connect() {
        if (baseUrl.isNotBlank()) {
            serverConfig.baseUrl = baseUrl.trimEnd('/')
            serverConfig.apiKey = if (apiKey.isBlank()) null else apiKey
            onConnected()
        } else {
            error = "Please enter a server URL"
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(
            painter = androidx.compose.ui.graphics.vector.painter.rememberVectorPainter(androidx.compose.material.icons.Icons.Default.Mic),
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            size = 80.dp
        )
        Spacer(Modifier.height(16.dp))
        Text(
            text = stringResource(R.string.app_name),
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = "Enter your WhisperSubs server URL",
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(32.dp))

        OutlinedTextField(
            value = baseUrl,
            onValueChange = { baseUrl = it },
            label = { Text("http://192.168.1.x:8000") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            keyboardOptions = androidx.compose.ui.text.input.KeyboardOptions(
                keyboardType = androidx.compose.ui.text.input.KeyboardType.Uri
            )
        )
        Spacer(Modifier.height(12.dp))

        OutlinedTextField(
            value = apiKey,
            onValueChange = { apiKey = it },
            label = { Text("API Key (optional)") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation()
        )
        Spacer(Modifier.height(16.dp))

        error?.let { msg ->
            Text(text = msg, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(12.dp))
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Button(
                onClick = connect,
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
            ) {
                Text(stringResource(R.string.connect))
            }
            OutlinedButton(
                onClick = {
                    if (androidx.core.content.ContextCompat.checkSelfPermission(context, android.Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                        cameraPermissionLauncher.launch(android.Manifest.permission.CAMERA)
                    }
                },
                modifier = Modifier.weight(1f)
            ) {
                Text(stringResource(R.string.connect_qr))
            }
        }

        Spacer(Modifier.height(24.dp))
        Text(
            text = "Tip: Open http://your-server:8000/connect on your phone browser for QR code",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontSize = 12.sp,
            textAlign = androidx.compose.ui.text.TextAlign.Center
        )
    }
}