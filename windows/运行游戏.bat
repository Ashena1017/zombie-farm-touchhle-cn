@echo off
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0StartZombieFarmNextHour.ps1" -NoSkip
