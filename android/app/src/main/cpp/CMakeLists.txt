cmake_minimum_required(VERSION 3.22.1)
project("whisper_jni" LANGUAGES C CXX)

# whisper.cpp configuration
set(WHISPER_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/whisper.cpp)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Android NDK settings
if(ANDROID)
    set(CMAKE_ANDROID_NDK_TOOLCHAIN_VERSION "clang")
    set(ANDROID_STL "c++_shared")
endif()

# Include whisper.cpp
add_subdirectory(${WHISPER_ROOT} ${CMAKE_CURRENT_BINARY_DIR}/whisper.cpp)

# JNI wrapper library
add_library(whisper_jni SHARED
    whisper_jni.cpp
)

target_include_directories(whisper_jni PRIVATE
    ${WHISPER_ROOT}/include
    ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(whisper_jni PRIVATE
    whisper
    ${CMAKE_DL_LIBS}
    log
)

# Build whisper.cpp with minimal features for mobile
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_OPENBLAS OFF CACHE BOOL "" FORCE)
set(GGML_CUDA OFF CACHE BOOL "" FORCE)
set(GGML_METAL OFF CACHE BOOL "" FORCE)
set(GGML_VULKAN OFF CACHE BOOL "" FORCE)
set(GGML_CLBLAST OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)