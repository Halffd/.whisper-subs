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

@Serializable
data class ChannelsResponse(
    val channels: List<Channel>,
    val count: Int
)

@Serializable
data class Channel(
    val name: String,
    val transcribed: Int,
    val unfinished: Int
)

@Serializable
data class ChannelVideosResponse(
    val channel: String,
    val channel_name: String?,
    val channel_url: String?,
    val subscribers: Long?,
    val avatar_url: String?,
    val videos: List<ChannelVideo>,
    val total: Int,
    val transcribed_count: Int
)

@Serializable
data class ChannelVideo(
    val id: String,
    val title: String,
    val date: String?,
    val model: String?,
    val video_id: String?,
    val source_url: String?,
    val has_srt: Boolean,
    val has_media: Boolean,
    val media: List<MediaFile>,
    val has_thumbnail: Boolean,
    val thumbnail_url: String?,
    val srt_url: String?,
    val duration: Double?,
    val views: Long?,
    val likes: Long?,
    val transcribed: Boolean,
    val has_video: Boolean = false,
    val has_audio: Boolean = false
)

@Serializable
data class VideoStatsResponse(
    val url: String,
    val title: String?,
    val views: Long?,
    val likes: Long?,
    val duration: Double?,
    val upload_date: String?,
    val channel: String?,
    val thumbnail: String?,
    val description: String?
)

@Serializable
data class TaskResponse(
    val task_id: String,
    val status: String,
    val source: String,
    val model_name: String,
    val created_at: String
)

@Serializable
data class TranscribeRequestBody(
    val source: String,
    val model_name: String
)

@Serializable
data class SubtitleSearchResponse(
    val results: List<SubtitleSearchResult>,
    val count: Int,
    val query: String
)

@Serializable
data class SubtitleSearchResult(
    val id: String,
    val title: String,
    val channel: String,
    val date: String?,
    val model: String?,
    val match_count: Int,
    val matches: List<SubtitleMatch>,
    val srt_url: String,
    val play_url: String?,
    val source_url: String? = null
)

@Serializable
data class SubtitleMatch(
    val timestamp: String,
    val snippet: String
)

@Serializable
data class VideoSearchResponse(
    val results: List<VideoSearchResult>,
    val count: Int,
    val query: String
)

@Serializable
data class VideoSearchResult(
    val id: String,
    val title: String?,
    val duration: Double?,
    val views: Long?,
    val thumbnail_url: String?,
    val url: String?,
    val channel: String? = null,
    val live: Boolean = false
)

@Serializable
data class TwitchSearchResponse(
    val live: VideoSearchResult?,
    val vods: List<VideoSearchResult>,
    val total: Int,
    val channel: String
)

@Serializable
data class DownloadRequest(
    val source: String
)

@Serializable
data class DownloadEntry(
    val download_id: String,
    val source: String,
    val status: String,          // pending | processing | merging | completed | failed
    val progress: Double? = null,
    val speed_mbps: Double? = null,
    val downloaded_mb: Double? = null,
    val title: String? = null,
    val channel: String? = null,
    val duration: Double? = null,
    val thumbnail: String? = null,
    val file_path: String? = null,
    val rel_path: String? = null,
    val error: String? = null,
    val created_at: Double? = null,
    val updated_at: Double? = null,
)

@Serializable
data class Suggestion(
    val text: String,
    val source: String,          // history | library | channel
    val scope: String? = null
)

@Serializable
data class SuggestionsResponse(
    val suggestions: List<Suggestion>,
    val query: String
)

/** One recorded search query (server-side per-user history). */
@Serializable
data class HistoryEntry(
    val q: String,
    val scope: String? = null,
    val at: String? = null,
)

/** Response of GET /api/v1/search/history. */
@Serializable
data class HistoryResponse(
    val history: List<HistoryEntry>,
)

/** One caption track reported by GET /api/v1/captions. */
@Serializable
data class CaptionTrackInfo(
    val lang: String,
    val ext: String = "srt",
    val automatic: Boolean = false,
    val name: String = "",
)

@Serializable
data class CaptionListResponse(
    val url: String = "",
    val tracks: List<CaptionTrackInfo> = emptyList(),
    val has_human: Boolean = false,
)

@Serializable
data class CaptionFetchResponse(
    val ok: Boolean = false,
    val path: String? = null,
    val rel_path: String? = null,
    val lang: String? = null,
    val automatic: Boolean = false,
    val subtitle_url: String? = null,
)
// ---------------------------------------------------------------------------
// YouTube: channel discovery, subscriptions, feed (server /api/v1/youtube/*)
// ---------------------------------------------------------------------------

/** A channel found via YouTube search, or resolved from a typed reference. */
@Serializable
data class YtChannel(
    val id: String = "",
    val name: String = "",
    val url: String = "",
    val handle: String = "",
    val avatar: String = "",
    val subscribers: Int? = null,
    val video_count: Int? = null,
    val description: String = "",
    /** How many search hits pointed here (rank signal). */
    val hits: Int = 0,
    /** Whether this account already follows the channel. */
    val subscribed: Boolean = false,
)

@Serializable
data class YtChannelSearchResponse(
    val results: List<YtChannel> = emptyList(),
    val count: Int = 0,
    val query: String = "",
)

/** A video from a followed channel (the feed / channel-videos shape). */
@Serializable
data class YtVideo(
    val id: String = "",
    val title: String = "",
    val url: String = "",
    val duration: Double? = null,
    val views: Long? = null,
    val timestamp: Double? = null,
    val thumbnail_url: String? = null,
    val channel: String = "",
    val channel_url: String = "",
    val live: Boolean = false,
    /** Feed only: rank score and the reasons it earned. */
    val score: Double? = null,
    val reasons: List<String> = emptyList(),
)

@Serializable
data class YtChannelVideosResponse(
    val channel: String = "",
    val videos: List<YtVideo> = emptyList(),
    val count: Int = 0,
)

@Serializable
data class YtSubscriptionsResponse(
    val subscriptions: List<YtChannel> = emptyList(),
    val count: Int = 0,
)

@Serializable
data class YtSubscribeRequest(
    val channel: YtChannel,
)

@Serializable
data class YtFeedResponse(
    val feed: List<YtVideo> = emptyList(),
    val count: Int = 0,
    val subscribed: Int = 0,
)
