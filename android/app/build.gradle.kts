plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.dagger.hilt.android") version "2.51.1"
    id("kotlin-android")
    id("kotlin-kapt")
}
android {
    namespace = "com.halffd.whispersubs"
    compileSdk = 34
    defaultConfig {
        applicationId = "com.halffd.whispersubs"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
        debug {
            isDebuggable = true
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
        freeCompilerArgs = listOf("-Xopt-in=kotlinx.coroutines.ExperimentalCoroutinesApi", "-Xopt-in=kotlinx.serialization.ExperimentalSerializationApi")
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "2.0.20"
    }
    packagingOptions {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1,DEPENDENCIES,LICENSE,NOTICE}"
        }
    }
    buildFeatures {
        compose = true
        viewBinding = false
    }
}
dependencies {
    // Core Android
    val core_ktx_version = "1.15.0"
    val activity_compose_version = "1.9.3"
    val lifecycle_version = "2.8.4"
    val navigation_version = "2.8.4"
    val room_version = "2.6.1"
    val hilt_version = "2.51.1"
    val work_version = "2.9.0"
    
    // Material3
    val material3_version = "1.3.1"
    
    // Media3 (ExoPlayer successor)
    val media3_version = "1.6.0"
    
    // Coil for images
    val coil_version = "2.7.0"
    
    // Ktor client
    val ktor_version = "3.0.3"
    
    // CameraX
    val camera_version = "1.4.0"
    
    // ML Kit Barcode Scanning
    val mlkit_version = "17.2.0"
    
    // Serialization
    val serialization_version = "1.6.3"
    
    // Coroutines
    val coroutines_version = "1.8.1"
    
    // Core
    implementation("androidx.core:core-ktx:$core_ktx_version")
    implementation("androidx.activity:activity-compose:$activity_compose_version")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:$lifecycle_version")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:$lifecycle_version")
    implementation("androidx.lifecycle:lifecycle-livedata-ktx:$lifecycle_version")
    implementation("androidx.navigation:navigation-compose:$navigation_version")
    
    // Hilt DI
    implementation("com.google.dagger:hilt-android:$hilt_version")
    kapt("com.google.dagger:hilt-compiler:$hilt_version")
    
    // Material3
    implementation("androidx.compose.material3:material3:$material3_version")
    implementation("androidx.compose.material3:material3-window-size-class:$material3_version")
    // Material Icons
    implementation("androidx.compose.material:material-icons-extended")
    
    // Compose
    implementation(platform("androidx.compose:compose-bom:2024.08.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.runtime:runtime-livedata")
    implementation("androidx.compose.runtime:runtime-rxjava2")
    
    // Media3 (ExoPlayer)
    implementation("androidx.media3:media3-exoplayer:$media3_version")
    implementation("androidx.media3:media3-ui:$media3_version")
    implementation("androidx.media3:media3-datasource-rtmp:$media3_version")
    implementation("androidx.media3:media3-session:$media3_version")
    implementation("androidx.media3:media3-subtitle:$media3_version") // For SRT sidecar
    
    // Coil for thumbnails
    implementation("io.coil-kt:coil-compose:$coil_version")
    
    // Ktor HTTP Client
    implementation("io.ktor:ktor-client-android:$ktor_version")
    implementation("io.ktor:ktor-client-cio:$ktor_version")
    implementation("io.ktor:ktor-client-content-negotiation:$ktor_version")
    implementation("io.ktor:ktor-serialization-kotlinx-json:$ktor_version")
    implementation("io.ktor:ktor-client-logging:$ktor_version")
    
    // CameraX
    implementation("androidx.camera:camera-core:$camera_version")
    implementation("androidx.camera:camera-camera2:$camera_version")
    implementation("androidx.camera:camera-lifecycle:$camera_version")
    implementation("androidx.camera:camera-view:$camera_version")
    implementation("androidx.camera:camera-video:$camera_version")
    implementation("androidx.camera:camera-extensions:$camera_version")
    implementation("androidx.camera:camera-mlkit-vision:$camera_version")
    
    // ML Kit Barcode Scanning (QR code)
    implementation("com.google.mlkit:barcode-scanning:$mlkit_version")
    
    // Kotlinx Serialization
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:$serialization_version")
    
    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:$coroutines_version")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:$coroutines_version")
    
    // Okio
    implementation("com.squareup.okio:okio:3.9.1")
    
    // Testing
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
kapt {
    correctErrorTypes = true
}
tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
    kotlinOptions {
        freeCompilerArgs = listOf("-Xopt-in=kotlinx.coroutines.ExperimentalCoroutinesApi", "-Xopt-in=kotlinx.serialization.ExperimentalSerializationApi")
    }
}