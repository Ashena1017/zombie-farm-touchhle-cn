# v28fix A/B: does the IPA-side fix remove the dangling observers at the source?
#
# The emulator-side workaround (stale-observer pruning) masks the bug, so it
# cannot be used to prove the IPA fix works.  This harness therefore DISABLES the
# pruning (TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE=1) and drives the real
# game:
#
#   1. launch the given IPA,
#   2. tap "Start Game" on the splash screen,
#   3. once the quest system is listening, run the complete-all-quests cheat
#      (which calls cleanupQuest: -> stopListening and frees the requirements),
#   4. post the quest notifications.
#
# Expected, with pruning OFF:
#   v27fix  -> PANIC  `does not respond to selector "incrementCount:"`
#              (stopListening never unregistered the requirement objects)
#   v28fix  -> NO PANIC (stopListening unregisters them, so no dangling entry)
#
# The stale audit is enabled so the observer table can be compared directly.
#
# The sandbox is snapshotted and restored, so the player's save is untouched.
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Ipa = 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa',
    [string]$Tag = 'v28',
    [int]$Seconds = 330,
    [int]$ClickAfter = 70,
    [int]$ClickX = 654,
    [int]$ClickY = 511,
    [int]$CompleteAfter = 120,
    [int]$PostAfter = 45,
    [string]$PostNames = 'kCropPlantedNotification,kSoilPlowedNotification,kItemBoughtNotification,kInvasionSuccessfulNotification',
    [switch]$WithPrune,
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

$ipaPath = if ([System.IO.Path]::IsPathRooted($Ipa)) { $Ipa } else { Join-Path $Root ('zombie_farm_ipa\' + $Ipa) }
$hle = Join-Path $hleRoot 'touchHLE_fork.exe'
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$perfDir = Join-Path $Root '_analysis\perf'
$outLog = Join-Path $perfDir ("v28ab_$Tag.out.log")

foreach ($f in @($ipaPath, $hle, $sandbox)) {
    if (-not (Test-Path -LiteralPath $f)) { Write-Host "FAIL: missing $f"; exit 1 }
}
if (-not (Test-Path -LiteralPath $perfDir)) { New-Item -ItemType Directory -Path $perfDir -Force | Out-Null }

$snap = Join-Path $env:TEMP ('zfr28_' + [Guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force
Remove-Item -LiteralPath $outLog -Force -ErrorAction SilentlyContinue

$env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
$env:TOUCHHLE_NSNOTIFICATIONCENTER_STALE_AUDIT = '15'
$env:TOUCHHLE_ZFR_DEBUG_COMPLETE_QUESTS_AFTER = "$CompleteAfter"
$env:TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION = $PostNames
$env:TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION_AFTER = "$PostAfter"
if ($WithPrune) {
    Remove-Item Env:TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE -ErrorAction SilentlyContinue
} else {
    $env:TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE = '1'
}

Write-Host "=== v28fix A/B: $Ipa ==="
Write-Host ("pruning: " + $(if ($WithPrune) { 'enabled' } else { 'DISABLED (this is the point of the test)' }))

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:ComSpec
$psi.Arguments = '/c ""{0}" "{1}" --landscape-right > "{2}" 2>&1"' -f $hle, $ipaPath, $outLog
# MUST be touchHLE's own folder: it resolves touchHLE_dylibs/ etc. against the
# CURRENT DIRECTORY (src/paths.rs), not the executable's location.
$psi.WorkingDirectory = $hleRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$proc = [System.Diagnostics.Process]::Start($psi)
$startTime = Get-Date
Write-Host "started cmd pid $($proc.Id); up to $Seconds s"

Add-Type -AssemblyName System.Drawing -ErrorAction SilentlyContinue
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Zfr28Win {
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, IntPtr extra);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
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

function Invoke-GameClick([IntPtr]$hwnd, [int]$x, [int]$y) {
    [void][Zfr28Win]::ShowWindow($hwnd, 5)
    [void][Zfr28Win]::SetWindowPos($hwnd, [IntPtr](-1), 0, 0, 0, 0, 0x0041)
    [void][Zfr28Win]::SetForegroundWindow($hwnd)
    Start-Sleep -Seconds 2
    $pt = New-Object Zfr28Win+POINT
    $pt.X = $x; $pt.Y = $y
    [void][Zfr28Win]::ClientToScreen($hwnd, [ref]$pt)
    Write-Host ("       screen ({0},{1})" -f $pt.X, $pt.Y)
    [void][Zfr28Win]::SetCursorPos($pt.X, $pt.Y)
    Start-Sleep -Milliseconds 400
    [Zfr28Win]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 150
    [Zfr28Win]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
}

function Save-GameShot([IntPtr]$hwnd, [string]$path) {
    $r = New-Object Zfr28Win+RECT
    if (-not [Zfr28Win]::GetWindowRect($hwnd, [ref]$r)) { return }
    $w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
    if ($w -le 0 -or $h -le 0) { return }
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
}

$deadline = (Get-Date).AddSeconds($Seconds)
$clicked = $false
while ((Get-Date) -lt $deadline -and -not $proc.HasExited) {
    Start-Sleep -Seconds 15
    $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
    if (-not $NoClick -and -not $clicked -and $elapsed -ge $ClickAfter) {
        $hwnd = Get-GameWindow
        if ($hwnd -ne [IntPtr]::Zero) {
            Write-Host ("  [{0,4}s] clicking Start Game at client ({1},{2})" -f $elapsed, $ClickX, $ClickY)
            Invoke-GameClick $hwnd $ClickX $ClickY
            $clicked = $true
            Start-Sleep -Seconds 15
            Save-GameShot $hwnd (Join-Path $perfDir ("v28ab_$Tag" + "_clicked.png"))
        } else {
            Write-Host ("  [{0,4}s] no window yet" -f $elapsed)
        }
    }
    $size = 0
    if (Test-Path -LiteralPath $outLog) { $size = (Get-Item -LiteralPath $outLog).Length }
    $last = ''
    try { $last = (Get-Content -LiteralPath $outLog -Tail 1) } catch { }
    Write-Host ("  [{0,4}s] log {1} bytes | {2}" -f $elapsed, $size, $last.Substring(0, [Math]::Min(90, $last.Length)))
}

$hwnd = Get-GameWindow
if ($hwnd -ne [IntPtr]::Zero) {
    [void][Zfr28Win]::SetWindowPos($hwnd, [IntPtr](-1), 0, 0, 0, 0, 0x0041)
    Start-Sleep -Seconds 3
    Save-GameShot $hwnd (Join-Path $perfDir "v28ab_$Tag.png")
}

$exited = $proc.HasExited
if (-not $exited) {
    Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}
Write-Host ("process exited on its own: " + $(if ($exited) { "yes (code $($proc.ExitCode))" } else { 'no (killed after the timeout)' }))

$hleLog = Join-Path $hleRoot 'touchHLE_log.txt'
$text = ''
if (Test-Path -LiteralPath $outLog) { $text = [System.IO.File]::ReadAllText($outLog) }
if (Test-Path -LiteralPath $hleLog) {
    $hleText = [System.IO.File]::ReadAllText($hleLog)
    Copy-Item -LiteralPath $hleLog -Destination (Join-Path $perfDir "v28ab_$Tag.touchhle.log") -Force
    if ($hleText.Length -gt $text.Length) { $text = $hleText }
}
$lines = $text -split "`r?`n"

function Show-Lines([string]$pattern, [int]$max) {
    $hits = @($lines | Select-String -Pattern $pattern)
    Write-Host ("--- {0}: {1} hit(s)" -f $pattern, $hits.Count)
    foreach ($h in ($hits | Select-Object -First $max)) {
        Write-Host ('    ' + $h.Line.Trim().Substring(0, [Math]::Min(160, $h.Line.Trim().Length)))
    }
}
Show-Lines 'stale audit' 10
Show-Lines 'ZombieFarm debug:' 6
Show-Lines 'ZombieFarm cheat:' 8
Show-Lines 'Skipping stale' 6
Show-Lines 'does not respond to selector|panicked at' 6

Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $hleLog -Force -ErrorAction SilentlyContinue
Write-Host 'sandbox restored'

$panicked = ($lines | Select-String -Pattern 'does not respond to selector') -ne $null
$completed = ($lines | Select-String -Pattern 'ZombieFarm debug: completing all quests') -ne $null
$posted = ($lines | Select-String -Pattern 'ZombieFarm debug: posting notifications') -ne $null

Write-Host ''
Write-Host ("quests completed: {0}; notifications posted: {1}; panic: {2}" -f $completed, $posted, $panicked)
if (-not $WithPrune) {
    # With pruning off, the ONLY thing that can prevent the panic is the IPA fix.
    $good = $completed -and $posted -and -not $panicked
    Write-Host ("RESULT: " + $(if ($good) { 'PASS - survived with pruning disabled (no dangling observers)' }
                                 else { 'INCONCLUSIVE/FAIL - see flags above' }))
} else {
    Write-Host ("RESULT: " + $(if (-not $panicked) { 'PASS - no crash (pruning on)' } else { 'FAIL - crashed' }))
}
exit $(if ($good) { 0 } else { 1 })
