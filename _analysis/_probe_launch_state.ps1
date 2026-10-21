# One-off end-to-end probe for the launch path.
#
# Answers one question with evidence: when the manager starts the game, does it
# (a) record the real process, (b) wait for it, (c) notice when it is gone, and
# (d) forget it again -- so that "is the game running?" can never go stale?
#
# Runs entirely inside a throwaway copy of Release\ in %TEMP%. The player's
# sandbox, save files and logs are never touched: the copy starts with an empty
# sandbox and is deleted afterwards.
#
# ASCII only, and the button caption is built from code points so this file needs
# no BOM (see _analysis\_ensure_bom.ps1 for why that matters).
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$BootTimeoutSeconds = 45,
    [int]$GameWindowTimeoutSeconds = 90,
    [switch]$KeepTemp
)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class ZProbe {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern IntPtr SendMessageW(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr wp, IntPtr lp);

    public static List<IntPtr> ChildrenOf(IntPtr parent) {
        List<IntPtr> found = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr l) { found.Add(h); return true; }, IntPtr.Zero);
        return found;
    }

    public static List<IntPtr> TopLevelOf(uint pid) {
        List<IntPtr> found = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr l) {
            uint owner; GetWindowThreadProcessId(h, out owner);
            if (owner == pid) { found.Add(h); }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static string TextOf(IntPtr h) {
        StringBuilder sb = new StringBuilder(512);
        GetWindowTextW(h, sb, sb.Capacity);
        return sb.ToString();
    }

    public static string ClassOf(IntPtr h) {
        StringBuilder sb = new StringBuilder(256);
        GetClassNameW(h, sb, sb.Capacity);
        return sb.ToString();
    }
}
'@

$failures = 0
function Check([string]$Name, [bool]$Ok, [string]$Detail = '') {
    $verdict = if ($Ok) { 'PASS' } else { 'FAIL' }
    Write-Host ("  {0,-46} {1} {2}" -f $Name, $verdict, $Detail)
    if (-not $Ok) { $script:failures++ }
}

$source = Join-Path $ProjectRoot 'Release'
if (-not (Test-Path -LiteralPath (Join-Path $source 'GameManager.ps1'))) {
    throw "Release copy not found under $source"
}

$work = Join-Path $env:TEMP ('zfr-launch-state-' + [Guid]::NewGuid().ToString('N'))
Write-Host "work copy: $work"
Write-Host ''
Copy-Item -LiteralPath $source -Destination $work -Recurse -Force

$hleDir = Join-Path $work 'touchHLE'
$stateFile = Join-Path $hleDir 'zfr_running.json'
$managerLog = Join-Path $hleDir 'zfr_manager.log'
$sandbox = Join-Path $hleDir 'touchHLE_sandbox'
Remove-Item -LiteralPath $stateFile, $managerLog -Force -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $sandbox) { Remove-Item -LiteralPath $sandbox -Recurse -Force }
[void][System.IO.Directory]::CreateDirectory($sandbox)

# The caption of the button to click, built without non-ASCII source text.
$startCaption = [string][char]0x542F + [char]0x52A8 + [char]0x6E38 + [char]0x620F

$manager = $null
$gamePid = 0
try {
    $manager = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', (Join-Path $work 'GameManager.ps1')) `
        -PassThru

    Write-Host '--- manager boots ---'
    $deadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
    $formHandle = [IntPtr]::Zero
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 400
        $manager.Refresh()
        if ($manager.HasExited) { break }
        if ($manager.MainWindowHandle -ne [IntPtr]::Zero) { $formHandle = $manager.MainWindowHandle; break }
    }
    Check 'manager window appears' ($formHandle -ne [IntPtr]::Zero) ("handle=$formHandle")
    if ($formHandle -eq [IntPtr]::Zero) { throw 'manager never showed a window' }

    # Find the start button (its caption is built above) among the form's children.
    $button = [IntPtr]::Zero
    foreach ($child in [ZProbe]::ChildrenOf($formHandle)) {
        if ([ZProbe]::ClassOf($child) -notlike '*BUTTON*') { continue }
        if ([ZProbe]::TextOf($child) -eq $startCaption) { $button = $child; break }
    }
    Check 'start button found' ($button -ne [IntPtr]::Zero)
    if ($button -eq [IntPtr]::Zero) { throw 'start button not found' }

    Write-Host ''
    Write-Host '--- launch ---'
    # PostMessage, not SendMessage: the click handler runs on the manager's UI
    # thread and blocks there for the whole game session, so a synchronous send
    # would never return.
    [void][ZProbe]::PostMessageW($button, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)   # BM_CLICK

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline -and -not (Test-Path -LiteralPath $stateFile)) { Start-Sleep -Milliseconds 250 }
    Check 'run record written at launch' (Test-Path -LiteralPath $stateFile)

    $record = $null
    if (Test-Path -LiteralPath $stateFile) {
        $record = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        $gamePid = [int]$record.pid
    }
    $live = Get-Process -Id $gamePid -ErrorAction SilentlyContinue
    Check 'recorded pid is alive' ([bool]$live) ("pid=$gamePid")
    if ($live) {
        $path = try { $live.Path } catch { '' }
        Check 'recorded exe is this copy' ($path -eq (Join-Path $hleDir 'touchHLE.exe')) $path
    }

    # The game should open its own window; close it the way a player would.
    Write-Host ''
    Write-Host '--- game window ---'
    $deadline = (Get-Date).AddSeconds($GameWindowTimeoutSeconds)
    $gameHandle = [IntPtr]::Zero
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if (-not (Get-Process -Id $gamePid -ErrorAction SilentlyContinue)) { break }
        foreach ($h in [ZProbe]::TopLevelOf([uint32]$gamePid)) {
            if ([ZProbe]::ClassOf($h) -like '*SDL*') { $gameHandle = $h; break }
        }
        if ($gameHandle -eq [IntPtr]::Zero -and (Get-Process -Id $gamePid -ErrorAction SilentlyContinue).MainWindowHandle -ne [IntPtr]::Zero) {
            $gameHandle = (Get-Process -Id $gamePid).MainWindowHandle
        }
        if ($gameHandle -ne [IntPtr]::Zero) { break }
    }
    Check 'game window appears' ($gameHandle -ne [IntPtr]::Zero) ("handle=$gameHandle")

    # Ask the game to quit the way a player would. Whether the guest honours
    # WM_CLOSE depends on which screen it is on, so if it is still there after a
    # grace period the probe kills it -- which is also worth testing, because a
    # crash is exactly "the process disappeared without a clean exit".
    Write-Host ''
    Write-Host '--- shutdown ---'
    if ($gameHandle -ne [IntPtr]::Zero) {
        [void][ZProbe]::PostMessageW($gameHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)   # WM_CLOSE
        $deadline = (Get-Date).AddSeconds(25)
        while ((Get-Date) -lt $deadline -and (Get-Process -Id $gamePid -ErrorAction SilentlyContinue)) {
            Start-Sleep -Milliseconds 500
        }
    }
    if (Get-Process -Id $gamePid -ErrorAction SilentlyContinue) {
        Write-Host '  (still running after WM_CLOSE -- killing it, as a crash would)'
        Stop-Process -Id $gamePid -Force -ErrorAction SilentlyContinue
    }

    # After the game is gone the record must be gone too, or the next launch would
    # be refused for a game that no longer exists.
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and (Test-Path -LiteralPath $stateFile)) { Start-Sleep -Milliseconds 500 }
    Check 'run record cleared after exit' (-not (Test-Path -LiteralPath $stateFile))
    Check 'game process gone' (-not [bool](Get-Process -Id $gamePid -ErrorAction SilentlyContinue)) ("pid=$gamePid")

    if (Test-Path -LiteralPath $managerLog) {
        $log = [System.IO.File]::ReadAllText($managerLog)
        Check 'manager log has launch line' ($log -match 'launch pid=' + $gamePid)
        Check 'manager log has exit line' ($log -match ('exit pid=' + $gamePid + ' code='))
        Write-Host ''
        Write-Host '--- zfr_manager.log ---'
        ($log -split "`r?`n") | Where-Object { $_.Trim() } | ForEach-Object { "  $_" }
    } else {
        Check 'manager log written' $false
    }
} finally {
    if ($manager -and -not $manager.HasExited) { Stop-Process -Id $manager.Id -Force -ErrorAction SilentlyContinue }
    if ($gamePid -ne 0) { Stop-Process -Id $gamePid -Force -ErrorAction SilentlyContinue }
    if (-not $KeepTemp -and (Test-Path -LiteralPath $work)) {
        Start-Sleep -Milliseconds 500
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    } elseif ($KeepTemp) {
        Write-Host "kept: $work"
    }
}

Write-Host ''
Write-Host ("PROBE: " + $(if ($failures -eq 0) { 'PASS' } else { "FAIL ($failures)" }))
exit $(if ($failures -eq 0) { 0 } else { 1 })
