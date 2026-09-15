package com.halffd.whispersubs.data

import android.content.Context
import android.content.SharedPreferences
import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class ServerConfig private constructor(private val prefs: SharedPreferences) {

    companion object {
        private const val PREFS_NAME = "whisper_subs_config"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_API_KEY = "api_key"
        private var INSTANCE: ServerConfig? = null

        @Volatile
        private var lock = Any()

        fun getInstance(context: Context): ServerConfig {
            return INSTANCE ?: synchronized(lock) {
                INSTANCE ?: ServerConfig(context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)).also { INSTANCE = it }
            }
        }
    }

    var baseUrl: String?
        get() = prefs.getString(KEY_BASE_URL, null)
        set(value) = prefs.edit().putString(KEY_BASE_URL, value).apply()

    var apiKey: String?
        get() = prefs.getString(KEY_API_KEY, null)
        set(value) = prefs.edit().putString(KEY_API_KEY, value).apply()

    fun isConfigured(): Boolean = baseUrl != null && baseUrl.isNotBlank()

    fun clear() {
        prefs.edit().clear().apply()
    }

    fun getApiEndpoint(): String {
        return baseUrl?.trimEnd('/') ?: ""
    }
}