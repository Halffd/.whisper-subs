package com.halffd.whispersubs.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Repository for locally saved transcriptions (on-device SRT files).
 */
class LocalLibraryRepository(private val context: Context) {

    /** Get all locally saved transcriptions from the app's transcriptions directory. */
    suspend fun getLocalItems(): Result<List<LibraryItem>> = withContext(Dispatchers.IO) {
        try {
            val dir = File(context.filesDir, "transcriptions")
            if (!dir.exists()) {
                return@withContext Result.success(emptyList())
            }

            val srtFiles = (dir.listFiles()?.filter { it.extension == "srt" }?.sortedByDescending { it.lastModified() } ?: emptyArray<File>()) as Array<File>

            val items = srtFiles.map { file ->
                val baseName = file.nameWithoutExtension
                val segmentCount = file.readText().split("\n\n").count { it.trim().isNotEmpty() }

                LibraryItem(
                    id = "local:${file.name}",
                    title = baseName.replace("transcription_", ""),
                    channel = "Local",
                    path = file.absolutePath,
                    srt_path = file.absolutePath,
                    media = emptyList(),
                    has_video = false,
                    has_audio = false,
                    has_thumbnail = false,
                    thumbnail_path = null,
                    source_url = null,
                    size_bytes = file.length(),
                    urls = Urls(
                        srt = "file://${file.absolutePath}",
                        media = emptyList(),
                        thumbnail = null,
                        play = "file://${file.absolutePath}"
                    )
                )
            }

            Result.success(items)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}