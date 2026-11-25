# Extract the portable ZIP into a temporary directory, verify and launch it there.
param(
    [string]$ZipPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\windows\zombie-farm-windows-x64.zip'),
    [ValidateRange(8, 600)]
    [int]$Seconds = 45,
    [switch]$LayoutOnly
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_file_hash.ps1')
$archive = (Resolve-Path -LiteralPath $ZipPath).Path
Add-Type -AssemblyName System.IO.Compression.FileSystem
$tempDir = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd('\')
$checkDir = Join-Path $tempDir ('zfr-windowstest-' + [Guid]::NewGuid().ToString('N'))
$proc = $null
New-Item -ItemType Directory -Path $checkDir | Out-Null
try {
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $checkDir)
    $roots = @(Get-ChildItem -LiteralPath $checkDir -Force)
    if ($roots.Count -ne 1 -or -not $roots[0].PSIsContainer) {
        throw 'The Windows ZIP must have a single top-level folder.'
    }
    $release = $roots[0].FullName
    $hleDir = Join-Path $release 'touchHLE'
    $hle = Join-Path $hleDir 'touchHLE.exe'
    $ipaDir = Join-Path $release 'zombie_farm_ipa'
    $logDir = Join-Path (Split-Path -Parent $PSScriptRoot) '_analysis\perf'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $log = Join-Path $logDir 'release_verify.log'

    Write-Host "bundle: $release"
    if (-not (Test-Path -LiteralPath $hle -PathType Leaf)) { throw "Missing emulator: $hle" }

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
    if ($ipas.Count -ne 1) { $ok = $false }

    # The release sandbox must be empty so each player starts a fresh profile.
    $save = Join-Path $hleDir 'touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents\saveGame.bin2'
    $sandboxFiles = @(Get-ChildItem -LiteralPath (Join-Path $hleDir 'touchHLE_sandbox') -Recurse -File -ErrorAction SilentlyContinue)
    Write-Host ("  sandbox files: {0} -- {1}" -f $sandboxFiles.Count, $(if ($sandboxFiles.Count -eq 0) { 'clean install profile' } else { 'FAIL: packaged files detected' }))
    if ($sandboxFiles.Count -gt 0 -or (Test-Path -LiteralPath $save)) { $ok = $false }

    $manifest = Join-Path $release 'SHA256SUMS.txt'
    $expectedFiles = @{}
    foreach ($line in Get-Content -LiteralPath $manifest -Encoding UTF8) {
        if ($line -notmatch '^(?<Hash>[a-fA-F0-9]{64})  (?<Name>.+)$') {
            throw "Invalid checksum line: $line"
        }
        $relativeName = $Matches['Name']
        if ($expectedFiles.ContainsKey($relativeName)) { throw "Duplicate checksum path: $relativeName" }
        $expectedFiles[$relativeName] = $Matches['Hash']
    }
    foreach ($file in Get-ChildItem -LiteralPath $release -File -Recurse -Force) {
        $relativeName = $file.FullName.Substring($release.Length + 1)
        if ($relativeName -eq 'SHA256SUMS.txt') { continue }
        if ((Get-Sha256Hex -Path $file.FullName) -ne $expectedFiles[$relativeName]) {
            throw "Missing or incorrect checksum: $relativeName"
        }
        $expectedFiles.Remove($relativeName)
    }
    if ($expectedFiles.Count) { throw 'The ZIP is missing files from SHA256SUMS.txt.' }
    if (-not $ok) { throw 'The ZIP has an invalid bundle layout.' }

    $launcher = Join-Path $release '游戏管理.exe'
    $nativeManager = Test-Path -LiteralPath (Join-Path $release 'ManagerWorker.ps1') -PathType Leaf
    if ($nativeManager) {
        $pe = [IO.BinaryReader]::new([IO.File]::OpenRead($launcher))
        try {
            $pe.BaseStream.Position = 0x3C
            $peHeader = $pe.ReadUInt32()
            $pe.BaseStream.Position = $peHeader
            if ($pe.ReadUInt32() -ne 0x4550 -or $pe.ReadUInt16() -ne 0x8664) {
                throw 'Expected a native x64 manager.'
            }
            $pe.BaseStream.Position = $peHeader + 0x5C
            if ($pe.ReadUInt16() -ne 2) { throw 'Expected a windowed manager executable.' }
        } finally { $pe.Dispose() }
    } else {
        # Released WinForms bundles have a managed launcher and no worker script.
        try { [void][Reflection.AssemblyName]::GetAssemblyName($launcher) }
        catch { throw 'A native Windows manager requires ManagerWorker.ps1.' }
    }
    if ($LayoutOnly) {
        Write-Host 'RESULT: PASS - ZIP layout and checksums'
        return
    }

    # --- 2. actually run it -----------------------------------------------------
    Write-Host ''
    Write-Host '--- checking settings through the bundled Windows manager ---'
    if ($nativeManager) {
        $checkInfo = [Diagnostics.ProcessStartInfo]::new($launcher, '--check-package')
        $checkInfo.WorkingDirectory = $release
        $checkInfo.UseShellExecute = $false
        $proc = [Diagnostics.Process]::Start($checkInfo)
        if (-not $proc.WaitForExit(60000)) { throw 'The bundled manager package check timed out.' }
        if ($proc.ExitCode -ne 0) { throw "The bundled manager package check failed (exit $($proc.ExitCode))." }
    } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $release 'GameManager.ps1') -ShowSettings
        if ($LASTEXITCODE -ne 0) { throw 'The legacy Windows manager could not read settings.' }
    }

    Write-Host ''
    Write-Host '--- launching the bundled copy ---'

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $hle
    $env:PATH = $release + ';' + $env:PATH
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
    $testStarted = [DateTime]::UtcNow
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()

    # The game renders in a window; wait for it, then close it.
    Start-Sleep -Seconds 6
    $windowFound = $false
    $deadline = $testStarted.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $proc.Refresh()
        if (-not $proc.HasExited -and $proc.MainWindowHandle -ne 0) { $windowFound = $true; break }
        if ($proc.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }

    # Keep observing until the requested runtime has really elapsed. Finding a
    # window early must not turn a 45-second check into a 14-second check.
    while (-not $proc.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    $stillRunning = -not $proc.HasExited
    $elapsed = ([DateTime]::UtcNow - $testStarted).TotalSeconds

    Write-Host ("  window appeared: {0}" -f $(if ($windowFound) { 'yes' } else { 'NO' }))
    Write-Host ("  still running after {0:F1}s: {1}" -f $elapsed, $(if ($stillRunning) { 'yes' } else { "no (exit $($proc.ExitCode))" }))

    # Collect output.
    if ($stillRunning) {
        try { $proc.Kill() } catch { }
    }
    $out = ''; $err = ''
    if (-not $proc.HasExited) { try { $proc.WaitForExit(10000) | Out-Null } catch { } }
    try { $out = $stdoutTask.GetAwaiter().GetResult() } catch { }
    try { $err = $stderrTask.GetAwaiter().GetResult() } catch { }

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
    if (-not $ok) { throw 'Standalone launch failed.' }
    Write-Host 'RESULT: PASS - the ZIP runs standalone'
}
finally {
    if ($proc -and -not $proc.HasExited) {
        $proc.Kill()
        $proc.WaitForExit()
    }
    $resolved = (Resolve-Path -LiteralPath $checkDir).Path
    if ((Split-Path -Parent $resolved) -ne $tempDir -or (Split-Path -Leaf $resolved) -notmatch '^zfr-windowstest-[a-f0-9]{32}$') {
        throw "Unexpected verification directory: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
