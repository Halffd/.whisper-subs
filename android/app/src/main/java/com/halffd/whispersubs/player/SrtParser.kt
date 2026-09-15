package com.halffd.whispersubs.player

import android.text.TextUtils
import com.halffd.whispersubs.data.Models.SrtBlock
import kotlinx.datetime.Duration.Companion.seconds
import kotlinx.datetime.parseSecondsOrNull

object SrtParser {

    /** Parse raw SRT content into list of SrtBlock */
    fun parseSrt(content: String): List<SrtBlock> {
        val blocks = mutableListOf<SrtBlock>()
        val lines = content.split("\n")
        var i = 0
        while (i < lines.size) {
            val line = lines[i].trim()
            if (line.isEmpty()) {
                i++
                continue
            }
            // Index line (e.g., "1")
            val index = line.toIntOrNull() ?: 0
            i++
            if (i >= lines.size) break

            // Timestamp line (e.g., "00:00:01,000 --> 00:00:04,000")
            val timestampLine = lines[i].trim()
            val (startStr, endStr) = timestampLine.split("-->").map { it.trim() }
            val start = parseSrtTime(startStr)
            val end = parseSrtTime(endStr)
            i++

            // Text lines (can be multiple)
            val textLines = mutableListOf<String>()
            while (i < lines.size) {
                val textLine = lines[i].trim()
                if (textLine.isEmpty()) break
                textLines.add(textLine)
                i++
            }
            val text = textLines.joinToString("\n")

            blocks.add(SrtBlock(
                index = index,
                start = start,
                end = end,
                text = text
            ))
            i++
        }
        return blocks
    }

    private fun parseSrtTime(timeStr: String): Double {
        // Format: "HH:MM:SS,mmm" or "HH:MM:SS.mmm"
        val normalized = timeStr.replace(",", ".")
        val parts = normalized.split(":")
        if (parts.size == 3) {
            val hours = parts[0].toIntOrNull() ?: 0
            val minutes = parts[1].toIntOrNull() ?: 0
            val seconds = parts[2].toDoubleOrNull() ?: 0.0
            return hours * 3600.0 + minutes * 60.0 + seconds
        }
        return 0.0
    }

    /** Convert SrtBlock list to Media3 Subtitle format */
    fun toMedia3Cues(blocks: List<SrtBlock>): List<com.google.android.exoplayer.text.Cue> {
        return blocks.map { block ->
            com.google.android.exoplayer.text.Cue(
                text = android.text.SpannedString(block.text),
                startTimeUs = (block.start * 1_000_000).toLong(),
                endTimeUs = (block.end * 1_000_000).toLong()
            )
        }
    }
}