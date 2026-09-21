package com.halffd.whispersubs.local

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
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

        // Static state mirror so UI can observe the service without binding
        private val _sharedState = MutableStateFlow<TranscriptionState>(TranscriptionState.Idle)
        val sharedState: StateFlow<TranscriptionState> = _sharedState

        private val _sharedSegments = MutableStateFlow<List<TranscriptSegment>>(emptyList())
        val sharedSegments: StateFlow<List<TranscriptSegment>> = _sharedSegments

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
            _state.value = TranscriptionState.Error("Model not found: $modelId")
            publishState(TranscriptionState.Error("Model not found: $modelId"))
            stopSelf()
            return
        }

        whisper = WhisperNative.init(modelPath, threads, translate, language)
            ?: run {
                _state.value = TranscriptionState.Error("Failed to initialize Whisper")
                publishState(TranscriptionState.Error("Failed to initialize Whisper"))
                stopSelf()
                return@startTranscription
            }

        _state.value = TranscriptionState.Transcribing
        publishState(TranscriptionState.Transcribing)
        startForeground(NOTIFICATION_ID, buildNotification("Starting..."))

        if (sourcePath != null && File(sourcePath).exists()) {
            // File transcription
            transcribeFile(android.net.Uri.parse(sourcePath))
        } else {
            // Live microphone transcription
            startLiveTranscription()
        }
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

                AudioDecoder.decode(
                    context = context,
                    uri = uri,
                    onChunk = { floatChunk ->
                        if (isRecording.get()) return@decode // shouldn't happen in file mode

                        val result = whisper?.transcribe(floatChunk)
                        if (result == 0) {
                            val nSegments = whisper?.getSegmentCount() ?: 0
                            for (i in segmentIdx until nSegments) {
                                whisper?.getSegment(i)?.let { segment ->
                                    _currentSegment.postValue(segment)
                                    _progress.postValue(whisper?.getProgress() ?: 0f)
                                    publishSegment(segment)
                                    segmentIdx++
                                }
                            }
                        }
                    },
                    cancelled = AtomicBoolean()
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

        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            sampleRate,
            channelConfig,
            audioFormat,
            bufferSize
        ).also {
            if (it.state != AudioRecord.STATE_INITIALIZED) {
                _state.value = TranscriptionState.Error("AudioRecord init failed")
                publishState(TranscriptionState.Error("AudioRecord init failed"))
                stopSelf()
                return@also
            }
        }

        audioRecord?.startRecording()
        isRecording.set(true)

        serviceScope.launch(Dispatchers.IO) {
            val buffer = ShortArray(16000) // 1 second at 16kHz
            while (isRecording.get()) {
                if (isPaused.get()) {
                    Thread.sleep(100)
                    continue
                }

                val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                if (read > 0) {
                    // Convert to float32 [-1, 1]
                    val floatBuffer = buffer.take(read).map { it.toFloat() / 32768.0f }.toFloatArray()

                    // Transcribe chunk
                    val result = whisper?.transcribe(floatBuffer)
                    if (result == 0) {
                        val nSegments = whisper?.getSegmentCount() ?: 0
                        if (nSegments > 0) {
                            val lastSegment = whisper?.getSegment(nSegments - 1)
                            lastSegment?.let {
                                _currentSegment.postValue(it)
                                _progress.postValue(whisper?.getProgress() ?: 0f)
                                publishSegment(it)
                            }
                        }
                    }
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