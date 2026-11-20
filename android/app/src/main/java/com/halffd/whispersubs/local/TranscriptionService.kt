package com.halffd.whispersubs.local

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import android.util.Log
import com.halffd.whispersubs.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.Date
import java.util.concurrent.atomic.AtomicBoolean

class TranscriptionService : Service() {

    companion object {
        private const val TAG = "TranscriptionService"
        const val CHANNEL_ID = "transcription_channel"
        const val NOTIFICATION_ID = 1001
        const val ACTION_START = "com.halffd.whispersubs.START_TRANSCRIPTION"
        const val ACTION_STOP = "com.halffd.whispersubs.STOP_TRANSCRIPTION"
        const val ACTION_PAUSE = "com.halffd.whispersubs.PAUSE_TRANSCRIPTION"
        const val EXTRA_MODEL_ID = "model_id"
        const val EXTRA_SOURCE_PATH = "source_path"
        const val EXTRA_LANGUAGE = "language"
        const val EXTRA_TRANSLATE = "translate"
        const val EXTRA_THREADS = "threads"

        /** Audio handed to whisper per call when transcribing a whole file. */
        private const val FILE_BLOCK_MS = 30_000

        /** Audio accumulated before each call in live mode (latency vs quality). */
        private const val MIC_WINDOW_MS = 5_000

        // Static state mirror so UI can observe the service without binding
        private val _sharedState = MutableStateFlow<TranscriptionState>(TranscriptionState.Idle)
        val sharedState: StateFlow<TranscriptionState> = _sharedState

        private val _sharedSegments = MutableStateFlow<List<TranscriptSegment>>(emptyList())
        val sharedSegments: StateFlow<List<TranscriptSegment>> = _sharedSegments

        // The service cannot be bound (onBind returns null), so every value the
        // UI needs has to be mirrored here. Progress had no mirror at all,
        // which is why the bar never moved.
        private val _sharedProgress = MutableStateFlow(0f)
        val sharedProgress: StateFlow<Float> = _sharedProgress

        internal fun publishProgress(value: Float) {
            _sharedProgress.value = value.coerceIn(0f, 1f)
        }

        internal fun resetSharedState() {
            _sharedState.value = TranscriptionState.Idle
            _sharedSegments.value = emptyList()
            _sharedProgress.value = 0f
        }

        internal fun publishState(state: TranscriptionState) {
            _sharedState.value = state
        }

        internal fun publishSegment(segment: TranscriptSegment) {
            _sharedSegments.value = _sharedSegments.value + segment
        }
    }

    private var whisper: WhisperNative? = null
    private var audioRecord: AudioRecord? = null
    private var isRecording = AtomicBoolean(false)
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var isPaused = AtomicBoolean(false)
    private val handler = Handler(Looper.getMainLooper())
    private val notificationManager: NotificationManager by lazy {
        getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    }

    // Live data for UI updates
    private val _state = MutableLiveData<TranscriptionState>()
    val state: LiveData<TranscriptionState> = _state

    private val _currentSegment = MutableLiveData<TranscriptSegment?>()
    val currentSegment: LiveData<TranscriptSegment?> = _currentSegment

    private val _progress = MutableLiveData<Float>()
    val progress: LiveData<Float> = _progress

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        when (action) {
            ACTION_START -> startTranscription(intent)
            ACTION_STOP -> stopTranscription()
            ACTION_PAUSE -> togglePause()
        }
        return START_STICKY
    }

    private fun startTranscription(intent: Intent) {
        val modelId = intent.getStringExtra(EXTRA_MODEL_ID) ?: "ggml-base.en"
        val sourcePath = intent.getStringExtra(EXTRA_SOURCE_PATH)
        val language = intent.getStringExtra(EXTRA_LANGUAGE) ?: "en"
        val translate = intent.getBooleanExtra(EXTRA_TRANSLATE, false)
        val threads = intent.getIntExtra(EXTRA_THREADS, 4)

        val modelPath = ModelManager.getModelPath(this, modelId).absolutePath
        if (!File(modelPath).exists()) {
            fail("Model not found: $modelId")
            return
        }

        // Resolve the source *before* anything heavy: a picked file arrives as
        // a content:// URI, and File(uri.toString()).exists() is always false,
        // which used to silently fall through to microphone capture.
        val sourceUri = sourcePath?.let { toMediaUri(it) }
        if (sourcePath != null && sourceUri == null) {
            fail("Cannot open that file")
            return
        }

        // Live capture needs the mic permission; without it AudioRecord
        // construction throws and the service dies with no explanation.
        val needsMic = sourceUri == null
        if (needsMic && !hasMicPermission()) {
            fail("Microphone permission is required for live transcription")
            return
        }

        whisper = WhisperNative.init(modelPath, threads, translate, language)
            ?: run {
                fail("Failed to initialize Whisper")
                return
            }

        // Fresh run: clear any previous transcript/progress so the UI does not
        // show the last session's state.
        _sharedSegments.value = emptyList()
        publishProgress(0f)
        _state.value = TranscriptionState.Transcribing
        publishState(TranscriptionState.Transcribing)
        startForegroundCompat(needsMic, "Starting...")

        if (sourceUri != null) {
            transcribeFile(sourceUri)
        } else {
            startLiveTranscription()
        }
    }

    /** Anything the user picked or downloaded, as a URI the decoder can open. */
    private fun toMediaUri(raw: String): android.net.Uri? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return null
        val parsed = android.net.Uri.parse(trimmed)
        // A bare filesystem path has no scheme: wrap it so ContentResolver
        // (and MediaExtractor) can still read it.
        val uri = if (parsed.scheme == null) {
            val file = File(trimmed)
            if (!file.exists()) return null
            android.net.Uri.fromFile(file)
        } else {
            parsed
        }
        return try {
            // Verify it is actually openable before committing to it.
            contentResolver.openFileDescriptor(uri, "r")?.use { }
            uri
        } catch (e: Exception) {
            Log.w(TAG, "Cannot open $uri: ${e.message}")
            null
        }
    }

    private fun hasMicPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    /**
     * Start as a foreground service declaring the right type. API 34+ rejects
     * (or kills) a microphone service that does not declare the microphone
     * type alongside the permission.
     */
    private fun startForegroundCompat(needsMic: Boolean, text: String) {
        val notification = buildNotification(text)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val type = if (needsMic) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK or
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            } else {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
            }
            startForeground(NOTIFICATION_ID, notification, type)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun fail(message: String) {
        Log.e(TAG, message)
        _state.value = TranscriptionState.Error(message)
        publishState(TranscriptionState.Error(message))
        stopSelf()
    }

    private fun transcribeFile(uri: android.net.Uri) {
        val context = this
        serviceScope.launch(Dispatchers.IO) {
            try {
                _state.value = TranscriptionState.Transcribing
                publishState(TranscriptionState.Transcribing)
                updateNotification("Transcribing file...")

                val cancelled = AtomicBoolean(false)
                var segmentIdx = 0
                var totalSamples = 0
                var fedSamples = 0

                AudioDecoder.decode(
                    context = context,
                    uri = uri,
                    // Whole-file transcription has no latency budget: give
                    // whisper 30 s of context per call, which is what it is
                    // trained for.
                    blockMs = FILE_BLOCK_MS,
                    onTotal = { totalSamples = it },
                    onChunk = { floatChunk ->
                        fedSamples += floatChunk.size
                        if (!cancelled.get()) {
                            try {
                                whisper?.transcribe(floatChunk)
                            } catch (e: Exception) {
                                // One bad block must not abandon the whole file.
                                Log.w(TAG, "Chunk failed: ${e.message}")
                            }
                            val nSegments = whisper?.getSegmentCount() ?: 0
                            for (i in segmentIdx until nSegments) {
                                whisper?.getSegment(i)?.let { segment ->
                                    _currentSegment.postValue(segment)
                                    publishSegment(segment)
                                    segmentIdx++
                                }
                            }
                        }
                        val overall = if (totalSamples > 0) {
                            (fedSamples.toFloat() / totalSamples).coerceIn(0f, 1f)
                        } else {
                            whisper?.getProgress() ?: 0f
                        }
                        _progress.postValue(overall)
                        publishProgress(overall)
                        updateNotification("Transcribing… ${(overall * 100).toInt()}%")
                    },
                    cancelled = cancelled
                )

                _state.value = TranscriptionState.Completed
                publishState(TranscriptionState.Completed)
                // Save SRT file
                saveSrtFile()
                stopSelf()
            } catch (e: Exception) {
                Log.e(TAG, "File transcription failed", e)
                _state.value = TranscriptionState.Error(e.message ?: "Transcription failed")
                publishState(TranscriptionState.Error(e.message ?: "Transcription failed"))
                stopSelf()
            }
        }
    }

    private fun startLiveTranscription() {
        val sampleRate = 16000
        val channelConfig = AudioFormat.CHANNEL_IN_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val bufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat) * 4

        val record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            sampleRate,
            channelConfig,
            audioFormat,
            bufferSize
        )
        // A failed AudioRecord is not recoverable, and `return@also` inside the
        // old `.also { }` only exited the lambda -- execution then continued and
        // called startRecording() on an uninitialised record.
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            fail("Microphone unavailable (AudioRecord init failed)")
            return
        }
        audioRecord = record

        record.startRecording()
        isRecording.set(true)

        serviceScope.launch(Dispatchers.IO) {
            val buffer = ShortArray(16000) // 1 second at 16kHz per AudioRecord read
            // Accumulate a few seconds before each whisper call: transcribing
            // isolated 1-second buffers produces fragments and hallucinated
            // text, so live mode trades a little latency for usable output.
            val window = FloatArray(MIC_WINDOW_MS * 16000 / 1000)
            var filled = 0
            var segmentIdx = 0

            while (isRecording.get()) {
                if (isPaused.get()) {
                    Thread.sleep(100)
                    continue
                }

                val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                if (read <= 0) continue

                for (i in 0 until read) {
                    if (filled >= window.size) break
                    window[filled++] = buffer[i].toFloat() / 32768.0f
                }

                if (filled < window.size) continue

                val block = window.copyOf(filled)
                filled = 0

                try {
                    whisper?.transcribe(block)
                } catch (e: Exception) {
                    Log.w(TAG, "Live chunk failed: ${e.message}")
                    continue
                }

                val nSegments = whisper?.getSegmentCount() ?: 0
                for (i in segmentIdx until nSegments) {
                    whisper?.getSegment(i)?.let { segment ->
                        _currentSegment.postValue(segment)
                        publishSegment(segment)
                        segmentIdx++
                        updateNotification("Live: ${segment.text.take(60)}")
                    }
                }
                // No progress bar for live audio: there is no known total, and
                // a fabricated fraction would be a lie.
            }

            // Flush whatever is still buffered when recording stops.
            if (filled > 0 && !isPaused.get()) {
                try {
                    whisper?.transcribe(window.copyOf(filled))
                    val nSegments = whisper?.getSegmentCount() ?: 0
                    for (i in segmentIdx until nSegments) {
                        whisper?.getSegment(i)?.let { publishSegment(it) }
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "Final chunk failed: ${e.message}")
                }
            }
        }
    }

    private fun togglePause() {
        val paused = !isPaused.getAndSet(!isPaused.get())
        val newState = if (paused) TranscriptionState.Paused else TranscriptionState.Transcribing
        _state.value = newState
        publishState(newState)
        updateNotification(if (paused) "Paused" else "Transcribing...")
    }

    private fun stopTranscription() {
        isRecording.set(false)
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
        whisper?.free()
        whisper = null
        _state.value = TranscriptionState.Stopped
        publishState(TranscriptionState.Stopped)
        // Save SRT file for live transcription
        saveSrtFile()
        publishState(TranscriptionState.Idle)
        stopForeground(true)
        stopSelf()
    }

    private fun updateNotification(text: String) {
        val notification = buildNotification(text)
        notificationManager.notify(NOTIFICATION_ID, notification)
    }

    private fun saveSrtFile() {
        val segments = sharedSegments.value
        if (segments.isEmpty()) return

        val timestamp = java.text.SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.US).format(java.util.Date())
        val baseName = "transcription_$timestamp"
        SrtWriter.writeSrt(this, segments, baseName)?.let { file ->
            Log.i(TAG, "Saved SRT to ${file.absolutePath}")
        }
    }

    private fun buildNotification(text: String): Notification {
        val intent = Intent(this, TranscriptionService::class.java).apply {
            action = ACTION_STOP
        }
        val stopAction = PendingIntent.getService(this, 0, intent, PendingIntent.FLAG_IMMUTABLE)

        val pauseIntent = Intent(this, TranscriptionService::class.java).apply {
            action = ACTION_PAUSE
        }
        val pauseAction = PendingIntent.getService(this, 1, pauseIntent, PendingIntent.FLAG_IMMUTABLE)

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("WhisperSubs Transcription")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_mic)
            .setOngoing(true)
            .addAction(R.drawable.ic_stop, "Stop", stopAction)
            .addAction(if (isPaused.get()) R.drawable.ic_play else R.drawable.ic_pause,
                if (isPaused.get()) "Resume" else "Pause", pauseAction)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Transcription Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Background transcription service"
                setShowBadge(false)
            }
            notificationManager.createNotificationChannel(channel)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopTranscription()
        serviceScope.cancel()
        super.onDestroy()
    }

    sealed class TranscriptionState {
        object Idle : TranscriptionState()
        object Transcribing : TranscriptionState()
        object Paused : TranscriptionState()
        object Completed : TranscriptionState()
        data class Error(val message: String) : TranscriptionState()
        object Stopped : TranscriptionState()
    }
}