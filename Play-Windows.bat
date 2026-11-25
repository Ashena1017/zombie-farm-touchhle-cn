@echo off
setlocal
for /f "tokens=2 delims=:" %%p in ('chcp') do set "zfr_codepage=%%p"
chcp 65001 >nul
start "" "%~dp0windows\游戏管理.exe"
set "zfr_result=%errorlevel%"
chcp %zfr_codepage% >nul
exit /b %zfr_result%
