// JNI bridge between WhisperNative.kt and the vendored whisper.cpp.
//
// Two things this file has to get exactly right, both of which were wrong
// before and made every on-device transcription impossible:
//
//  1. Linkage. Every native method must be `extern "C" JNIEXPORT`, and its
//     name must match what the Kotlin compiler emits. `nativeInit` lives in
//     WhisperNative's companion object, so its JVM owner is
//     `WhisperNative$Companion` -> the JNI name carries `_00024Companion`.
//     The rest are instance methods of WhisperNative. As a second safety net
//     JNI_OnLoad registers them by signature, which is immune to both name
//     mangling and a later `@JvmStatic` being added on the Kotlin side.
//
//  2. Segment accumulation. `whisper_full()` resets its own state on every
//     call, so feeding audio in chunks would otherwise lose all earlier text.
//     Segments are therefore copied into the context after each call, with a
//     running time offset, and `nativeGetSegmentCount` returns the cumulative
//     count -- which is what the Kotlin caller loops over.
//
// Timestamps from whisper.cpp are in CENTISECONDS (`whisper_full_get_segment_t0`
// is documented by `100 * samples / WHISPER_SAMPLE_RATE` in whisper.cpp), while
// the Kotlin side and the SRT writer work in milliseconds.

#include <jni.h>
#include <android/log.h>

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include "whisper.h"

#define LOG_TAG "WhisperJNI"
#define LOGD(...) __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)

// JNINativeMethod takes char*; JNI never writes through them.
#define JNI_STR(literal) const_cast<char *>(literal)

namespace {

constexpr int kSampleRate = 16000;      // whisper.cpp only accepts 16 kHz
constexpr int64_t kCsToMs = 10;         // centiseconds -> milliseconds

struct Segment {
    std::string text;
    int64_t startMs = 0;
    int64_t endMs = 0;
};

struct WhisperContext {
    whisper_context * ctx = nullptr;
    whisper_full_params params{};
    std::string language;
    int n_threads = 4;
    bool translate = false;

    // Progress of the in-flight whisper_full() call, 0.0 .. 1.0.
    std::atomic<float> progress{0.0f};

    // Everything transcribed so far, across every transcribe() call.
    std::vector<Segment> segments;
    // Audio already handed to whisper_full(), in ms: the time offset for the
    // next call's segments.
    int64_t fedMs = 0;

    std::mutex lock;
};

void whisperProgressCallback(whisper_context * /*ctx*/,
                             whisper_state * /*state*/,
                             int progress,
                             void * userData) {
    auto * wrapper = static_cast<WhisperContext *>(userData);
    if (wrapper != nullptr) {
        wrapper->progress.store(static_cast<float>(progress) / 100.0f);
    }
}

/** True for cues that carry no speech (blank or bracketed annotations). */
bool isNoise(const std::string & text) {
    size_t first = text.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return true;  // whitespace only
    }
    size_t last = text.find_last_not_of(" \t\r\n");
    std::string trimmed = text.substr(first, last - first + 1);
    if (trimmed.size() < 2) {
        return false;  // a single character can be legitimate
    }
    // "[BLANK_AUDIO]", "(music)", "[ Silence ]" style annotations.
    char open = trimmed.front();
    char close = trimmed.back();
    return (open == '[' && close == ']') || (open == '(' && close == ')');
}

jobject buildSegment(JNIEnv * env, const Segment & segment) {
    jclass cls = env->FindClass("com/halffd/whispersubs/local/TranscriptSegment");
    if (cls == nullptr) {
        return nullptr;
    }
    jmethodID ctor = env->GetMethodID(cls, "<init>", "(Ljava/lang/String;JJ)V");
    if (ctor == nullptr) {
        env->DeleteLocalRef(cls);
        return nullptr;
    }
    jstring text = env->NewStringUTF(segment.text.c_str());
    jobject result = env->NewObject(cls, ctor, text,
                                    static_cast<jlong>(segment.startMs),
                                    static_cast<jlong>(segment.endMs));
    env->DeleteLocalRef(text);
    env->DeleteLocalRef(cls);
    return result;
}

}  // namespace

// ---------------------------------------------------------------------------
// Native methods. Names must match the Kotlin declarations exactly.
// ---------------------------------------------------------------------------

extern "C" JNIEXPORT jlong JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_00024Companion_nativeInit(
        JNIEnv * env, jobject /* thiz: the Companion instance */,
        jstring modelPath, jint nThreads, jboolean translate, jstring language) {
    if (modelPath == nullptr) {
        LOGE("nativeInit: model path is null");
        return 0;
    }

    const char * model_path = env->GetStringUTFChars(modelPath, nullptr);
    const char * lang = (language != nullptr)
                            ? env->GetStringUTFChars(language, nullptr)
                            : nullptr;

    auto * wrapper = new WhisperContext();
    wrapper->n_threads = nThreads > 0 ? nThreads : 4;
    wrapper->translate = translate == JNI_TRUE;
    if (lang != nullptr) {
        wrapper->language = lang;
    }

    whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = false;      // no GPU backend is linked in
    cparams.flash_attn = false;

    wrapper->ctx = whisper_init_from_file_with_params(model_path, cparams);

    if (wrapper->ctx == nullptr) {
        LOGE("Failed to load model: %s", model_path);
        delete wrapper;
        env->ReleaseStringUTFChars(modelPath, model_path);
        if (lang != nullptr) {
            env->ReleaseStringUTFChars(language, lang);
        }
        return 0;
    }

    wrapper->params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    wrapper->params.n_threads = wrapper->n_threads;
    wrapper->params.translate = wrapper->translate;
    wrapper->params.language =
        wrapper->language.empty() ? nullptr : wrapper->language.c_str();
    // Chunked feeding: each call must stand alone, not inherit the previous
    // chunk's text as a decoder prompt.
    wrapper->params.no_context = true;
    wrapper->params.single_segment = false;
    wrapper->params.suppress_blank = true;
    wrapper->params.suppress_nst = true;
    wrapper->params.temperature = 0.0f;
    // Our own progress reporting, and nothing on stdout.
    wrapper->params.print_progress = false;
    wrapper->params.print_realtime = false;
    wrapper->params.print_timestamps = false;
    wrapper->params.print_special = false;
    wrapper->params.progress_callback = whisperProgressCallback;
    wrapper->params.progress_callback_user_data = wrapper;

    LOGI("Model loaded: %s (threads=%d, translate=%d, lang=%s)",
         model_path, wrapper->n_threads, wrapper->translate ? 1 : 0,
         wrapper->language.empty() ? "auto" : wrapper->language.c_str());

    env->ReleaseStringUTFChars(modelPath, model_path);
    if (lang != nullptr) {
        env->ReleaseStringUTFChars(language, lang);
    }
    return reinterpret_cast<jlong>(wrapper);
}

extern "C" JNIEXPORT void JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_free(
        JNIEnv * /*env*/, jobject /* thiz */, jlong handle) {
    auto * wrapper = reinterpret_cast<WhisperContext *>(handle);
    if (wrapper == nullptr) {
        return;
    }
    if (wrapper->ctx != nullptr) {
        whisper_free(wrapper->ctx);
    }
    delete wrapper;
}

extern "C" JNIEXPORT jint JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_nativeTranscribe(
        JNIEnv * env, jobject /* thiz */, jlong handle,
        jfloatArray audioData, jint audioLength, jint sampleRate) {
    auto * wrapper = reinterpret_cast<WhisperContext *>(handle);
    if (wrapper == nullptr || wrapper->ctx == nullptr || audioData == nullptr) {
        return -1;
    }
    if (sampleRate != kSampleRate) {
        LOGE("Sample rate must be %d Hz, got %d", kSampleRate, sampleRate);
        return -2;
    }
    if (audioLength <= 0) {
        return 0;
    }

    jfloat * audio = env->GetFloatArrayElements(audioData, nullptr);
    if (audio == nullptr) {
        return -1;
    }

    wrapper->progress.store(0.0f);
    // Serialise: the Kotlin side drives one transcription at a time, but a
    // stray second caller (e.g. stop() racing a chunk) must not corrupt state.
    std::lock_guard<std::mutex> guard(wrapper->lock);

    const int64_t chunkStartMs = wrapper->fedMs;

    int rc = whisper_full(wrapper->ctx, wrapper->params, audio, audioLength);
    env->ReleaseFloatArrayElements(audioData, audio, JNI_ABORT);

    if (rc != 0) {
        LOGE("whisper_full failed: %d", rc);
        return rc;
    }

    const int n = whisper_full_n_segments(wrapper->ctx);
    int added = 0;
    for (int i = 0; i < n; i++) {
        const char * text = whisper_full_get_segment_text(wrapper->ctx, i);
        if (text == nullptr) {
            continue;
        }
        std::string body(text);
        if (isNoise(body)) {
            continue;
        }
        // t0/t1 are centiseconds relative to the start of *this* call.
        const int64_t t0 = whisper_full_get_segment_t0(wrapper->ctx, i);
        const int64_t t1 = whisper_full_get_segment_t1(wrapper->ctx, i);

        Segment segment;
        segment.text = body;
        segment.startMs = chunkStartMs + t0 * kCsToMs;
        segment.endMs = chunkStartMs + t1 * kCsToMs;
        wrapper->segments.push_back(segment);
        added++;
    }

    wrapper->fedMs += (static_cast<int64_t>(audioLength) * 1000) / kSampleRate;
    wrapper->progress.store(1.0f);

    LOGD("chunk %lldms -> %d segment(s), total %zu",
         static_cast<long long>(chunkStartMs), added, wrapper->segments.size());
    return 0;
}

extern "C" JNIEXPORT jint JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_nativeGetSegmentCount(
        JNIEnv * /*env*/, jobject /* thiz */, jlong handle) {
    auto * wrapper = reinterpret_cast<WhisperContext *>(handle);
    if (wrapper == nullptr) {
        return 0;
    }
    std::lock_guard<std::mutex> guard(wrapper->lock);
    return static_cast<jint>(wrapper->segments.size());
}

extern "C" JNIEXPORT jobject JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_nativeGetSegment(
        JNIEnv * env, jobject /* thiz */, jlong handle, jint index) {
    auto * wrapper = reinterpret_cast<WhisperContext *>(handle);
    if (wrapper == nullptr) {
        return nullptr;
    }
    std::lock_guard<std::mutex> guard(wrapper->lock);
    if (index < 0 || static_cast<size_t>(index) >= wrapper->segments.size()) {
        return nullptr;
    }
    return buildSegment(env, wrapper->segments[static_cast<size_t>(index)]);
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_nativeGetLanguage(
        JNIEnv * env, jobject /* thiz */, jlong handle) {
    auto * wrapper = reinterpret_cast<WhisperContext *>(handle);
    if (wrapper == nullptr) {
        return env->NewStringUTF("auto");
    }
    if (wrapper->language.empty()) {
        // Language detection happened inside whisper_full; report what it chose.
        const int id = wrapper->ctx != nullptr ? whisper_full_lang_id(wrapper->ctx) : -1;
        if (id >= 0) {
            const char * code = whisper_lang_str(id);
            if (code != nullptr) {
                return env->NewStringUTF(code);
            }
        }
        return env->NewStringUTF("auto");
    }
    return env->NewStringUTF(wrapper->language.c_str());
}

extern "C" JNIEXPORT jfloat JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_nativeGetProgress(
        JNIEnv * /*env*/, jobject /* thiz */, jlong handle) {
    auto * wrapper = reinterpret_cast<WhisperContext *>(handle);
    if (wrapper == nullptr) {
        return 0.0f;
    }
    return wrapper->progress.load();
}

// ---------------------------------------------------------------------------
// Explicit registration: immune to Kotlin name mangling.
// ---------------------------------------------------------------------------

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM * vm, void * /*reserved*/) {
    JNIEnv * env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void **>(&env), JNI_VERSION_1_6) != JNI_OK) {
        return JNI_ERR;
    }

    static const JNINativeMethod kCompanionMethods[] = {
        {JNI_STR("nativeInit"), JNI_STR("(Ljava/lang/String;IZLjava/lang/String;)J"),
         reinterpret_cast<void *>(
             Java_com_halffd_whispersubs_local_WhisperNative_00024Companion_nativeInit)},
    };
    static const JNINativeMethod kInstanceMethods[] = {
        {JNI_STR("free"), JNI_STR("()V"),
         reinterpret_cast<void *>(Java_com_halffd_whispersubs_local_WhisperNative_free)},
        {JNI_STR("nativeTranscribe"), JNI_STR("(J[FII)I"),
         reinterpret_cast<void *>(Java_com_halffd_whispersubs_local_WhisperNative_nativeTranscribe)},
        {JNI_STR("nativeGetSegmentCount"), JNI_STR("(J)I"),
         reinterpret_cast<void *>(Java_com_halffd_whispersubs_local_WhisperNative_nativeGetSegmentCount)},
        {JNI_STR("nativeGetSegment"), JNI_STR("(JI)Lcom/halffd/whispersubs/local/TranscriptSegment;"),
         reinterpret_cast<void *>(Java_com_halffd_whispersubs_local_WhisperNative_nativeGetSegment)},
        {JNI_STR("nativeGetLanguage"), JNI_STR("(J)Ljava/lang/String;"),
         reinterpret_cast<void *>(Java_com_halffd_whispersubs_local_WhisperNative_nativeGetLanguage)},
        {JNI_STR("nativeGetProgress"), JNI_STR("(J)F"),
         reinterpret_cast<void *>(Java_com_halffd_whispersubs_local_WhisperNative_nativeGetProgress)},
    };

    jclass companion = env->FindClass(
        "com/halffd/whispersubs/local/WhisperNative$Companion");
    if (companion != nullptr) {
        if (env->RegisterNatives(companion, kCompanionMethods, 1) != JNI_OK) {
            LOGE("RegisterNatives failed for WhisperNative$Companion");
        }
        env->DeleteLocalRef(companion);
    } else {
        LOGE("WhisperNative$Companion not found; relying on name lookup");
        env->ExceptionClear();
    }

    jclass clazz = env->FindClass("com/halffd/whispersubs/local/WhisperNative");
    if (clazz != nullptr) {
        const int count = static_cast<int>(
            sizeof(kInstanceMethods) / sizeof(kInstanceMethods[0]));
        if (env->RegisterNatives(clazz, kInstanceMethods, count) != JNI_OK) {
            LOGE("RegisterNatives failed for WhisperNative");
        }
        env->DeleteLocalRef(clazz);
    } else {
        LOGE("WhisperNative not found; relying on name lookup");
        env->ExceptionClear();
    }

    return JNI_VERSION_1_6;
}
