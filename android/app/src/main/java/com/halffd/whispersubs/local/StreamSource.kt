package com.halffd.whispersubs.local

import android.content.Context
import android.net.Uri
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Fetches a media URL for on-device transcription.
 *
 * The device pipeline is file-based: [AudioDecoder] needs a
 * `ParcelFileDescriptor` (MediaExtractor), and whisper.cpp needs a byte
 * range it can seek. So a remote source is staged into the app cache
 * first and handed back as a `content://`/`file://` Uri — the same shape
 * a locally picked file already has.
 *
 * Design notes:
 * - Downloads are **capped** by [maxBytes]. A 3-hour stream at 128 kbps
 *   is ~170 MB, so the default covers ordinary videos without allowing an
 *   unbounded write to the user's storage.
 * - Progress is reported through [onProgress] so the UI can show a real
 *   bar instead of an indefinite spinner.
 * - A live stream that never ends hits the cap and returns the partial
 *   file, which is the useful behaviour: transcribe what has arrived.
 * - [cancel] stops the transfer and leaves no partial file behind.
 */
object StreamSource {

    private const val TAG = "StreamSource"
    private const val CONNECT_TIMEOUT_MS = 15_000
    private const val READ_TIMEOUT_MS = 30_000
    private const val BUFFER = 64 * 1024

    /** Direct-media and m3u8/hls sources the device can fetch itself. */
    fun isFetchable(input: String): Boolean {
        val trimmed = input.trim()
        if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) return true
        if (trimmed.startsWith("rtmp://") || trimmed.startsWith("rtsp://")) return false
        return false
    }

    /**
     * Download [url] into the cache dir and return a Uri for it.
     *
     * Returns null on failure (network error, non-2xx, cancelled) after
     * logging; the caller decides whether that is fatal.
     *
     * @param maxBytes Hard cap on bytes written (see class docs).
     * @param onProgress (bytesRead, contentLength or -1) on the IO thread.
     */
    fun fetch(
        context: Context,
        url: String,
        cancelled: AtomicBoolean = AtomicBoolean(false),
        maxBytes: Long = DEFAULT_MAX_BYTES,
        onProgress: (Long, Long) -> Unit = { _, _ -> },
    ): Uri? {
        val target = File(
            context.cacheDir,
            "stream_" + Integer.toHexString(url.hashCode()) + extOf(url),
        )
        if (target.exists() && target.length() in 1 until maxBytes) {
            // A previous fetch of the same URL is still meaningful.
            onProgress(target.length(), target.length())
            return Uri.fromFile(target)
        }

        var connection: HttpURLConnection? = null
        try {
            connection = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                requestMethod = "GET"
                // Some CDNs 403 without a browser UA.
                setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14)")
                setRequestProperty("Accept", "*/*")
            }
            val code = connection.responseCode
            if (code !in 200..299) {
                Log.w(TAG, "HTTP $code for $url")
                return null
            }

            val declared = connection.contentLengthLong
            val body: InputStream = connection.inputStream
            var written = 0L
            var lastReport = 0L

            FileOutputStream(target).use { out ->
                val buffer = ByteArray(BUFFER)
                while (!cancelled.get()) {
                    val read = body.read(buffer)
                    if (read < 0) break
                    out.write(buffer, 0, read)
                    written += read
                    if (written - lastReport >= BUFFER * 16L) {
                        lastReport = written
                        onProgress(written, declared)
                    }
                    if (written >= maxBytes) {
                        Log.w(TAG, "Hit ${maxBytes}B cap for $url; using partial file")
                        break
                    }
                }
            }
            if (cancelled.get()) {
                target.delete()
                return null
            }
            if (written == 0L) {
                target.delete()
                Log.w(TAG, "Empty body for $url")
                return null
            }
            onProgress(written, declared)
            return Uri.fromFile(target)
        } catch (e: IOException) {
            Log.w(TAG, "Fetch failed for $url: ${e.message}")
            target.delete()
            return null
        } finally {
            connection?.disconnect()
        }
    }

    /** File extension to cache under, so MediaExtractor sniffs correctly. */
    private fun extOf(url: String): String {
        val path = url.substringBefore('?').substringBefore('#')
        val dot = path.lastIndexOf('.')
        val slash = path.lastIndexOf('/')
        if (dot > slash && dot < path.length - 1) {
            return path.substring(dot).take(8)
        }
        return ".dat"
    }

    /** ~450 MB: covers a 3-hour 128 kbps audio stream; guards the cache. */
    const val DEFAULT_MAX_BYTES = 450L * 1024 * 1024

    /** Remove staged stream files older than [maxAgeMs]. */
    fun prune(context: Context, maxAgeMs: Long = 7L * 24 * 3600 * 1000) {
        val cutoff = System.currentTimeMillis() - maxAgeMs
        context.cacheDir.listFiles()?.forEach { file ->
            if (file.name.startsWith("stream_") && file.lastModified() < cutoff) {
                file.delete()
            }
        }
    }
}
