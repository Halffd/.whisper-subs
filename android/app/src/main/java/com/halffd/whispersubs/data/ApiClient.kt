package com.halffd.whispersubs.data

import android.util.Log
import com.halffd.whispersubs.data.Models.*
import io.ktor.client.*
import io.ktor.client.call.*
import io.ktor.client.engine.android.*
import io.ktor.client.plugins.contentnegotiation.*
import io.ktor.client.plugins.logging.*
import io.ktor.client.request.*
import io.ktor.client.statement.*
import io.ktor.http.*
import io.ktor.serialization.kotlinx.json.*
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.Json

class ApiClient(private val serverConfig: ServerConfig) {

    private val client = HttpClient(Android) {
        install(ContentNegotiation) {
            json(Json { ignoreUnknownKeys = true })
        }
        install(Logging) {
            logger = object : Logger {
                override fun log(message: String) = Log.d("Ktor", message)
                override fun log(message: String, ex: Throwable) = Log.e("Ktor", message, ex)
            }
            level = LogLevel.ALL
        }
        defaultRequest {
            header("Accept", "application/json")
            serverConfig.apiKey?.let { header("X-API-Key", it) }
        }
        expectSuccess = false
    }

    suspend fun getLibrary(): Result<LibraryResponse> {
        return try {
            val response = client.get("${
                serverConfig.getApiEndpoint()
            }/api/v1/library").body<LibraryResponse>()
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getPlayInfo(source: String, srtPath: String?): Result<PlayResponse> {
        return try {
            val baseUrl = serverConfig.getApiEndpoint()
            val encodedSource = io.ktor.http.urlEncode(source)
            val srtParam = srtPath?.let { "&srt=${io.ktor.http.urlEncode(it)}" } ?: ""
            val response = client.get("$baseUrl/api/v1/play?source=$encodedSource$srtParam").body<PlayResponse>()
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun streamProxy(source: String, range: String? = null): HttpStatement {
        val baseUrl = serverConfig.getApiEndpoint()
        val encodedSource = io.ktor.http.urlEncode(source)
        val requestBuilder = client.prepareGet("$baseUrl/api/v1/proxy?source=$encodedSource") {
            range?.let { header("Range", it) }
        }
        return client.execute(requestBuilder)
    }

    suspend fun getLiveTasks(): Result<LiveResponse> {
        return try {
            val response = client.get("${
                serverConfig.getApiEndpoint()
            }/api/v1/live").body<LiveResponse>()
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // SSE connection for live subtitles
    fun connectSse(taskId: String): Channel<SseSegment> = Channel(Channel.UNLIMITED) { channel ->
        val baseUrl = serverConfig.getApiEndpoint()
        val job = CoroutineScope(Dispatchers.IO).launch {
            val requestUrl = "$baseUrl/api/v1/tasks/$taskId/subtitles/stream"
            client.webSocket(
                method = HttpMethod.Get,
                host = "",
                port = 80,
                path = "/api/v1/tasks/$taskId/subtitles/stream",
            ) { ws ->
                ws.incoming.consumeEach { frame ->
                    when (frame) {
                        is Frame.Text -> {
                            val text = frame.readText()
                            parseSseLine(text)?.let { segment ->
                                channel.trySend(segment)
                            }
                        }
                        is Frame.Close -> {
                            channel.close()
                        }
                    }
                }
            }
        }
        channel.invokeOnClose { job.cancel() }
    }

    // Fallback: HTTP polling for snapshots
    suspend fun getSnapshot(taskId: String): Result<SubtitleSnapshot> {
        return try {
            val response = client.get("${
                serverConfig.getApiEndpoint()
            }/api/v1/tasks/$taskId/subtitles/snapshot").body<SubtitleSnapshot>()
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    fun close() {
        client.close()
    }

    private fun parseSseLine(line: String): SseSegment? {
        // Parse SSE format: "event: segment\ndata: {...}\n\n"
        val lines = line.split("\n")
        var eventType = ""
        var data = ""
        for (l in lines) {
            if (l.startsWith("event:")) eventType = l.substring(6).trim()
            else if (l.startsWith("data:")) data = l.substring(5).trim()
        }
        if (eventType == "segment" && data.isNotBlank()) {
            try {
                return Json { ignoreUnknownKeys = true }.decodeFromString<SseSegment>(data)
            } catch (e: Exception) {
                Log.w("ApiClient", "Failed to parse SSE segment: $data", e)
            }
        }
        return null
    }
}