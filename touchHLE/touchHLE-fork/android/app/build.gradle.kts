/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 *
 * Parts of this file are derived from SDL 2's Android project template, which
 * has a different license. Please see vendor/SDL/LICENSE.txt for details.
 */
import org.gradle.nativeplatform.platform.internal.DefaultNativePlatform
import groovy.json.JsonSlurper
import java.security.KeyStore
import java.security.MessageDigest

plugins {
    id("com.android.application") version("8.10.1")
    id("com.github.willir.rust.cargo-ndk-android") version("0.3.4")
    id("org.jetbrains.kotlin.android") version("2.0.21")
}

fun getTouchHLEBranding(): String {
    val output = providers.exec {
        commandLine("cargo", "run", "--package", "touchHLE_version", "--", "--branding")
    }.standardOutput.asText.get().trim()

    return output
}

fun join(prefix: String, separator: String, branding: String): String {
    return if (branding.isEmpty()) prefix else prefix + separator + branding
}

fun env(name: String): String? {
    return System.getenv(name)?.takeIf { it.isNotBlank() }
}

val repositoryRoot = rootDir.parentFile.parentFile.parentFile
val releaseInfo = JsonSlurper().parse(repositoryRoot.resolve("release.json"), "UTF-8") as Map<*, *>
val ipaInfo = releaseInfo["ipa"] as Map<*, *>
val androidInfo = releaseInfo["android"] as Map<*, *>
val bundledZombieFarmIpa = repositoryRoot.resolve("zombie_farm_ipa").resolve(ipaInfo["name"] as String)
val bundledIpaHash = ipaInfo["sha256"] as String
val installedIpaName = androidInfo["installedIpaName"] as String
val generatedZombieFarmAssets = layout.buildDirectory.dir("generated/zombieFarmAssets")
val bundleZombieFarmIpa = tasks.register("bundleZombieFarmIpa") {
    val expectedSize = (ipaInfo["size"] as Number).toLong()
    inputs.file(bundledZombieFarmIpa)
    inputs.property("ipaSha256", bundledIpaHash)
    inputs.property("ipaSize", expectedSize)
    inputs.property("installedIpaName", installedIpaName)
    outputs.dir(generatedZombieFarmAssets)
    doLast {
        val ipa = bundledZombieFarmIpa.readBytes()
        val digest = MessageDigest.getInstance("SHA-256").digest(ipa)
            .joinToString("") { "%02x".format(it) }
        check(ipa.size.toLong() == expectedSize && digest == bundledIpaHash) {
            "Bundled IPA differs from release.json: ${bundledZombieFarmIpa.name}, SHA-256 $digest"
        }
        val dest = generatedZombieFarmAssets.get().asFile
        dest.mkdirs()
        // A renamed built-in must not leave another playable IPA in the merged APK assets.
        dest.listFiles { file -> file.isFile && file.extension.equals("ipa", true) && file.name != installedIpaName }
            ?.forEach { check(it.delete()) { "Could not remove stale generated asset: ${it.name}" } }
        dest.resolve(installedIpaName).writeBytes(ipa)
        dest.resolve("touchHLE_zombiefarm_ipa.sha256").writeText(digest)
    }
}

val testSigning = providers.gradleProperty("zfTestSigning").orNull == "true"

android {
    val branding = getTouchHLEBranding()
    val testAppName = join("僵尸农场·测试版", " ", branding)
    ndkVersion = "27.2.12479018"
    compileSdk = 36
    buildFeatures {
        buildConfig = true
    }
    defaultConfig {
        applicationId = "org.touchhle.zombiefarm"
        // 5: free/open-source statement (first-run dialog + permanent footer)
        // and the signing-certificate self-check.
        // 6: title-screen watermark + window title.
        // 7: the statement now appears on every launch, plus the QQ group.
        // 8: launching any IPA is allowed again; only the bundled one is watched.
        // 12: empty Cocos text textures keep zero layout with transparent backing.
        versionCode = (androidInfo["versionCode"] as Number).toInt()
        if (!branding.isEmpty()) {
            applicationIdSuffix = branding.lowercase()
        }
        resValue("string", "app_name", join("Zombie Farm 游戏管理", " ", branding))
        manifestPlaceholders["icon"] = "@drawable/zombie_farm_icon"
        buildConfigField("int", "APP_ICON", "org.touchhle.android.R.drawable.zombie_farm_icon")
        versionName = join(releaseInfo["tag"] as String, " ", branding)
        buildConfigField("String", "BUNDLED_IPA_NAME", "\"$installedIpaName\"")
        buildConfigField("String", "BUNDLED_IPA_SHA256", "\"$bundledIpaHash\"")

        minSdk = 21 // first version with AArch64
        targetSdk = 31
        testInstrumentationRunner = "org.touchhle.android.ManagerTestRunner"
        externalNativeBuild {
            ndkBuild {
                arguments("APP_PLATFORM=android-21")
                // abiFilters 'armeabi-v7a', 'arm64-v8a', 'x86', 'x86_64'
                // Only 'arm64-v8a' and 'x86_64' are supported by dynarmic
                // and hence touchHLE. The 'x86_64' build works, but the main
                // use for that would be the emulator in Android Studio, and
                // its OpenGL ES implementations don't seem to work properly
                // with touchHLE, so we disable it to reduce build time and
                // avoid shipping stuff we haven't meaningfully tested.
                // Make sure this matches the cargoNdk targets below.
                abiFilters("arm64-v8a")
            }
        }
    }
    // The target JVM version must be the same for Java and Kotlin.
    compileOptions {
        sourceCompatibility(JavaVersion.VERSION_11)
        targetCompatibility(JavaVersion.VERSION_11)
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    signingConfigs {
        getByName("debug") {
            val projectTestStore = File(System.getProperty("user.home"), ".android/zombie-farm-test.keystore")
            val customStore = env("ZF_TEST_KEYSTORE_PATH")?.let { file(it) }
            if (customStore != null || projectTestStore.isFile) storeFile = customStore ?: projectTestStore
            env("ZF_TEST_KEYSTORE_PASSWORD")?.let { storePassword = it }
            env("ZF_TEST_KEY_ALIAS")?.let { keyAlias = it }
            env("ZF_TEST_KEY_PASSWORD")?.let { keyPassword = it }
        }
        create("release") {
            storeFile = env("ANDROID_KEYSTORE_PATH")?.let { file(it) }
            storePassword = env("ANDROID_KEYSTORE_PASSWORD")
            keyAlias = env("ANDROID_KEY_ALIAS")
            keyPassword = env("ANDROID_KEY_PASSWORD")
        }
    }
    buildTypes {
        release {
            if (testSigning) {
                applicationIdSuffix = ".qa"
                resValue("string", "app_name", testAppName)
            }
            signingConfig = signingConfigs.getByName(if (testSigning) "debug" else "release")
            isMinifyEnabled = false
            isDebuggable = true // allow use of ADB to manage files, etc
        }
        debug {
            applicationIdSuffix = ".qa.debug"
            resValue("string", "app_name", testAppName)
            isMinifyEnabled = false
            packaging {
                jniLibs.keepDebugSymbols.add("**/*.so")
            }
            isDebuggable = true
            isJniDebuggable = true
        }
    }
    testBuildType = "release"

    applicationVariants.all {
        val variantName = name.replaceFirstChar { char ->
            if (char.isLowerCase()) char.titlecase() else char.toString()
        }
        tasks.named("merge${variantName}Assets").configure {
            dependsOn("externalNativeBuild${variantName}")
            dependsOn(bundleZombieFarmIpa)
        }
    }

    sourceSets {
        getByName("main") {
            java.srcDir("${rootDir.parentFile}/vendor/SDL/android-project/app/src/main/java")
            assets.srcDir(generatedZombieFarmAssets)
            java.srcDir(rootProject.file(".tauri/kotlin"))
            jniLibs.srcDir(rootProject.file(".tauri/jni"))
        }
    }

    if (!project.hasProperty("EXCLUDE_NATIVE_LIBS")) {
        sourceSets {
            getByName("main") {
                jniLibs.srcDir("${projectDir}/jniLibs")
            }
        }
        externalNativeBuild {
            ndkBuild {
                path("jni/Android.mk")
            }
        }
    }

    lint {
        abortOnError = false
    }
    namespace = "org.touchhle.android"
}

// Inspect the resolved task graph so aggregate and abbreviated Gradle requests
// get the same check. IDE sync and compile-only tasks need no signing secrets.
gradle.taskGraph.whenReady {
    val appTasks = allTasks.filter { it.project == project }.map { it.name }.toSet()
    val pinSource = file("src/main/java/org/touchhle/android/ManagerActivity.java")
    fun checkSigner(configName: String, official: Boolean) {
        val config = android.signingConfigs.getByName(configName)
        val store = config.storeFile
        if (!official && store != null && !store.exists()) return // AGP provisions a fresh default debug store.
        check(store != null && store.isFile && !config.storePassword.isNullOrBlank() &&
            !config.keyAlias.isNullOrBlank() && !config.keyPassword.isNullOrBlank()) {
            "Missing Android $configName signing configuration. See scripts/README.md."
        }
        val keys = KeyStore.getInstance(store, config.storePassword!!.toCharArray())
        check(keys.isKeyEntry(config.keyAlias)) { "Missing $configName signing key entry." }
        val certificate = keys.getCertificate(config.keyAlias)
        val digest = MessageDigest.getInstance("SHA-256").digest(certificate.encoded)
            .joinToString("") { "%02x".format(it) }
        val pin = Regex("""OFFICIAL_CERT\s*=\s*"([a-fA-F0-9]{64})""").find(pinSource.readText())?.groupValues?.get(1)
            ?: error("Cannot read the official certificate fingerprint from ManagerActivity.java.")
        check(digest.equals(pin, ignoreCase = true) == official) {
            if (official) "Release certificate does not match the player APK."
            else "Test builds require a separate certificate from the player APK."
        }
    }
    fun packages(variant: String) = listOf("assemble$variant", "package$variant", "bundle$variant",
        "sign${variant}Bundle", "validateSigning$variant", "package${variant}AndroidTest").any { it in appTasks }
    if (packages("Release")) checkSigner(if (testSigning) "debug" else "release", !testSigning)
    if (packages("Debug")) checkSigner("debug", false)
}

cargoNdk {
    // Make sure this matches the android abiFilters above.
    targets = arrayListOf("arm64")
    module = ".."
    librariesNames = arrayListOf("libtouchHLE.so", "libSDL2.so", "libc++_shared.so")
    extraCargoEnv = mapOf(
        "ANDROID_NDK" to android.ndkDirectory.toString(),
        "ANDROID_NDK_HOME" to android.ndkDirectory.toString(),
        "SDL2_TOOLCHAIN" to rootProject.file("sdl2/ndk-compat.cmake").absolutePath,
    )

    if (DefaultNativePlatform.host().operatingSystem.isWindows) {
        val binPath =
            android.ndkDirectory.toPath().resolve("toolchains/llvm/prebuilt/windows-x86_64/bin")
        val clangPath = binPath.resolve("clang.exe")
        val clangXXPath = binPath.resolve("clang++.exe")

        if (!clangPath.toFile().exists()) {
            throw GradleException("NDK clang compiler not found at expected location: $clangPath")
        }
        if (!clangXXPath.toFile().exists()) {
            throw GradleException("NDK clang++ compiler not found at expected location: $clangXXPath")
        }

        extraCargoEnv.putAll(
            mapOf(
                "CC" to clangPath.toString(),
                "CXX" to clangXXPath.toString(),
                // The default generator on Windows (Visual Studio) does not respect
                // the CC and CXX environment variables. Using Ninja ensures that
                // the specified compilers are used
                "CMAKE_GENERATOR" to "Ninja",
            )
        )
    }
    // The default feature, "static", makes us use static linking for SDL2 and OpenAL Soft.
    // For Android, we need dynamic linking for SDL2, but static linking for OpenAL Soft.
    extraCargoBuildArguments = arrayListOf(
        "--lib",
        "--no-default-features",
        "--features",
        "touchHLE_openal_soft_wrapper/static,sdl2/bundled"
    )
}

dependencies {
    implementation(project(":tauri-android"))
    implementation("androidx.appcompat:appcompat:1.6.0")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.lifecycle:lifecycle-process:2.6.2")
    implementation(fileTree("libs") {
        include("*.jar")
    })
}
