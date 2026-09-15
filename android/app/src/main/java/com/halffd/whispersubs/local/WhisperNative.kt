package com.halffd.whispersubs.local

import android.util.Log

class WhisperNative private constructor(private val handle: Long) {

    companion object {
        private const val TAG = "WhisperNative"
        private var loaded = false

        fun loadLibrary() {
            if (!loaded) {
                System.loadLibrary("whisper_jni")
                loaded = true
            }
        }

        @JvmStatic
        fun init(
            modelPath: String,
            nThreads: Int = 4,
            translate: Boolean = false,
            language: String? = null
        ): WhisperNative? {
            loadLibrary()
            val handle = nativeInit(modelPath, nThreads, translate, language)
            return if (handle != 0L) WhisperNative(handle) else null
        }

        private external fun nativeInit(
            modelPath: String,
            nThreads: Int,
            translate: Boolean,
            language: String?
        ): Long
    }

    external fun free()

    @Throws(WhisperException::class)
    fun transcribe(audio: FloatArray, sampleRate: Int = 16000): Int {
        val result = nativeTranscribe(handle, audio, audio.size, sampleRate)
        if (result != 0) throw WhisperException("Transcription failed: $result")
        return result
    }

    fun getSegmentCount(): Int = nativeGetSegmentCount(handle)

    fun getSegment(index: Int): TranscriptSegment? {
        return nativeGetSegment(handle, index)
    }

    fun getLanguage(): String = nativeGetLanguage(handle) ?: "auto"

    fun getProgress(): Float = nativeGetProgress(handle)

    private external fun nativeTranscribe(handle: Long, audio: FloatArray, audioLength: Int, sampleRate: Int): Int
    private external fun nativeGetSegmentCount(handle: Long): Int
    private external fun nativeGetSegment(handle: Long, index: Int): TranscriptSegment?
    private external fun nativeGetLanguage(handle: Long): String?
    private external fun nativeGetProgress(handle: Long): Float
}

data class TranscriptSegment(
    val text: String,
    val startMs: Long,
    val endMs: Long
)

class WhisperException(message: String) : Exception(message)