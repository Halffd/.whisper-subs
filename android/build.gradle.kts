buildscript {
    ext.kotlin_version = "2.0.20"
    ext.compose_compiler_version = "2.0.20"
    ext.activity_compose_version = "1.9.3"
    ext.lifecycle_version = "2.8.4"
    ext.media3_version = "1.6.0"
    ext.coil_version = "2.7.0"
    ext.ktor_version = "3.0.3"
    ext.hilt_version = "2.51.1"
    ext.material3_version = "1.3.1"
    ext.accompanist_version = "0.32.0"
    ext.camera_version = "1.4.0"
    ext.mlkit_version = "17.2.0"
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath("com.android.tools.build:gradle:8.7.2")
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.0.20")
        classpath("com.google.dagger:hilt-android-gradle-plugin:2.51.1")
    }
}
allprojects {
    repositories {
        google()
        mavenCentral()
    }
}
tasks.register("clean", Delete::class) {
    delete(rootProject.buildDir)
}