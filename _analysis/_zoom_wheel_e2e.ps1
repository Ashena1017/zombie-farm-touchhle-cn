# Drive the fork build's mouse-wheel zoom end to end: launch the game, wait for
# the farm, screenshot, post WM_MOUSEWHEEL notches, screenshot again, and pull
# the "ZombieFarm zoom:" lines out of touchHLE_log.txt. ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$WaitSeconds = 80,
    [int]$UpNotches = 6,
    [int]$DownNotches = 12,
    # Client-area position of the title screen's "开始游戏" button. The window is
    # 1024x768 client inside a 1040x807 frame (8px borders, 31px title bar), and
    # the button sits near (770, 690) in window coords.
    [int]$TitleButtonX = 762,
    [int]$TitleButtonY = 659,
    [string]$Ipa = 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing

$src = @'
using System;
using System.Runtime.InteropServices;
public class ZWin {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, IntPtr extra);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
'@
Add-Type -TypeDefinition $src -ErrorAction SilentlyContinue

$hleRoot = if (Test-Path -LiteralPath (Join-Path $Root 'touchHLE\touchHLE.exe')) { Join-Path $Root 'touchHLE' } else { $Root }
$hle     = Join-Path $hleRoot 'touchHLE_fork.exe'
$ipaPath = Join-Path $Root ('zombie_farm_ipa\' + $Ipa)
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$log     = Join-Path $hleRoot 'touchHLE_log.txt'
$outDir  = Join-Path $Root '_analysis\perf'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$snap = Join-Path $env:TEMP ('zrz_' + [Guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force
Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue

function Shot([string]$path, $hwnd) {
    $r = New-Object ZWin+RECT
    [void][ZWin]::GetWindowRect($hwnd, [ref]$r)
    $w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
    if ($w -le 0 -or $h -le 0) { Write-Host 'bad window rect'; return }
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Host ("saved {0} ({1}x{2})" -f $path, $w, $h)
}

function Wheel($hwnd, [int]$notches) {
    $r = New-Object ZWin+RECT
    [void][ZWin]::GetWindowRect($hwnd, [ref]$r)
    $lx = [int](($r.Left + $r.Right) / 2) -band 0xFFFF
    $ly = [int](($r.Top + $r.Bottom) / 2) -band 0xFFFF
    $lp = [IntPtr]([int64](($ly * 65536) + $lx))
    $step = if ($notches -gt 0) { 1 } else { -1 }
    for ($i = 0; $i -lt [Math]::Abs($notches); $i++) {
        $d = 120 * $step
        if ($d -lt 0) { $d += 65536 }
        $wp = [IntPtr]([int64]($d * 65536))
        [void][ZWin]::PostMessage($hwnd, 0x020A, $wp, $lp)
        Start-Sleep -Milliseconds 120
    }
    Write-Host ("posted {0} wheel notch(es)" -f $notches)
}

# Click at client coords, so the game leaves its title screen and loads the farm.
function ClickClient($hwnd, [int]$x, [int]$y) {
    [void][ZWin]::ShowWindow($hwnd, 5)
    [void][ZWin]::SetWindowPos($hwnd, [IntPtr](-1), 0, 0, 0, 0, 0x0041)
    [void][ZWin]::SetForegroundWindow($hwnd)
    Start-Sleep -Seconds 1
    $pt = New-Object ZWin+POINT
    $pt.X = $x; $pt.Y = $y
    [void][ZWin]::ClientToScreen($hwnd, [ref]$pt)
    Write-Host ("clicking client ({0},{1}) -> screen ({2},{3})" -f $x, $y, $pt.X, $pt.Y)
    [void][ZWin]::SetCursorPos($pt.X, $pt.Y)
    Start-Sleep -Milliseconds 400
    [ZWin]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)   # LEFTDOWN
    Start-Sleep -Milliseconds 150
    [ZWin]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)   # LEFTUP
    Start-Sleep -Milliseconds 600
}

$proc = $null
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = '/c ""{0}" "{1}" --landscape-right"' -f $hle, $ipaPath
    $psi.WorkingDirectory = $hleRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    Write-Host "started; waiting up to $WaitSeconds s for the farm"

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    $p = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        $p = Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue |
             Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
        if ($p) { break }
    }
    # let the farm finish loading and settle
    Start-Sleep -Seconds 15

    if (-not $p) {
        Write-Host 'FAIL: no touchHLE window appeared'
    } else {
        $hw = $p.MainWindowHandle
        Write-Host ("window '{0}' hwnd={1}" -f $p.MainWindowTitle, $hw)
        [void][ZWin]::ShowWindow($hw, 5)
        [void][ZWin]::SetWindowPos($hw, [IntPtr](-1), 0, 0, 0, 0, 0x0041)
        [void][ZWin]::SetForegroundWindow($hw)
        Start-Sleep -Seconds 3

        Shot (Join-Path $outDir 'zoom_00_title.png') $hw

        # The game boots to its title screen; the farm (and therefore
        # ZFFarmTileMap) only exists after "开始游戏" is pressed. Click it, then
        # give the farm time to load and settle.
        ClickClient $hw $TitleButtonX $TitleButtonY
        Start-Sleep -Seconds 8
        Shot (Join-Path $outDir 'zoom_01_farm.png') $hw

        Shot (Join-Path $outDir 'zoom_before.png') $hw
        Wheel $hw $UpNotches
        Start-Sleep -Seconds 2
        Shot (Join-Path $outDir 'zoom_after_up.png') $hw
        Wheel $hw (-$DownNotches)
        Start-Sleep -Seconds 2
        Shot (Join-Path $outDir 'zoom_after_down.png') $hw
    }
} finally {
    Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if ($proc) { Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 4
}

Write-Host ''
Write-Host '=== ZombieFarm zoom log lines ==='
if (Test-Path -LiteralPath $log) {
    Copy-Item -LiteralPath $log -Destination (Join-Path $outDir 'zoom.touchhle.log') -Force
    $hits = Select-String -LiteralPath $log -Pattern 'ZombieFarm zoom'
    if ($hits) { $hits | ForEach-Object { $_.Line } } else { Write-Host '(no zoom lines)' }
} else { Write-Host '(no log file)' }

Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'restored sandbox'
