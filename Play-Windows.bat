@echo off
setlocal
set "ZFR_WINDOWS_DIR=%~dp0windows"
rem Code points for the localized launcher name keep this batch file ASCII.
powershell.exe -NoProfile -Command "$ErrorActionPreference = 'Stop'; $launcherName = (-join [char[]](0x6E38,0x620F,0x7BA1,0x7406)) + '.exe'; [void][Diagnostics.Process]::Start((Join-Path $env:ZFR_WINDOWS_DIR $launcherName))"
exit /b %errorlevel%
