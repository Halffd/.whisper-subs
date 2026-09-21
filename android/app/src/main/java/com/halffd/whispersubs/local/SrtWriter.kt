package com.halffd.whispersubs.local

import android.content.Context
import java.io.File
import java.io.FileWriter
import java.text.DecimalFormat

/**
 * Writes SRT subtitle files from transcript segments.
 */
object SrtWriter {

    private const val TIME_FORMAT = "HH:mm:ss,SSS"
    private val df = DecimalFormat("00")

    /**
     * Write segments to an SRT file.
     * @param context App context for file storage
     * @param segments List of TranscriptSegment (must have startMs/endMs/text)
     * @param baseName Base filename (without extension), e.g. "my_video"
     * @return File object of the created SRT, or null on failure
     */
    fun writeSrt(
        context: Context,
        segments: List<TranscriptSegment>,
        baseName: String,
    ): File? {
        if (segments.isEmpty()) return null

        val dir = File(context.filesDir, "transcriptions")
        if (!dir.exists() && !dir.mkdirs()) {
            return null
        }

        val file = File(dir, "$baseName.srt")
        FileWriter(file).use { writer ->
            for ((index, segment) in segments.withIndex()) {
                writer.write("${index + 1}\n")
                writer.write("${formatTime(segment.startMs)} --> ${formatTime(segment.endMs)}\n")
                writer.write("${segment.text.trim()}\n\n")
            }
        }
        return file
    }

    private fun formatTime(ms: Long): String {
        val totalSeconds = ms / 1000
        val hours = totalSeconds / 3600
        val minutes = (totalSeconds % 3600) / 60
        val seconds = totalSeconds % 60
        val millis = ms % 1000
        return "${df.format(hours)}:${df.format(minutes)}:${df.format(seconds)},${String.format("%03d", millis)}"
    }
}