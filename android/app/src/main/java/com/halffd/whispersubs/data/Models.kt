package com.halffd.whispersubs.data

import kotlinx.serialization.Serializable

@Serializable
data class LibraryResponse(
    val library: List<LibraryItem>,
    val count: Int
)

@Serializable
data class LibraryItem(
    val id: String,
    val title: String,
    val channel: String,
    val path: String,
    val srt_path: String,
    val media: List<MediaFile>,
    val has_video: Boolean,
    val has_audio: Boolean,
    val has_thumbnail: Boolean,
    val thumbnail_path: String?,
    val source_url: String?,
    val size_bytes: Long,
    val urls: Urls
)

@Serializable
data class MediaFile(
    val type: String,
    val format: String,
    val url: String
)

@Serializable
data class Urls(
    val srt: String,
    val media: List<MediaFile>,
    val thumbnail: String?,
    val play: String?
)

@Serializable
data class PlayResponse(
    val source: String,
    val url: String,
    val protocol: String,
    val ext: String,
    val format_note: String,
    val width: Int?,
    val height: Int?,
    val duration: Double?,
    val title: String,
    val channel: String?,
    val thumbnail: String?,
    val headers: Map<String, String>,
    val is_live: Boolean,
    val resolved_at: Double,
    val resolver: String,
    val play_url: String,
    val srt_url: String?
)

@Serializable
data class LiveResponse(
    val live: List<LiveTask>,
    val count: Int
)

@Serializable
data class LiveTask(
    val task_id: String,
    val status: String,
    val source: String,
    val model_name: String,
    val is_live: Boolean,
    val created_at: String,
    val error: String?,
    val has_subtitles: Boolean?,
    val sse_url: String?,
    val snapshot_url: String?,
    val subs_url: String?
)

@Serializable
data class SrtBlock(
    val index: Int,
    val start: Double,
    val end: Double,
    val text: String
)

@Serializable
data class SubtitleSnapshot(
    val task_id: String,
    val source_path: String,
    val is_final: Boolean,
    val blocks: List<SrtBlock>,
    val count: Int
)

@Serializable
data class SseSegment(
    val index: Int,
    val start: Double,
    val end: Double,
    val text: String
)

@Serializable
data class SseEvent(
    val event: String,
    val data: String
)