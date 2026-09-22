package com.halffd.whispersubs.local

import android.content.Context
import java.io.File

/**
 * Search within locally saved transcriptions (on-device SRT files).
 * Returns matches with snippet + timestamp.
 */
object LocalSearch {

    data class LocalMatch(
        val timestamp: String,
        val snippet: String,
    )

    data class LocalResult(
        val fileName: String,
        val filePath: String,
        val matchCount: Int,
        val matches: List<LocalMatch>,
        val lastModified: Long,
    )

    fun search(context: Context, query: String, limit: Int = 30): List<LocalResult> {
        val q = query.trim()
        if (q.isEmpty()) return emptyList()

        val dir = File(context.filesDir, "transcriptions")
        if (!dir.exists()) return emptyList()

        val results = mutableListOf<LocalResult>()
        val files = dir.listFiles()?.filter { it.extension == "srt" } ?: return emptyList()

        for (file in files.sortedByDescending { it.lastModified() }) {
            val content = try {
                file.readText()
            } catch (e: Exception) {
                continue
            }

            val matches = mutableListOf<LocalMatch>()
            val blocks = content.split(Regex("\n\\s*\n"))
            for (block in blocks) {
                if (matches.size >= 5) break
                val lines = block.trim().split("\n").map { it.trim() }.filter { it.isNotEmpty() }
                if (lines.size < 2) continue
                var timestamp = ""
                val textLines = mutableListOf<String>()
                for (line in lines) {
                    if (line.contains("-->")) timestamp = line
                    else if (!line.matches(Regex("\\d+"))) textLines.add(line)
                }
                val text = textLines.joinToString(" ")
                if (q.lowercase() in text.lowercase()) {
                    matches.add(LocalMatch(timestamp = timestamp, snippet = snippet(text, q)))
                }
            }

            if (matches.isNotEmpty()) {
                results.add(
                    LocalResult(
                        fileName = file.nameWithoutExtension,
                        filePath = file.absolutePath,
                        matchCount = matches.size,
                        matches = matches,
                        lastModified = file.lastModified(),
                    )
                )
            }
            if (results.size >= limit) break
        }

        results.sortByDescending { it.matchCount }
        return results
    }

    private fun snippet(line: String, query: String, width: Int = 80): String {
        val idx = line.lowercase().indexOf(query.lowercase())
        if (idx < 0) return line.take(width)
        val start = maxOf(0, idx - width / 2)
        val end = minOf(line.length, start + width)
        val prefix = if (start > 0) "..." else ""
        val suffix = if (end < line.length) "..." else ""
        return prefix + line.substring(start, end) + suffix
    }
}