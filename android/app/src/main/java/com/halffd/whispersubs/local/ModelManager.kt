package com.halffd.whispersubs.local

import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.URL
import java.util.concurrent.TimeUnit

data class WhisperModel(
    val id: String,
    val name: String,
    val sizeMb: Int,
    val url: String,
    val description: String
) {
    val filename = "$id.bin"
}

object ModelManager {
    private const val TAG = "ModelManager"
    private const val MODELS_DIR = "whisper_models"
    private const val BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"

    // Available models (ggml format for whisper.cpp)
    val AVAILABLE_MODELS = listOf(
        WhisperModel(
            id = "ggml-tiny",
            name = "Tiny (39 MB)",
            sizeMb = 39,
            url = "${BASE_URL}ggml-tiny.bin",
            description = "Fastest, English-only, ~32x realtime"
        ),
        WhisperModel(
            id = "ggml-tiny.en",
            name = "Tiny.en (39 MB)",
            sizeMb = 39,
            url = "${BASE_URL}ggml-tiny.en.bin",
            description = "English-only, fastest"
        ),
        WhisperModel(
            id = "ggml-base",
            name = "Base (74 MB)",
            sizeMb = 74,
            url = "${BASE_URL}ggml-base.bin",
            description = "Good balance, multilingual, ~16x realtime"
        ),
        WhisperModel(
            id = "ggml-base.en",
            name = "Base.en (74 MB)",
            sizeMb = 74,
            url = "${BASE_URL}ggml-base.en.bin",
            description = "English-only, good balance"
        ),
        WhisperModel(
            id = "ggml-small",
            name = "Small (244 MB)",
            sizeMb = 244,
            url = "${BASE_URL}ggml-small.bin",
            description = "Better accuracy, ~6x realtime"
        ),
        WhisperModel(
            id = "ggml-small.en",
            name = "Small.en (244 MB)",
            sizeMb = 244,
            url = "${BASE_URL}ggml-small.en.bin",
            description = "English-only, better accuracy"
        ),
        WhisperModel(
            id = "ggml-medium",
            name = "Medium (769 MB)",
            sizeMb = 769,
            url = "${BASE_URL}ggml-medium.bin",
            description = "High accuracy, ~2x realtime"
        ),
        WhisperModel(
            id = "ggml-large-v3",
            name = "Large-v3 (1550 MB)",
            sizeMb = 1550,
            url = "${BASE_URL}ggml-large-v3.bin",
            description = "Best accuracy, ~1x realtime"
        )
    )

    fun getModelsDir(context: Context): File {
        return File(context.filesDir, MODELS_DIR).apply { mkdirs() }
    }

    fun getModelPath(context: Context, modelId: String): File {
        return File(getModelsDir(context), "${modelId}.bin")
    }

    fun isModelDownloaded(context: Context, modelId: String): Boolean {
        return getModelPath(context, modelId).exists()
    }

    fun getDownloadedModels(context: Context): List<WhisperModel> {
        return AVAILABLE_MODELS.filter { isModelDownloaded(context, it.id) }
    }

    fun downloadModel(
        context: Context,
        model: WhisperModel,
        progressListener: (Float) -> Unit
    ): Boolean {
        val destFile = getModelPath(context, model.id)
        val tempFile = File(destFile.parentFile, "${destFile.name}.tmp")

        val client = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(300, TimeUnit.SECONDS)
            .build()

        val request = Request.Builder().url(model.url).build()

        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                Log.e(TAG, "Download failed: ${response.code}")
                return false
            }

            val body = response.body ?: return false
            val contentLength = body.contentLength()
            var downloaded = 0L

            val inputStream = body.byteStream()
            val outputStream = FileOutputStream(tempFile)
            val buffer = ByteArray(8192)
            var len: Int

            while (inputStream.read(buffer).also { len = it } != -1) {
                outputStream.write(buffer, 0, len)
                downloaded += len
                if (contentLength > 0) {
                    progressListener(downloaded.toFloat() / contentLength)
                }
            }

            outputStream.close()
            inputStream.close()

            // Verify file size roughly matches
            if (destFile.length() > 0 && Math.abs(destFile.length() - model.sizeMb * 1024L * 1024L) < model.sizeMb * 1024L * 1024L * 0.1) {
                tempFile.renameTo(destFile)
                return true
            }

            return false
        } catch (e: IOException) {
            Log.e(TAG, "Download error", e)
            tempFile.delete()
            return false
        }
    }

    fun deleteModel(context: Context, modelId: String): Boolean {
        return getModelPath(context, modelId).delete()
    }

    fun getModelById(modelId: String): WhisperModel? {
        return AVAILABLE_MODELS.firstOrNull { it.id == modelId }
    }
}