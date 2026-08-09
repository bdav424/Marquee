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

    buildTypes {
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
