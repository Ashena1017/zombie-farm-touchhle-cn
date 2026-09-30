# Render 使用说明.html headlessly and screenshot it, so we can check the
# typography without opening a visible browser window.
$edge = @(
    "$env:ProgramFiles (x86)\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles (x86)\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $edge) { throw 'no Edge/Chrome found' }

$root = Split-Path -Parent $PSScriptRoot
$html = Join-Path $root 'Release\使用说明.html'
$png  = Join-Path $PSScriptRoot '_html_preview.png'
if (Test-Path -LiteralPath $png) { Remove-Item -LiteralPath $png -Force }

# Headless Edge mangles non-ASCII file:// URIs on this machine, so preview via an
# ASCII-named temp copy. The shipped file keeps its Chinese name; only the
# screenshot path changes.
$tmp = Join-Path $env:TEMP 'zf_readme_preview.html'
Copy-Item -LiteralPath $html -Destination $tmp -Force
$uri = ([System.Uri]$tmp).AbsoluteUri
& $edge --headless --disable-gpu "--screenshot=$png" --window-size=860,2400 --hide-scrollbars $uri 2>&1 | Out-Null
Start-Sleep -Milliseconds 800
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $png)) { throw "screenshot not produced by $edge" }
Write-Host ("OK  {0}  {1:N0} B" -f $png, (Get-Item -LiteralPath $png).Length)
