package com.halffd.whispersubs.data

import android.util.Log
import io.ktor.client.*
import io.ktor.client.call.*
import io.ktor.client.engine.android.*
import io.ktor.client.plugins.contentnegotiation.*
import io.ktor.client.request.*
import io.ktor.client.statement.*
import io.ktor.http.*
import io.ktor.serialization.kotlinx.json.*
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.Headers
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class ApiClient(private val serverConfig: ServerConfig) {

    private val json = Json { ignoreUnknownKeys = true }

    private val client = HttpClient(Android) {
        install(ContentNegotiation) {
            json(json)
        }
        expectSuccess = false
    }

    private val okClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS) // SSE: no read timeout
        .build()

    private fun url(endpoint: String): String = serverConfig.getApiEndpoint() + endpoint

    suspend fun getLibrary(): Result<LibraryResponse> {
        return try {
            val response = client.get(url("/api/v1/library")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<LibraryResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getPlayInfo(source: String, srtPath: String?): Result<PlayResponse> {
        return try {
            val encodedSource = URLEncoder.encode(source, "UTF-8")
            val srtParam = srtPath?.let { "&srt=${URLEncoder.encode(it, "UTF-8")}" } ?: ""
            val response = client.get(url("/api/v1/play?source=$encodedSource$srtParam")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<PlayResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Absolute play URL for Media3 (proxy path or direct HLS). */
    fun absoluteUrl(relative: String): String {
        return if (relative.startsWith("http")) relative else url(relative)
    }

    suspend fun getLiveTasks(): Result<LiveResponse> {
        return try {
            val response = client.get(url("/api/v1/live")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<LiveResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Fetch SRT text from a relative or absolute URL. */
    suspend fun fetchSrtText(srtUrl: String): Result<String> {
        return try {
            val full = absoluteUrl(srtUrl)
            val request = Request.Builder()
                .url(full)
                .apply { serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) } }
                .build()
            val response = okClient.newCall(request).await()
            if (response.isSuccessful) {
                Result.success(response.body?.string() ?: "")
            } else {
                Result.failure(RuntimeException("HTTP ${response.code}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Subscribe to the server's SSE subtitle stream for a task.
     * The endpoint is SSE (text/event-stream), NOT WebSocket.
     * Emits each parsed segment; closes when the stream ends.
     */
    suspend fun subscribeSse(
        taskId: String,
        onSegment: (SrtBlock) -> Unit,
        onDone: () -> Unit,
        onError: (String) -> Unit,
    ): Job {
        return CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val sseUrl = url("/api/v1/tasks/$taskId/subtitles/stream")
            val request = Request.Builder()
                .url(sseUrl)
                .header("Accept", "text/event-stream")
                .apply { serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) } }
                .build()

            try {
                val response = okClient.newCall(request).await()
                if (!response.isSuccessful) {
                    onError("SSE HTTP ${response.code}")
                    return@launch
                }
                val source = response.body?.source() ?: run {
                    onError("SSE empty body")
                    return@launch
                }

                var eventType = ""
                var data = ""

                while (true) {
                    val line = try {
                        source.readUtf8LineStrict()
                    } catch (e: java.io.IOException) {
                        break // stream ended
                    }
                    when {
                        line.startsWith("event:") -> eventType = line.substring(6).trim()
                        line.startsWith("data:") -> data += line.substring(5).trim()
                        line.isEmpty() -> {
                            // Dispatch complete event
                            if (eventType == "segment" && data.isNotBlank()) {
                                parseSegment(data)?.let(onSegment)
                            } else if (eventType == "done") {
                                onDone()
                            }
                            eventType = ""
                            data = ""
                        }
                        // ignore comments / unknown lines
                    }
                }
                source.close()
                onDone()
            } catch (e: Exception) {
                onError(e.message ?: "SSE failed")
            }
        }
    }

    private fun parseSegment(data: String): SrtBlock? {
        return try {
            json.decodeFromString<SrtBlock>(data)
        } catch (e: Exception) {
            Log.w("ApiClient", "Failed to parse SSE segment: $data", e)
            null
        }
    }

    // -----------------------------------------------------------------
    // Channels API
    // -----------------------------------------------------------------

    suspend fun getChannels(): Result<ChannelsResponse> {
        return try {
            val response = client.get(url("/api/v1/channels")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<ChannelsResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getChannelVideos(channel: String, refresh: Boolean = false): Result<ChannelVideosResponse> {
        return try {
            val encodedChannel = URLEncoder.encode(channel, "UTF-8")
            val refreshParam = if (refresh) "&refresh=true" else ""
            val response = client.get(url("/api/v1/channels/$encodedChannel/videos?1=1$refreshParam")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<ChannelVideosResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Absolute URL for icons/thumbnails/media relative paths. */
    fun absoluteIconUrl(relative: String): String {
        return if (relative.startsWith("http")) relative else url(relative)
    }

    fun absoluteThumbUrl(relative: String): String {
        return if (relative.startsWith("http")) relative else url(relative)
    }

    /** Start a transcription job for a source URL (POST /transcribe). */
    suspend fun startTranscription(source: String, modelName: String = "large-v3"): Result<TaskResponse> {
        return try {
            val response = client.post(url("/transcribe")) {
                contentType(ContentType.Application.Json)
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
                setBody(TranscribeRequestBody(source = source, model_name = modelName))
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<TaskResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    fun close() {
        client.close()
        okClient.dispatcher.executorService.shutdown()
    }
}

/** OkHttp Call -> coroutine await. */
private suspend fun okhttp3.Call.await(): okhttp3.Response =
    suspendCancellableCoroutine { cont ->
        enqueue(object : okhttp3.Callback {
            override fun onResponse(call: okhttp3.Call, response: okhttp3.Response) {
                cont.resume(response)
            }

            override fun onFailure(call: okhttp3.Call, e: java.io.IOException) {
                cont.resumeWithException(e)
            }
        })
        cont.invokeOnCancellation { cancel() }
    }