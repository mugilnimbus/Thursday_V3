import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// Release signing reads keystore.properties next to this project (git-ignored; see the README). Without that
// file a release build is left unsigned, so a signing key is never needed just to build or test.
val keystoreFile = rootProject.file("keystore.properties")
val keystore = Properties().apply { if (keystoreFile.exists()) keystoreFile.inputStream().use { load(it) } }

android {
    namespace = "app.thursday"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.thursday"
        minSdk = 30 // BiometricPrompt with the phone's lock-screen credential needs Android 11
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        // Lets a release build sit beside another build on one phone for a smoke test: -Pthursday.idSuffix=.smoke
        providers.gradleProperty("thursday.idSuffix").orNull?.let { applicationIdSuffix = it }
    }

    signingConfigs {
        if (keystoreFile.exists()) {
            create("release") {
                storeFile = rootProject.file(keystore.getProperty("storeFile"))
                storePassword = keystore.getProperty("storePassword")
                keyAlias = keystore.getProperty("keyAlias")
                keyPassword = keystore.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            // Debug builds may also pair with http://127.0.0.1:8701 through `adb reverse` (see README).
            buildConfigField("boolean", "ALLOW_LOCAL_HTTP", "true")
        }
        release {
            signingConfig = signingConfigs.findByName("release")
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            buildConfigField("boolean", "ALLOW_LOCAL_HTTP", "false")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
}

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

dependencies {
    implementation(libs.core.ktx)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.process)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.coroutines.android)
    implementation(libs.okhttp)
    implementation(libs.biometric)
    implementation(libs.camera.camera2)
    implementation(libs.camera.lifecycle)
    implementation(libs.camera.view)
    implementation(libs.mlkit.barcode)
    debugImplementation(libs.compose.ui.tooling)
    testImplementation(libs.junit)
}
