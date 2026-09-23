package com.halffd.whispersubs.data

import android.content.Context
import android.content.SharedPreferences
import kotlinx.serialization.json.Json

/**
 * Timestamped cache of the last successful library / channels responses.
 * Lets the app show cached content with a stale banner when the server
 * is unreachable, instead of an empty error screen.
 */
class OfflineCache(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private val json = Json { ignoreUnknownKeys = true }

    /** Cached payload + fetch timestamp. */
    data class Entry<T>(val data: T, val cachedAtMs: Long)

    fun saveLibrary(response: LibraryResponse) {
        put(KEY_LIBRARY, json.encodeToString(LibraryResponse.serializer(), response))
    }

    fun loadLibrary(): Entry<LibraryResponse>? = load(KEY_LIBRARY) { text ->
        json.decodeFromString(LibraryResponse.serializer(), text)
    }

    fun saveChannels(response: ChannelsResponse) {
        put(KEY_CHANNELS, json.encodeToString(ChannelsResponse.serializer(), response))
    }

    fun loadChannels(): Entry<ChannelsResponse>? = load(KEY_CHANNELS) { text ->
        json.decodeFromString(ChannelsResponse.serializer(), text)
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    private fun put(key: String, value: String) {
        prefs.edit()
            .putString(key, value)
            .putLong("$key.time", System.currentTimeMillis())
            .apply()
    }

    private fun <T> load(key: String, decode: (String) -> T): Entry<T>? {
        val text = prefs.getString(key, null) ?: return null
        val cachedAt = prefs.getLong("$key.time", 0L)
        if (cachedAt <= 0L) return null
        return try {
            Entry(decode(text), cachedAt)
        } catch (e: Exception) {
            null
        }
    }

    private companion object {
        const val PREFS_NAME = "offline_cache"
        const val KEY_LIBRARY = "library"
        const val KEY_CHANNELS = "channels"
    }
}
