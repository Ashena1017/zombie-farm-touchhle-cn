# Verify the Release bundle actually works, IN PLACE.
#
# The point of this test is that "the file list looks right" is not evidence: a
# missing resource only shows up when touchHLE tries to load it. So this runs the
# bundled copy with the bundled game and checks that it reaches gameplay.
#
# It deliberately uses the Release folder's own files (its touchHLE.exe, its IPA,
# its options file), so anything missing from the bundle fails here.
#
# Safety: the game is launched through the bundle's own GameManager.ps1 launch
# path, and the sandbox copy is restored afterwards.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$Seconds = 45
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'

$release = Join-Path $Root 'Release'
# touchHLE and its resources live in a subfolder of the bundle; the manager and its
# runtime DLLs sit at the top level.
$hleDir = Join-Path $release 'touchHLE'
$hle = Join-Path $hleDir 'touchHLE.exe'
$ipaDir = Join-Path $release 'zombie_farm_ipa'
$log = Join-Path $Root '_analysis\perf\release_verify.log'

Write-Host "bundle: $release"
if (-not (Test-Path -LiteralPath $hle)) { Write-Host "FAIL: no touchHLE.exe at $hle"; exit 1 }

# --- 1. static checks -------------------------------------------------------
Write-Host ''
Write-Host '--- required files present ---'
# Top level: the manager and its runtime DLLs.
$requiredTop = @(
    '游戏管理.exe', 'GameManager.ps1',
    'MSVCP140.dll', 'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll',
    'zombie_farm_ipa', 'touchHLE'
)
# Inside touchHLE\: the emulator and its resources.
$requiredHle = @(
    'touchHLE.exe', 'touchHLE_options.txt', 'touchHLE_default_options.txt',
    'touchHLE_dylibs', 'touchHLE_fonts', 'touchHLE_sandbox'
)
$ok = $true
foreach ($r in $requiredTop) {
    $p = Join-Path $release $r
    $exists = Test-Path -LiteralPath $p
    if (-not $exists) { $ok = $false }
    Write-Host ("  {0,-34} {1}" -f $r, $(if ($exists) { 'ok' } else { 'MISSING' }))
}
foreach ($r in $requiredHle) {
    $p = Join-Path $hleDir $r
    $exists = Test-Path -LiteralPath $p
    if (-not $exists) { $ok = $false }
    Write-Host ("  touchHLE\{0,-25} {1}" -f $r, $(if ($exists) { 'ok' } else { 'MISSING' }))
}

# The game must be there, and touchHLE_dylibs must contain the libraries this app
# needs (checking fs.rs: libgcc_s.1, libstdc++.6.0.9, libz.1.2.3).
Write-Host ''
Write-Host '--- bundle contents that matter ---'
$dylibs = @(Get-ChildItem (Join-Path $hleDir 'touchHLE_dylibs') -File | ForEach-Object { $_.Name })
Write-Host "  dylibs: $($dylibs.Count) file(s)"
foreach ($need in @('libgcc_s.1.dylib', 'libstdc++.6.0.9.dylib', 'libz.1.2.3.dylib')) {
    $has = $dylibs -contains $need
    # A missing dylib makes touchHLE panic at startup, so this is not cosmetic.
    Write-Host ("    {0,-28} {1}" -f $need, $(if ($has) { 'ok' } else { 'MISSING' }))
    if (-not $has) { $ok = $false }
}
$ipas = @(Get-ChildItem -LiteralPath $ipaDir -Filter '*.ipa' -File)
Write-Host "  IPAs: $($ipas.Count) -- $(($ipas | ForEach-Object { $_.Name }) -join ', ')"
if ($ipas.Count -lt 1) { $ok = $false }

# The release sandbox must be empty so each player starts a fresh profile.
$save = Join-Path $hleDir 'touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents\saveGame.bin2'
$sandboxFiles = @(Get-ChildItem -LiteralPath (Join-Path $hleDir 'touchHLE_sandbox') -Recurse -File -ErrorAction SilentlyContinue)
Write-Host ("  sandbox files: {0} -- {1}" -f $sandboxFiles.Count, $(if ($sandboxFiles.Count -eq 0) { 'clean install profile' } else { 'FAIL: packaged files detected' }))
if ($sandboxFiles.Count -gt 0 -or (Test-Path -LiteralPath $save)) { $ok = $false }

# --- 2. actually run it -----------------------------------------------------
Write-Host ''
Write-Host '--- launching the bundled copy ---'

# Snapshot the whole sandbox and clean up run artifacts afterwards: a launch also
# writes Library\Preferences and touchHLE_log.txt, and shipping those would mean
# shipping a bundle that has visibly been run already.
$sandbox = Join-Path $hleDir 'touchHLE_sandbox'
$sandboxSnapshot = Join-Path $env:TEMP ('relv_' + [Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $sandbox) {
    Copy-Item -LiteralPath $sandbox -Destination $sandboxSnapshot -Recurse -Force
}

Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $hle
$psi.Arguments = '"' + $ipas[0].FullName + '" --landscape-right'
# MUST be touchHLE's own folder: resources resolve against the CURRENT DIRECTORY
# (src/paths.rs), not the executable location, so the parent folder panics with
#   Unexpected I/O failure ... "touchHLE_dylibs/libz.1.2.3.dylib"
$psi.WorkingDirectory = $hleDir
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true

$env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
$proc = [System.Diagnostics.Process]::Start($psi)

# The game renders in a window; wait for it, then close it.
Start-Sleep -Seconds 6
$windowFound = $false
$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline) {
    $p = Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($p -and $p.MainWindowHandle -ne 0) { $windowFound = $true; break }
    if ($proc.HasExited) { break }
    Start-Sleep -Milliseconds 500
}

# Let it run a little so loading failures would surface.
Start-Sleep -Seconds 8
$stillRunning = -not $proc.HasExited

Write-Host ("  window appeared: {0}" -f $(if ($windowFound) { 'yes' } else { 'NO' }))
Write-Host ("  still running after {0}s: {1}" -f ($Seconds), $(if ($stillRunning) { 'yes' } else { "no (exit $($proc.ExitCode))" }))

# Collect output.
if ($stillRunning) {
    Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
$out = ''; $err = ''
try { $out = $proc.StandardOutput.ReadToEnd() } catch { }
try { $err = $proc.StandardError.ReadToEnd() } catch { }
if (-not $proc.HasExited) { try { $proc.WaitForExit(10000) | Out-Null } catch { } }

$text = $out + "`n" + $err
[System.IO.File]::WriteAllText($log, $text, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ''
Write-Host '--- what touchHLE said ---'
# These must be messages a RELEASE build actually emits. "Loading armv7 slice"
# used to be asserted here, but that comes from `log_dbg!`, which only prints when
# its module is listed in log::ENABLED_MODULES - so in a normal run it can never
# appear and the line was permanently "NOT FOUND", which reads like a failure.
# The replacements are release-visible AND meaningful: the options line proves the
# options file was applied, and the device-family line proves --device-family took
# effect (the emulator would otherwise pick iPhone and the game would lay out
# wrongly).
foreach ($pattern in @(
    'Using options from',
    'iPad device family is chosen',
    'CPU emulation begins'
)) {
    $hit = ($text -split "`r?`n") | Select-String -Pattern ([regex]::Escape($pattern)) | Select-Object -First 1
    Write-Host ("  {0,-32} {1}" -f $pattern, $(if ($hit) { 'found' } else { 'NOT FOUND' }))
    if (-not $hit) { $ok = $false }
}
$panic = ($text -split "`r?`n") | Select-String -Pattern 'panicked|assertion failed|Unexpected I/O failure' | Select-Object -First 3
if ($panic) {
    Write-Host '  errors:'
    foreach ($p in $panic) { Write-Host "    $($p.Line.Trim())" }
} else {
    Write-Host '  no panics'
}

# A missing dylib or font produces a specific message; check for those too.
$missing = ($text -split "`r?`n") | Select-String -Pattern 'No such file|could not open|Could not open|not found' | Select-Object -First 5
if ($missing) {
    Write-Host '  missing-file messages:'
    foreach ($m in $missing) { Write-Host "    $($m.Line.Trim())" }
}

$ran = $windowFound -and $stillRunning -and -not $panic
if (-not $ran) { $ok = $false }

# --- 3. restore the bundle to its shipped state ----------------------------
if (Test-Path -LiteralPath $sandbox) {
    Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
}
if (Test-Path -LiteralPath $sandboxSnapshot) {
    Copy-Item -LiteralPath $sandboxSnapshot -Destination $sandbox -Recurse -Force
    Remove-Item -LiteralPath $sandboxSnapshot -Recurse -Force -ErrorAction SilentlyContinue
}
foreach ($junk in @('touchHLE_log.txt', 'zfr_last_run.log', 'zfr_last_launch.txt',
                    'launcher_selected_ipa.txt')) {
    $jp = Join-Path $hleDir $junk
    if (Test-Path -LiteralPath $jp) { Remove-Item -LiteralPath $jp -Force -ErrorAction SilentlyContinue }
}
Write-Host ''
Write-Host '  bundle restored to its shipped state'

Write-Host ''
Write-Host ("RESULT: " + $(if ($ok) { 'PASS - the bundle runs standalone' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })
