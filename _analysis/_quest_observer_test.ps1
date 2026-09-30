# Reproduce (and verify the fix for) the Zombie Farm quest-notification crash.
#
# Background: the v10/v11 IPA patches rewrote -[ZFQuestNotification stopListening]
# so that it no longer unregisters the per-requirement observers that
# -startListening adds for "incrementCount:". Those observers are held by
# NSNotificationCenter WITHOUT a retain, so once a ZFQuestRequirement is
# deallocated the registration is a dangling guest pointer; posting its
# notification then sends "incrementCount:" to whatever object now lives at that
# address (usually an NSString), which aborts emulation.
#
# This script drives the real game:
#   1. it launches the bundled IPA with the debug build,
#   2. after N seconds (and once the quest system has registered its
#      incrementCount: observers) it runs the complete-all-quests cheat, which
#      clears quests and frees their requirements,
#   3. a bit later it posts the quest notification names on the default center.
#
# With pruning disabled (TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE=1) step 3
# must panic with `... does not respond to selector "incrementCount:"`; with the
# fix it must log "Skipping stale NSNotificationCenter observer" instead.
#
# The sandbox is snapshotted and restored, so the player's save is untouched.
#
# The game stops at its splash screen until "Start Game" is tapped, so the
# harness injects a click into the game window (client coordinates).
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Tag = 'A',
    [int]$Seconds = 300,
    [int]$ClickAfter = 60,
    [int]$ClickX = 654,
    [int]$ClickY = 511,
    [int]$CompleteAfter = 150,
    [int]$PostAfter = 45,
    [string]$PostNames = 'kCropPlantedNotification,kSoilPlowedNotification,kItemBoughtNotification,kInvasionSuccessfulNotification',
    [switch]$NoPrune,
    [switch]$NoClick
)
$root = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}


$ErrorActionPreference = 'Continue'

$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'
$hle = Join-Path $hleRoot 'touchHLE_fork.exe'
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$outLog = Join-Path $Root ("_analysis\perf\quest_obs_$Tag.out.log")
$errLog = Join-Path $Root ("_analysis\perf\quest_obs_$Tag.err.log")

foreach ($f in @($ipa, $hle, $sandbox)) {
    if (-not (Test-Path -LiteralPath $f)) { Write-Host "FAIL: missing $f"; exit 1 }
}

# --- snapshot the save ------------------------------------------------------
$snap = Join-Path $env:TEMP ('zfrq_' + [Guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force
Write-Host "sandbox snapshotted to $snap"

Remove-Item -LiteralPath $outLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $errLog -Force -ErrorAction SilentlyContinue

# --- environment ------------------------------------------------------------
$env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
$env:TOUCHHLE_NSNOTIFICATIONCENTER_STALE_AUDIT = '15'
$env:TOUCHHLE_ZFR_DEBUG_COMPLETE_QUESTS_AFTER = "$CompleteAfter"
$env:TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION = $PostNames
$env:TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION_AFTER = "$PostAfter"
if ($NoPrune) {
    $env:TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE = '1'
} else {
    Remove-Item Env:TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE -ErrorAction SilentlyContinue
}
Write-Host ("pruning: " + $(if ($NoPrune) { 'DISABLED (expect a panic)' } else { 'enabled (expect cleanup)' }))
Write-Host ("complete quests after {0}s, post notifications after {1}s" -f $CompleteAfter, $PostAfter)

# --- run --------------------------------------------------------------------
# NOTE: Start-Process cannot be used here: this machine's environment has both
# NO_PROXY and no_proxy, and PowerShell's environment provider throws
# "An item with the same key has already been added" when it rebuilds the child
# environment. ProcessStartInfo passes the real environment block through
# instead, and cmd.exe's redirection gives us a log file rather than a pipe
# (an unread 64 KiB pipe would block the emulator).
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:ComSpec
$psi.Arguments = '/c ""{0}" "{1}" --landscape-right > "{2}" 2>&1"' -f $hle, $ipa, $outLog
# MUST be touchHLE's own folder: it resolves touchHLE_dylibs/ etc. against the
# CURRENT DIRECTORY (src/paths.rs), not the executable's location.
$psi.WorkingDirectory = $hleRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$proc = [System.Diagnostics.Process]::Start($psi)
$startTime = Get-Date
Write-Host "started cmd pid $($proc.Id); running for up to $Seconds s"

# --- input ------------------------------------------------------------------
# The splash screen's "Start Game" button needs a tap before anything happens.
Add-Type -AssemblyName System.Drawing -ErrorAction SilentlyContinue
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class ZfrWin {
    [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, IntPtr extra);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
'@ -ErrorAction SilentlyContinue

function Get-GameWindow {
    $p = Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($p) { return $p.MainWindowHandle }
    return [IntPtr]::Zero
}

# SDL ignores synthesised mouse messages unless the window is the active mouse
# target, so this is a real click: the window is raised and the actual cursor is
# moved and clicked at the button.
function Invoke-GameClick([IntPtr]$hwnd, [int]$x, [int]$y) {
    [void][ZfrWin]::ShowWindow($hwnd, 5)
    [void][ZfrWin]::SetWindowPos($hwnd, [IntPtr](-1), 0, 0, 0, 0, 0x0041)  # TOPMOST, keep size
    [void][ZfrWin]::SetForegroundWindow($hwnd)
    Start-Sleep -Seconds 2
    $pt = New-Object ZfrWin+POINT
    $pt.X = $x; $pt.Y = $y
    [void][ZfrWin]::ClientToScreen($hwnd, [ref]$pt)
    Write-Host ("       screen position ({0},{1})" -f $pt.X, $pt.Y)
    [void][ZfrWin]::SetCursorPos($pt.X, $pt.Y)
    Start-Sleep -Milliseconds 400
    [ZfrWin]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)   # LEFTDOWN
    Start-Sleep -Milliseconds 150
    [ZfrWin]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)   # LEFTUP
}

function Save-GameShot([IntPtr]$hwnd, [string]$path) {
    $r = New-Object ZfrWin+RECT
    if (-not [ZfrWin]::GetWindowRect($hwnd, [ref]$r)) { return }
    $w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
    if ($w -le 0 -or $h -le 0) { return }
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
}

$deadline = (Get-Date).AddSeconds($Seconds)
$lastSize = -1
$clicked = $false
while ((Get-Date) -lt $deadline -and -not $proc.HasExited) {
    Start-Sleep -Seconds 15
    $elapsedNow = [int]((Get-Date) - $startTime).TotalSeconds
    if (-not $NoClick -and -not $clicked -and $elapsedNow -ge $ClickAfter) {
        $hwnd = Get-GameWindow
        if ($hwnd -ne [IntPtr]::Zero) {
            Write-Host ("  [{0,4}s] clicking Start Game at client ({1},{2})" -f $elapsedNow, $ClickX, $ClickY)
            Invoke-GameClick $hwnd $ClickX $ClickY
            $clicked = $true
            Start-Sleep -Seconds 20
            Save-GameShot $hwnd (Join-Path $Root ("_analysis\perf\quest_obs_$Tag" + "_afterclick.png"))
            Write-Host ("  [{0,4}s] screenshot after the click saved" -f [int]((Get-Date) - $startTime).TotalSeconds)
        } else {
            Write-Host ("  [{0,4}s] no game window yet for the start click" -f $elapsedNow)
        }
    }
    $size = 0
    if (Test-Path -LiteralPath $outLog) { $size = (Get-Item -LiteralPath $outLog).Length }
    if ($size -ne $lastSize) {
        $last = ''
        try { $last = (Get-Content -LiteralPath $outLog -Tail 1) } catch { }
        Write-Host ("  [{0,4}s] log {1} bytes | {2}" -f $elapsedNow, $size, $last)
        $lastSize = $size
    }
}

# A screenshot after the run, to see how far the game got (window is moved to the
# top first so the capture is not hidden behind other windows).
$hwnd = Get-GameWindow
if ($hwnd -ne [IntPtr]::Zero) {
    [void][ZfrWin]::SetWindowPos($hwnd, [IntPtr](-1), 0, 0, 0, 0, 0x0041)
    Start-Sleep -Seconds 3
    Save-GameShot $hwnd (Join-Path $Root ("_analysis\perf\quest_obs_$Tag.png"))
    Write-Host ("  screenshot: _analysis\perf\quest_obs_$Tag.png")
}

$exited = $proc.HasExited
if (-not $exited) {
    Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}
Write-Host ("process exited on its own: " + $(if ($exited) { "yes (code $($proc.ExitCode))" } else { 'no (killed after the timeout)' }))

# --- report -----------------------------------------------------------------
# touchHLE writes the same output to its own touchHLE_log.txt (src/log.rs), which
# is written with an unbuffered handle, so prefer it when it is longer.
$hleLog = Join-Path $hleRoot 'touchHLE_log.txt'
$text = ''
if (Test-Path -LiteralPath $outLog) { $text = [System.IO.File]::ReadAllText($outLog) }
if (Test-Path -LiteralPath $hleLog) {
    $hleText = [System.IO.File]::ReadAllText($hleLog)
    Copy-Item -LiteralPath $hleLog -Destination (Join-Path $Root ("_analysis\perf\quest_obs_$Tag.touchhle.log")) -Force
    if ($hleText.Length -gt $text.Length) { $text = $hleText }
}
$lines = $text -split "`r?`n"
Write-Host ("log lines: " + $lines.Count)

function Show-Lines([string]$pattern, [int]$max) {
    $hits = @($lines | Select-String -Pattern $pattern)
    Write-Host ("--- {0}: {1} hit(s)" -f $pattern, $hits.Count)
    foreach ($h in ($hits | Select-Object -First $max)) { Write-Host ("    " + $h.Line.Trim()) }
}

Show-Lines 'stale audit' 8
Show-Lines 'Skipping stale' 12
Show-Lines 'ZombieFarm debug:' 6
Show-Lines 'ZombieFarm cheat:' 8
Show-Lines 'panicked|does not respond to selector|panic' 8

# --- restore ----------------------------------------------------------------
Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
foreach ($junk in @('touchHLE_log.txt', 'zombie_farm_crash_snapshot.txt')) {
    $jp = Join-Path $Root $junk
    if (Test-Path -LiteralPath $jp) { Remove-Item -LiteralPath $jp -Force -ErrorAction SilentlyContinue }
}
Write-Host 'sandbox restored'

$panicked = ($lines | Select-String -Pattern 'does not respond to selector') -ne $null
if ($NoPrune) {
    Write-Host ("RESULT: " + $(if ($panicked) { 'PASS - reproduced the crash (pruning off)' } else { 'INCONCLUSIVE - no panic' }))
    exit $(if ($panicked) { 0 } else { 1 })
} else {
    $cleaned = ($lines | Select-String -Pattern 'Skipping stale NSNotificationCenter observer') -ne $null
    $allClear = -not $panicked
    Write-Host ("RESULT: " + $(if ($allClear) { 'PASS - no crash' } else { 'FAIL - still crashed' }) + $(if ($cleaned) { ' (stale observer(s) cleaned up)' } else { ' (no stale observer seen)' }))
    exit $(if ($allClear) { 0 } else { 1 })
}
