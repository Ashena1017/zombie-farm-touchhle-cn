@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "PROFILE=release"
set "EXTREME_NATIVE=0"
set "CPU_TARGET="
set "FORWARD_ARGS="

:parse_args
if "%~1"=="" goto args_done
set "ARG=%~1"
if /i "%~1"=="debug" (
    set "PROFILE=debug"
    shift
    goto parse_args
)
if /i "%~1"=="release" (
    set "PROFILE=release"
    shift
    goto parse_args
)
if /i "%~1"=="native" (
    set "EXTREME_NATIVE=1"
    set "CPU_TARGET=native"
    shift
    goto parse_args
)
if /i "%~1"=="--native" (
    set "EXTREME_NATIVE=1"
    set "CPU_TARGET=native"
    shift
    goto parse_args
)
if /i "%~1"=="extreme" (
    set "EXTREME_NATIVE=1"
    set "CPU_TARGET=native"
    shift
    goto parse_args
)
if /i "%~1"=="--extreme" (
    set "EXTREME_NATIVE=1"
    set "CPU_TARGET=native"
    shift
    goto parse_args
)
if /i "%~1"=="no-native" (
    set "EXTREME_NATIVE=0"
    set "CPU_TARGET="
    shift
    goto parse_args
)
if /i "%~1"=="--no-native" (
    set "EXTREME_NATIVE=0"
    set "CPU_TARGET="
    shift
    goto parse_args
)
if /i "%~1"=="--cpu" (
    if "%~2"=="" (
        echo Missing CPU name after --cpu.
        echo Example: build_windows.bat release --cpu raptorlake
        exit /b 1
    )
    set "EXTREME_NATIVE=1"
    set "CPU_TARGET=%~2"
    shift
    shift
    goto parse_args
)
if /i "!ARG:~0,6!"=="--cpu=" (
    if "!ARG:~6!"=="" (
        echo Missing CPU name after --cpu=.
        echo Example: build_windows.bat release --cpu=raptorlake
        exit /b 1
    )
    set "EXTREME_NATIVE=1"
    set "CPU_TARGET=!ARG:~6!"
    shift
    goto parse_args
)
if /i "!ARG:~0,4!"=="cpu=" (
    if "!ARG:~4!"=="" (
        echo Missing CPU name after cpu=.
        echo Example: build_windows.bat release cpu=raptorlake
        exit /b 1
    )
    set "EXTREME_NATIVE=1"
    set "CPU_TARGET=!ARG:~4!"
    shift
    goto parse_args
)
if defined FORWARD_ARGS (
    set "FORWARD_ARGS=%FORWARD_ARGS% %1"
) else (
    set "FORWARD_ARGS=%1"
)
shift
goto parse_args

:args_done

set "VSDEVCMD="

if defined VSDEVCMD_PATH (
    if exist "%VSDEVCMD_PATH%" (
        set "VSDEVCMD=%VSDEVCMD_PATH%"
    )
)

if not defined VSDEVCMD (
    set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
    if exist "%VSWHERE%" (
        for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find Common7\Tools\VsDevCmd.bat`) do (
            set "VSDEVCMD=%%I"
        )
    )
)

if not defined VSDEVCMD if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" (
    set "VSDEVCMD=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"
)
if not defined VSDEVCMD if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" (
    set "VSDEVCMD=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
)
if not defined VSDEVCMD if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional\Common7\Tools\VsDevCmd.bat" (
    set "VSDEVCMD=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional\Common7\Tools\VsDevCmd.bat"
)
if not defined VSDEVCMD if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Enterprise\Common7\Tools\VsDevCmd.bat" (
    set "VSDEVCMD=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Enterprise\Common7\Tools\VsDevCmd.bat"
)

if not defined VSDEVCMD (
    echo Failed to find VsDevCmd.bat.
    echo Install Visual Studio 2022 Build Tools with C++ tools, or set VSDEVCMD_PATH.
    exit /b 1
)

set "CMAKE_BIN="
for /d %%D in ("%SCRIPT_DIR%..\.codex_deps\cmake-*-windows-x86_64") do (
    if exist "%%~fD\bin\cmake.exe" (
        set "CMAKE_BIN=%%~fD\bin"
    )
)
if not defined CMAKE_BIN if exist "%SCRIPT_DIR%.codex_deps\cmake-3.29.6-windows-x86_64\bin\cmake.exe" (
    set "CMAKE_BIN=%SCRIPT_DIR%.codex_deps\cmake-3.29.6-windows-x86_64\bin"
)

set "CARGO_FLAGS="
if /i "%PROFILE%"=="release" (
    set "CARGO_FLAGS=--release"
)

if "%EXTREME_NATIVE%"=="1" (
    if not defined CPU_TARGET (
        set "CPU_TARGET=native"
    )
    set "NATIVE_RUSTFLAGS=-C target-cpu=!CPU_TARGET!"
    if defined RUSTFLAGS (
        set "RUSTFLAGS=!RUSTFLAGS! !NATIVE_RUSTFLAGS!"
    ) else (
        set "RUSTFLAGS=!NATIVE_RUSTFLAGS!"
    )
    if /i "%PROFILE%"=="release" (
        set "CARGO_PROFILE_RELEASE_OPT_LEVEL=3"
        set "CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1"
        set "CARGO_PROFILE_RELEASE_LTO=fat"
    ) else (
        set "CARGO_PROFILE_DEV_OPT_LEVEL=3"
        set "CARGO_PROFILE_DEV_CODEGEN_UNITS=1"
        set "CARGO_PROFILE_DEV_LTO=fat"
    )
)

echo Using VS developer environment: "%VSDEVCMD%"
if defined CMAKE_BIN (
    echo Using bundled CMake: "%CMAKE_BIN%"
)
echo Building touchHLE ^(%PROFILE%^)
if "%EXTREME_NATIVE%"=="1" (
    echo CPU optimization: enabled ^(target-cpu=!CPU_TARGET!^)
    echo RUSTFLAGS=!RUSTFLAGS!
    if /i "%PROFILE%"=="release" (
        echo Cargo profile: opt-level=!CARGO_PROFILE_RELEASE_OPT_LEVEL!, codegen-units=!CARGO_PROFILE_RELEASE_CODEGEN_UNITS!, lto=!CARGO_PROFILE_RELEASE_LTO!
    ) else (
        echo Cargo profile: opt-level=!CARGO_PROFILE_DEV_OPT_LEVEL!, codegen-units=!CARGO_PROFILE_DEV_CODEGEN_UNITS!, lto=!CARGO_PROFILE_DEV_LTO!
    )
)

call "%VSDEVCMD%" -arch=x64 >nul
if errorlevel 1 exit /b %errorlevel%

if defined CMAKE_BIN (
    set "PATH=%CMAKE_BIN%;%PATH%"
)

cargo build %CARGO_FLAGS% %FORWARD_ARGS%
exit /b %errorlevel%
