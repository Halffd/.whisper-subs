package com.halffd.whispersubs.local

import android.content.Context
import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaCodecList
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import android.util.Log
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Decodes any audio/video file (via content:// URI or path) to 16 kHz mono
 * Float32 PCM suitable for whisper.cpp.
 *
 * Uses MediaExtractor + MediaCodec; resamples to 16 kHz mono with linear
 * interpolation. Streams output through a callback so transcription can run
 * incrementally.
 */
object AudioDecoder {

    private const val TAG = "AudioDecoder"
    private const val TARGET_SAMPLE_RATE = 16000

    /**
     * Decode the given URI to 16kHz mono float PCM, invoking [onChunk] with
     * each converted chunk (samples relative to file start).
     * Returns total number of samples produced.
     *
     * @param blockMs how much audio to hand over per [onChunk] call. whisper.cpp
     *   wants ~30 s of context to transcribe well, so tiny blocks (the old
     *   fixed quarter-second) wreck accuracy; callers pick a size that suits
     *   their latency budget.
     * @param onTotal expected total sample count when the container advertises
     *   a duration, so a caller can render real progress. Null when unknown.
     */
    fun decode(
        context: Context,
        uri: Uri,
        onChunk: (FloatArray) -> Unit,
        blockMs: Int = 1000,
        onTotal: ((Int) -> Unit)? = null,
        cancelled: AtomicBoolean = AtomicBoolean(false),
    ): Int {
        val extractor = MediaExtractor()
        try {
            context.contentResolver.openFileDescriptor(uri, "r")?.use { pfd ->
                extractor.setDataSource(pfd.fileDescriptor)
            } ?: throw IllegalArgumentException("Cannot open $uri")

            var audioTrackIndex = -1
            var format: MediaFormat? = null
            for (i in 0 until extractor.trackCount) {
                val trackFormat = extractor.getTrackFormat(i)
                val mime = trackFormat.getString(MediaFormat.KEY_MIME) ?: continue
                if (mime.startsWith("audio/")) {
                    audioTrackIndex = i
                    format = trackFormat
                    break
                }
            }
            if (audioTrackIndex < 0 || format == null) {
                throw IllegalArgumentException("No audio track in $uri")
            }

            val mime = format.getString(MediaFormat.KEY_MIME)!!
            val sampleRate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE)
            val channelCount = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)

            // Containers usually advertise a duration (microseconds); tell the
            // caller up front so it can show progress for the whole file.
            if (onTotal != null) {
                val durationUs = try {
                    if (format.containsKey(MediaFormat.KEY_DURATION)) {
                        format.getLong(MediaFormat.KEY_DURATION)
                    } else 0L
                } catch (e: Exception) {
                    0L
                }
                if (durationUs > 0) {
                    val expected = (durationUs / 1_000_000.0 * TARGET_SAMPLE_RATE).toInt()
                    if (expected > 0) onTotal(expected)
                }
            }

            extractor.selectTrack(audioTrackIndex)

            val decoder = MediaCodecList(MediaCodecList.REGULAR_CODECS).findDecoderForFormat(format)
                ?: throw IllegalStateException("No decoder for $mime")
            val codec = MediaCodec.createByCodecName(decoder)
            codec.configure(format, null, null, 0)
            codec.start()

            // Accumulate interleaved PCM for resampling
            var accumulated = ArrayList<Float>(sampleRate * channelCount)
            var totalSamples = 0
            var pcmDone = false

            val bufferInfo = MediaCodec.BufferInfo()
            while (!pcmDone && !cancelled.get()) {
                // Feed input
                val inIndex = codec.dequeueInputBuffer(10_000)
                if (inIndex >= 0) {
                    val inputBuffer = codec.getInputBuffer(inIndex)!!
                    val size = extractor.readSampleData(inputBuffer, 0)
                    if (size < 0) {
                        codec.queueInputBuffer(inIndex, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                    } else {
                        codec.queueInputBuffer(inIndex, 0, size, extractor.sampleTime, 0)
                        extractor.advance()
                    }
                }

                // Drain output
                when (val outIndex = codec.dequeueOutputBuffer(bufferInfo, 10_000)) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> { /* new format, ignore */ }
                    MediaCodec.INFO_TRY_AGAIN_LATER -> { /* no output yet */ }
                    MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED -> { /* rebuffers, ignore */ }
                    else -> {
                        val outBuffer = codec.getOutputBuffer(outIndex)!!
                        val shorts = ShortArray(bufferInfo.size / 2)
                        outBuffer.asShortBuffer().get(shorts)

                        // De-interleave + average channels to mono, normalize to [-1, 1]
                        for (i in 0 until shorts.size step channelCount) {
                            var sum = 0f
                            for (ch in 0 until channelCount) {
                                sum += shorts[i + ch].toFloat() / 32768f
                            }
                            accumulated.add(sum / channelCount)
                        }

                        codec.releaseOutputBuffer(outIndex, false)

                        if (bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                            pcmDone = true
                        }

                        // Resample + emit once enough source audio is buffered
                        // for one block (blockMs at the source sample rate).
                        val blockTarget =
                            (sampleRate.toLong() * channelCount * blockMs / 1000L)
                                .coerceAtLeast(1L)
                        if (accumulated.size >= blockTarget) {
                            val (floats, consumed) = resampleTo16kMono(accumulated, sampleRate, channelCount)
                            // Remove consumed prefix
                            accumulated = ArrayList(accumulated.subList(consumed, accumulated.size))
                            if (floats.isNotEmpty()) {
                                totalSamples += floats.size
                                onChunk(floats)
                            }
                        }
                    }
                }
            }

            // Final flush
            if (accumulated.isNotEmpty()) {
                val (floats, _) = resampleTo16kMono(accumulated, sampleRate, channelCount)
                if (floats.isNotEmpty()) {
                    totalSamples += floats.size
                    onChunk(floats)
                }
            }

            codec.stop()
            codec.release()
            Log.d(TAG, "Decoded $totalSamples samples (${totalSamples / TARGET_SAMPLE_RATE}s) from $uri")
            return totalSamples
        } finally {
            extractor.release()
        }
    }

    /**
     * Linear-interpolation resample of accumulated interleaved samples to
     * 16 kHz mono. Returns (converted floats, consumed input sample count).
     * Only fully-convertible samples are consumed (keeps a small tail for
     * interpolation continuity).
     */
    private fun resampleTo16kMono(
        interleaved: ArrayList<Float>,
        sampleRate: Int,
        channelCount: Int,
    ): Pair<FloatArray, Int> {
        val monoCount = interleaved.size / channelCount
        if (monoCount < 2) return Pair(FloatArray(0), 0)

        val ratio = sampleRate.toDouble() / TARGET_SAMPLE_RATE
        val convertible = ((monoCount - 1) / ratio).toInt()  // output samples fully covered
        if (convertible <= 0) return Pair(FloatArray(0), 0)

        val out = FloatArray(convertible)
        for (i in 0 until convertible) {
            val srcPos = i * ratio
            val idx = srcPos.toInt()
            val frac = srcPos - idx
            val s0 = interleaved[idx * channelCount]
            val s1 = if (idx + 1 < monoCount) interleaved[(idx + 1) * channelCount] else s0
            out[i] = s0 + (s1 - s0) * frac.toFloat()
        }

        // Consumed: leave 1 mono-sample tail for next batch continuity
        val consumedMono = ((convertible - 1) * ratio).toInt()
        val consumed = consumedMono * channelCount
        return Pair(out, consumed)
    }
}