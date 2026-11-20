package com.halffd.whispersubs.data

/**
 * Recognises media URLs the server can resolve via yt-dlp.
 *
 * Distinguishing a URL from a search phrase matters: pasting a link used
 * to fall through to a keyword search, which returned nothing useful and
 * left the user with no way to transcribe an ad-hoc link.
 */
object MediaLinks {

    private val SUPPORTED_HOSTS = listOf(
        "youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtube.com",
        "twitch.tv",
        "www.twitch.tv",
        "clips.twitch.tv",
        "vimeo.com",
        "www.vimeo.com",
        "dailymotion.com",
        "www.dailymotion.com",
        "soundcloud.com",
        "www.soundcloud.com",
        "tiktok.com",
        "www.tiktok.com",
        // Direct media files are handed to yt-dlp unchanged.
        "archive.org",
    )

    fun isMediaUrl(text: String): Boolean {
        val trimmed = text.trim()
        if (trimmed.isBlank()) return false

        // A direct media file link (also covers plain .m4a/.mp4 downloads).
        if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            if (MEDIA_EXTENSIONS.any { trimmed.endsWith(it, ignoreCase = true) }) {
                return true
            }
        }

        val host = hostOf(trimmed) ?: return false
        return SUPPORTED_HOSTS.any { host == it || host.endsWith(".$it") }
    }

    /** Host without scheme, lowercased; null when it is not a URL at all. */
    fun hostOf(text: String): String? {
        val withoutScheme = text.removePrefix("http://").removePrefix("https://")
        if (withoutScheme == text) return null
        val host = withoutScheme.substringBefore('/').substringBefore(':')
            .substringBefore('?')
        return host.lowercase().ifBlank { null }
    }

    /**
     * True when the URL points at a live broadcast: `/live` paths, or a
     * channel root (Twitch is live whenever the channel is streaming).
     */
    fun isLiveUrl(text: String): Boolean {
        if (!isMediaUrl(text)) return false
        val path = text.let {
            it.substringAfter("://").substringAfter('/', "")
        }
        if (path.startsWith("live") || path.contains("/live")) return true
        // Twitch channel URLs are live-capable.
        val host = hostOf(text) ?: return false
        return host.contains("twitch.tv")
    }

    /** Human label for the source, used in headers and retries. */
    fun label(text: String): String {
        val host = hostOf(text) ?: return text
        return host.removePrefix("www.") + text.substringBefore('?')
            .substringAfter(host, "")
    }

    private val MEDIA_EXTENSIONS = listOf(
        ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac",
        ".mp4", ".mkv", ".webm", ".mov", ".avi",
    )
}
