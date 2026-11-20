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

    // -----------------------------------------------------------------
    // Search API
    // -----------------------------------------------------------------

    suspend fun searchSubtitles(q: String, channel: String? = null, limit: Int = 50): Result<SubtitleSearchResponse> {
        return try {
            val encodedQ = URLEncoder.encode(q, "UTF-8")
            val channelParam = channel?.let { "&channel=${URLEncoder.encode(it, "UTF-8")}" } ?: ""
            val response = client.get(url("/api/v1/search/subtitles?q=$encodedQ&limit=$limit$channelParam")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<SubtitleSearchResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun searchYoutube(q: String, limit: Int = 10): Result<VideoSearchResponse> {
        return try {
            val encodedQ = URLEncoder.encode(q, "UTF-8")
            val response = client.get(url("/api/v1/search/youtube?q=$encodedQ&limit=$limit")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<VideoSearchResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun searchTwitch(
        channel: String,
        q: String? = null,
        type: String = "all",
        sort: String = "date",
    ): Result<TwitchSearchResponse> {
        return try {
            val encodedChannel = URLEncoder.encode(channel, "UTF-8")
            val qParam = q?.takeIf { it.isNotBlank() }?.let { "&q=${URLEncoder.encode(it, "UTF-8")}" } ?: ""
            val response = client.get(url("/api/v1/search/twitch?channel=$encodedChannel&type=$type&sort=$sort$qParam")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<TwitchSearchResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Recent search queries, most recent first (server per-user history). */
    suspend fun getSearchHistory(limit: Int = 50): Result<HistoryResponse> {
        return try {
            val response = client.get(url("/api/v1/search/history?limit=$limit")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<HistoryResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Record a search query in per-user history (fire-and-forget friendly). */
    suspend fun recordSearchHistory(q: String, scope: String = "subtitles"): Result<Unit> {
        return try {
            val encodedQ = URLEncoder.encode(q, "UTF-8")
            val encodedScope = URLEncoder.encode(scope, "UTF-8")
            val response = client.post(url("/api/v1/search/history?q=$encodedQ&scope=$encodedScope")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(Unit)
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Autocomplete suggestions: recent history + library titles + channel names. */
    suspend fun getSuggestions(q: String, limit: Int = 8): Result<SuggestionsResponse> {
        return try {
            val encodedQ = URLEncoder.encode(q, "UTF-8")
            val response = client.get(url("/api/v1/search/suggestions?q=$encodedQ&limit=$limit")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<SuggestionsResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // -----------------------------------------------------------------
    // YouTube: channel search, subscriptions, feed
    // -----------------------------------------------------------------

    /** Find channels by name or @handle. */
    suspend fun searchYtChannels(q: String, limit: Int = 8): Result<YtChannelSearchResponse> {
        return try {
            val encodedQ = URLEncoder.encode(q, "UTF-8")
            val response = client.get(url("/api/v1/youtube/channels/search?q=$encodedQ&limit=$limit")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<YtChannelSearchResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Resolve a typed channel reference (name/@handle/URL) to a channel. */
    suspend fun resolveYtChannel(channel: String): Result<YtChannel> {
        return try {
            val encoded = URLEncoder.encode(channel, "UTF-8")
            val response = client.get(url("/api/v1/youtube/channel?channel=$encoded")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<YtChannel>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Video list for a channel URL (server caches 30 min unless refreshed). */
    suspend fun getYtChannelVideos(
        channel: String,
        limit: Int = 50,
        refresh: Boolean = false,
    ): Result<YtChannelVideosResponse> {
        return try {
            val encoded = URLEncoder.encode(channel, "UTF-8")
            val response = client.get(
                url("/api/v1/youtube/channel/videos?channel=$encoded&limit=$limit&refresh=$refresh")
            ) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<YtChannelVideosResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Channels this account follows. */
    suspend fun getYtSubscriptions(): Result<YtSubscriptionsResponse> {
        return try {
            val response = client.get(url("/api/v1/youtube/subscriptions")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<YtSubscriptionsResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Follow a channel. */
    suspend fun subscribeYt(channel: YtChannel): Result<Unit> {
        return try {
            val response = client.post(url("/api/v1/youtube/subscriptions")) {
                contentType(ContentType.Application.Json)
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
                setBody(Json.encodeToString(YtSubscribeRequest(channel)))
            }
            if (response.status.isSuccess()) {
                Result.success(Unit)
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** Unfollow a channel by URL. */
    suspend fun unsubscribeYt(channelUrl: String): Result<Unit> {
        return try {
            val encoded = URLEncoder.encode(channelUrl, "UTF-8")
            val response = client.delete(url("/api/v1/youtube/subscriptions?channel=$encoded")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(Unit)
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Ranked feed from followed channels. Ranking runs on the server
     * (recency + watches + watchable length + live), so the app only renders.
     */
    suspend fun getYtFeed(
        limit: Int = 20,
        refresh: Boolean = false,
    ): Result<YtFeedResponse> {
        return try {
            val response = client.get(url("/api/v1/youtube/feed?limit=$limit&refresh=$refresh")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<YtFeedResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // -----------------------------------------------------------------
    // Captions API (YouTube caption tracks)
    // -----------------------------------------------------------------

    /** Caption tracks available for a YouTube URL (human + automatic). */
    suspend fun listCaptions(url: String): Result<CaptionListResponse> {
        return try {
            val encoded = URLEncoder.encode(url, "UTF-8")
            val response = client.get(url("/api/v1/captions?url=$encoded")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<CaptionListResponse>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Fetch the best caption track for [url] as SRT.
     *
     * The server writes it under its captions dir and returns a subtitle URL
     * the player can side-load, so a link with human captions never needs to
     * be transcribed at all.
     */
    suspend fun fetchCaptions(
        url: String,
        dest: String,
        langs: String = "",
        allowAutomatic: Boolean = false,
    ): Result<CaptionFetchResponse> {
        return try {
            val encoded = URLEncoder.encode(url, "UTF-8")
            val response = client.get(
                url(
                    "/api/v1/captions?url=$encoded&dest=$dest" +
                        "&langs=$langs&allow_automatic=$allowAutomatic"
                )
            ) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<CaptionFetchResponse>())
            } else {
                Result.failure(
                    RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}")
                )
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // -----------------------------------------------------------------
    // Downloads API (server-side yt-dlp downloads)
    // -----------------------------------------------------------------

    suspend fun startDownload(source: String): Result<DownloadEntry> {
        return try {
            val response = client.post(url("/api/v1/download")) {
                contentType(ContentType.Application.Json)
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
                setBody(DownloadRequest(source = source))
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<DownloadEntry>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}: ${response.bodyAsText().take(200)}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getDownloadStatus(downloadId: String): Result<DownloadEntry> {
        return try {
            val response = client.get(url("/api/v1/download/$downloadId")) {
                serverConfig.apiKey?.takeIf { it.isNotBlank() }?.let { header("X-API-Key", it) }
            }
            if (response.status.isSuccess()) {
                Result.success(response.body<DownloadEntry>())
            } else {
                Result.failure(RuntimeException("HTTP ${response.status.value}"))
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