# Ktor
-keep class io.ktor.** { *; }
-keep class kotlinx.serialization.** { *; }
-keep class kotlinx.coroutines.** { *; }

# Coil
-keep class coil3.** { *; }

# Media3
-keep class androidx.media3.** { *; }

# ML Kit
-keep class com.google.mlkit.** { *; }

# Hilt
-keep class dagger.hilt.** { *; }

# OkHttp
-keep class okhttp3.** { *; }
-keep class okio.** { *; }

# Kotlinx
-keep class kotlinx.** { *; }

# App specific
-keep class com.halffd.whispersubs.** { *; }

# JNI classes
-keep class com.halffd.whispersubs.local.WhisperNative { *; }
-keep class com.halffd.whispersubs.local.TranscriptSegment { *; }
-keep class com.halffd.whispersubs.local.ModelManager$WhisperModel { *; }
-keep class com.halffd.whispersubs.local.TranscriptionService { *; }
-keep class com.halffd.whispersubs.local.LocalTranscriptionViewModel { *; }

# Native library
-keep class com.halffd.whispersubs.local.** { *; }