package com.halffd.whispersubs.data

import android.content.Context

/**
 * PotPlayer-style resume: stores the last playback position per item so
 * reopening a video continues where it left off. Entries are cleared when
 * playback reaches the end (position >= duration - 10s) or stays idle < 5s.
 */
class ResumeStore(context: Context) {

    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun save(key: String, positionMs: Long, durationMs: Long) {
        val edit = prefs.edit()
        when {
            durationMs > 0 && positionMs >= durationMs - 10_000 -> edit.remove(key)
            positionMs < 5_000 -> edit.remove(key)
            else -> edit.putLong(key, positionMs)
        }
        edit.apply()
    }

    fun load(key: String): Long = prefs.getLong(key, 0L)

    private companion object {
        const val PREFS_NAME = "resume_positions"
    }
}
