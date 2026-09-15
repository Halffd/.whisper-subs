#include <jni.h>
#include <string>
#include <vector>
#include <memory>
#include <android/log.h>
#include "whisper.h"

#define LOG_TAG "WhisperJNI"
#define LOGD(...) __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

struct WhisperContext {
    whisper_context* ctx = nullptr;
    whisper_full_params params;
    std::vector<whisper_token> tokens;
    std::string language;
    int n_threads = 4;
    bool translate = false;
    int offset_ms = 0;
    int duration_ms = 0;
};

static jlong JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_init(JNIEnv* env, jclass clazz,
                                                     jstring modelPath,
                                                     jint nThreads,
                                                     jboolean translate,
                                                     jstring language) {
    const char* model_path = env->GetStringUTFChars(modelPath, nullptr);
    const char* lang = language ? env->GetStringUTFChars(language, nullptr) : "auto";

    auto* wrapper = new WhisperContext();
    wrapper->n_threads = nThreads;
    wrapper->translate = translate;
    if (language) wrapper->language = lang;

    struct whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = false;
    wrapper->ctx = whisper_init_from_file_with_params(model_path, cparams);

    if (!wrapper->ctx) {
        LOGE("Failed to load model: %s", model_path);
        delete wrapper;
        env->ReleaseStringUTFChars(modelPath, model_path);
        if (language) env->ReleaseStringUTFChars(language, lang);
        return 0;
    }

    wrapper->params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    wrapper->params.n_threads = nThreads;
    wrapper->params.translate = translate;
    wrapper->params.language = wrapper->language.empty() ? nullptr : wrapper->language.c_str();
    wrapper->params.print_progress = true;
    wrapper->params.print_realtime = false;
    wrapper->params.print_timestamps = true;
    wrapper->params.single_segment = false;
    wrapper->params.max_tokens = 0;
    wrapper->params.suppress_blank = true;
    wrapper->params.suppress_non_speech_tokens = true;
    wrapper->params.temperature = 0.0f;
    wrapper->params.max_initial_ts = 1.0f;
    wrapper->params.length_penalty = -1.0f;

    LOGD("Whisper model loaded: %s, threads: %d", model_path, nThreads);
    env->ReleaseStringUTFChars(modelPath, model_path);
    if (language) env->ReleaseStringUTFChars(language, lang);
    return reinterpret_cast<jlong>(wrapper);
}

static void JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_free(JNIEnv* env, jclass clazz, jlong handle) {
    auto* wrapper = reinterpret_cast<WhisperContext*>(handle);
    if (wrapper) {
        if (wrapper->ctx) {
            whisper_free(wrapper->ctx);
        }
        delete wrapper;
    }
}

static jint JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_transcribe(JNIEnv* env, jclass clazz,
                                                           jlong handle,
                                                           jfloatArray audioData,
                                                           jint audioLength,
                                                           jint sampleRate) {
    auto* wrapper = reinterpret_cast<WhisperContext*>(handle);
    if (!wrapper || !wrapper->ctx) return -1;

    jfloat* audio = env->GetFloatArrayElements(audioData, nullptr);
    if (!audio) return -1;

    // whisper.cpp expects 16kHz mono float32
    if (sampleRate != 16000) {
        LOGE("Sample rate must be 16kHz, got %d", sampleRate);
        env->ReleaseFloatArrayElements(audioData, audio, JNI_ABORT);
        return -2;
    }

    int ret = whisper_full(wrapper->ctx, wrapper->params, audio, audioLength);
    env->ReleaseFloatArrayElements(audioData, audio, JNI_ABORT);

    if (ret != 0) {
        LOGE("whisper_full failed: %d", ret);
        return ret;
    }

    return 0;
}

static jint JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_getSegmentCount(JNIEnv* env, jclass clazz, jlong handle) {
    auto* wrapper = reinterpret_cast<WhisperContext*>(handle);
    if (!wrapper || !wrapper->ctx) return 0;
    return whisper_full_n_segments(wrapper->ctx);
}

static jobject JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_getSegment(JNIEnv* env, jclass clazz,
                                                           jlong handle, jint index) {
    auto* wrapper = reinterpret_cast<WhisperContext*>(handle);
    if (!wrapper || !wrapper->ctx) return nullptr;

    int n_segments = whisper_full_n_segments(wrapper->ctx);
    if (index < 0 || index >= n_segments) return nullptr;

    const char* text = whisper_full_get_segment_text(wrapper->ctx, index);
    int64_t t0 = whisper_full_get_segment_t0(wrapper->ctx, index);
    int64_t t1 = whisper_full_get_segment_t1(wrapper->ctx, index);

    jclass segmentClass = env->FindClass("com/halffd/whispersubs/local/TranscriptSegment");
    if (!segmentClass) return nullptr;

    jmethodID constructor = env->GetMethodID(segmentClass, "<init>", "(Ljava/lang/String;JJ)V");
    if (!constructor) return nullptr;

    jstring jtext = env->NewStringUTF(text);
    jobject segment = env->NewObject(segmentClass, constructor, jtext, t0, t1);
    env->DeleteLocalRef(jtext);
    return segment;
}

static jstring JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_getLanguage(JNIEnv* env, jclass clazz, jlong handle) {
    auto* wrapper = reinterpret_cast<WhisperContext*>(handle);
    if (!wrapper || !wrapper->ctx) return nullptr;

    // Get detected language from the first segment
    int n_segments = whisper_full_n_segments(wrapper->ctx);
    if (n_segments > 0) {
        // Language detection happens in whisper_full, we can query it
        // For now return the language we set or "auto"
        return env->NewStringUTF(wrapper->language.empty() ? "auto" : wrapper->language.c_str());
    }
    return env->NewStringUTF(wrapper->language.empty() ? "auto" : wrapper->language.c_str());
}

static jfloat JNICALL
Java_com_halffd_whispersubs_local_WhisperNative_getProgress(JNIEnv* env, jclass clazz, jlong handle) {
    // whisper.cpp doesn't expose progress directly during transcription
    // Could be enhanced with a progress callback
    return 0.0f;
}

extern "C" JNIEXPORT jint JNICALL
JNI_OnLoad(JavaVM* vm, void* reserved) {
    JNIEnv* env;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) {
        return JNI_ERR;
    }
    return JNI_VERSION_1_6;
}