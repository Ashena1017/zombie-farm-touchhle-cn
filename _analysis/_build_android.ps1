param(
    [string]$Gradle = 'gradle'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$androidProject = Join-Path $root 'touchHLE\touchHLE-fork\android'
$builtApk = Join-Path $androidProject 'app\build\outputs\apk\release\app-release.apk'
$outputDir = Join-Path $root 'touchHLE-zombiefarm-android-arm64'
$outputApk = Join-Path $outputDir 'touchHLE-zombiefarm-android-arm64-fixed.apk'
$localPropertiesPath = Join-Path $androidProject 'local.properties'

$gradleCommand = Get-Command $Gradle -ErrorAction Stop
$sdkRoot = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { $null }
if (-not $sdkRoot -and (Test-Path -LiteralPath $localPropertiesPath -PathType Leaf)) {
    $sdkLine = Get-Content -LiteralPath $localPropertiesPath -Raw -Encoding ASCII | Select-String -Pattern '(?m)^sdk\.dir=(.+)$'
    if ($sdkLine) {
        $sdkRoot = $sdkLine.Matches[0].Groups[1].Value.Trim() -replace '/', '\\'
    }
}
if (-not $sdkRoot) {
    throw 'Set ANDROID_HOME or ANDROID_SDK_ROOT, or provide sdk.dir in android/local.properties.'
}
$sdkCmake = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'cmake') -Filter cmake.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$systemCmake = Get-Command cmake -ErrorAction SilentlyContinue
if ($systemCmake) {
    $env:CMAKE = $systemCmake.Source
} elseif ($sdkCmake) {
    $env:CMAKE = $sdkCmake.FullName
    $env:Path = "$(Split-Path $sdkCmake.FullName);$env:Path"
}
$sdkNinja = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'cmake') -Filter ninja.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($sdkNinja) {
    $env:Path = "$(Split-Path $sdkNinja.FullName);$env:Path"
}
$env:CMAKE_POLICY_VERSION_MINIMUM = '3.5'

$forkRoot = Split-Path -Parent $androidProject
$resourceDir = Join-Path $androidProject 'app\src\main\res\drawable-nodpi'
$resourceLinks = @('icon.png', 'icon_preview.png', 'icon_unofficial.png')
$assetDir = Join-Path $androidProject 'app\src\main\assets'
$assetLinks = @('touchHLE_dylibs', 'touchHLE_fonts', 'touchHLE_default_options.txt')
$originalResources = @{}
$originalJniLibraries = @{}
try {
    if (-not (Test-Path -LiteralPath $localPropertiesPath -PathType Leaf)) {
        $sdkPath = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { $env:ANDROID_SDK_ROOT }
        $sdkPath = $sdkPath.Replace('\', '/')
        [System.IO.File]::WriteAllText($localPropertiesPath, "sdk.dir=$sdkPath`n", [System.Text.Encoding]::ASCII)
    }

    foreach ($name in $resourceLinks) {
        $resourcePath = Join-Path $resourceDir $name
        $linkText = [System.IO.File]::ReadAllText($resourcePath)
        $targetPath = Join-Path (Join-Path $forkRoot 'res') $name
        if ($linkText.Trim() -eq "../../../../../../res/$name") {
            if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
                throw "Android resource symlink target is missing: $targetPath"
            }
            $originalResources[$resourcePath] = [System.IO.File]::ReadAllBytes($resourcePath)
            Copy-Item -LiteralPath $targetPath -Destination $resourcePath -Force
        }
    }

    foreach ($name in $assetLinks) {
        $assetPath = Join-Path $assetDir $name
        $linkText = [System.IO.File]::ReadAllText($assetPath).Trim()
        $targetPath = Join-Path $forkRoot $name
        $expectedLink = "../../../../../$name/"
        if ($linkText -eq $expectedLink -or $linkText -eq $expectedLink.TrimEnd('/')) {
            if (-not (Test-Path -LiteralPath $targetPath)) {
                throw "Android asset target is missing: $targetPath"
            }
            $originalResources[$assetPath] = [System.IO.File]::ReadAllBytes($assetPath)
            Remove-Item -LiteralPath $assetPath -Force
            Copy-Item -LiteralPath $targetPath -Destination $assetPath -Recurse -Force
        }
    }

    # The repository may contain a stale libc++_shared.so left by an older
    # cargo-ndk run. It must match the NDK used for this build, otherwise
    # Android can reject libtouchHLE.so with a missing C++ ABI symbol.
    $ndkRoot = if ($env:ANDROID_NDK) {
        $env:ANDROID_NDK
    } else {
        Join-Path $sdkRoot 'ndk\27.2.12479018'
    }
    $ndkLibcxx = Join-Path $ndkRoot 'toolchains\llvm\prebuilt\windows-x86_64\sysroot\usr\lib\aarch64-linux-android\libc++_shared.so'
    $jniLibcxx = Join-Path $androidProject 'app\src\main\jniLibs\arm64-v8a\libc++_shared.so'
    $cargoLibcxx = Join-Path $forkRoot 'target\aarch64-linux-android\release\libc++_shared.so'
    if (Test-Path -LiteralPath $ndkLibcxx -PathType Leaf) {
        foreach ($destination in @($jniLibcxx, $cargoLibcxx)) {
            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                $originalJniLibraries[$destination] = [System.IO.File]::ReadAllBytes($destination)
            }
            else {
                $originalJniLibraries[$destination] = $null
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $ndkLibcxx -Destination $destination -Force
        }
    } else {
        throw "Matching NDK libc++_shared.so not found: $ndkLibcxx"
    }

    # Force a fresh merge so a previously cached libc++_shared.so cannot survive.
    & $gradleCommand.Source --project-dir $androidProject clean assembleRelease
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle failed with exit code $LASTEXITCODE."
    }
}
finally {
    foreach ($resourcePath in $originalResources.Keys) {
        if (Test-Path -LiteralPath $resourcePath) {
            Remove-Item -LiteralPath $resourcePath -Recurse -Force
        }
        [System.IO.File]::WriteAllBytes($resourcePath, $originalResources[$resourcePath])
    }
    foreach ($jniPath in $originalJniLibraries.Keys) {
        if ($null -eq $originalJniLibraries[$jniPath]) {
            Remove-Item -LiteralPath $jniPath -Force -ErrorAction SilentlyContinue
        }
        else {
            [System.IO.File]::WriteAllBytes($jniPath, $originalJniLibraries[$jniPath])
        }
    }
}
if (-not (Test-Path -LiteralPath $builtApk -PathType Leaf)) {
    throw "Gradle reported success but did not create $builtApk."
}

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
Copy-Item -LiteralPath $builtApk -Destination $outputApk -Force
& (Join-Path $PSScriptRoot '_verify_android_package.ps1') -ApkPath $outputApk
if ($LASTEXITCODE -ne 0) {
    throw 'The built Android APK did not pass package verification.'
}
Write-Host "Built Android APK: $outputApk"
