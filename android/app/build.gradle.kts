plugins {
    id("com.android.application") version "8.5.2"
    id("org.jetbrains.kotlin.android") version "1.9.24"
}

android {
    namespace = "com.winchester.marquee"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.winchester.marquee"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    /* A checked-in debug key, so every CI build signs identically.
     *
     * Gradle generates ~/.android/debug.keystore on first use, and a CI runner
     * is a fresh machine every time — so each build was signed with a
     * different key and Android refused to install the new APK over the old
     * one with a signature mismatch. Updating meant uninstalling first and
     * placing the widget again.
     *
     * This is the standard debug key with the standard published password. It
     * is not a secret and it cannot sign anything for the Play Store; its only
     * job is to stay the same from one build to the next. */
    signingConfigs {
        getByName("debug") {
            storeFile = rootProject.file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        debug { signingConfig = signingConfigs.getByName("debug") }
        release { isMinifyEnabled = false }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

// No dependencies on purpose. The widget reads one JSON file with
// org.json from the platform and draws it with RemoteViews, so there is
// nothing here to keep patched.
dependencies { }
