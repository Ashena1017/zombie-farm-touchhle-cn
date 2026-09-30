# Launch the game, let it settle, and screenshot its window, to see what state it
# is stuck in. ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$WaitSeconds = 60,
    [string]$Shot = "$root\_analysis\perf\game_window.png"
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
Add-Type -AssemblyName System.Drawing

$src = @'
using System;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
Add-Type -TypeDefinition $src -ErrorAction SilentlyContinue

$hle = Join-Path $hleRoot 'touchHLE_fork.exe'
$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$snap = Join-Path $env:TEMP ('zfrs_' + [Guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force

$env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:ComSpec
$psi.Arguments = '/c ""{0}" "{1}" --landscape-right"' -f $hle, $ipa
# MUST be touchHLE's own folder: it resolves touchHLE_dylibs/ etc. against the
# CURRENT DIRECTORY (src/paths.rs), not the executable's location.
$psi.WorkingDirectory = $hleRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$proc = [System.Diagnostics.Process]::Start($psi)
Write-Host "started; waiting $WaitSeconds s"
Start-Sleep -Seconds $WaitSeconds

$p = Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) { Write-Host 'game process not running'; }
else {
    Write-Host ("window title: '{0}' handle={1}" -f $p.MainWindowTitle, $p.MainWindowHandle)
    if ($p.MainWindowHandle -ne 0) {
        # HWND_TOPMOST = -1, SWP_NOSIZE|SWP_SHOWWINDOW = 0x0041
        [void][Win]::ShowWindow($p.MainWindowHandle, 5)
        [void][Win]::SetWindowPos($p.MainWindowHandle, [IntPtr](-1), 0, 0, 0, 0, 0x0041)
        [void][Win]::SetForegroundWindow($p.MainWindowHandle)
        Start-Sleep -Seconds 3
        $r = New-Object Win+RECT
        [void][Win]::GetWindowRect($p.MainWindowHandle, [ref]$r)
        $w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
        Write-Host "rect: $($r.Left),$($r.Top) ${w}x${h}"
        if ($w -gt 0 -and $h -gt 0) {
            $bmp = New-Object System.Drawing.Bitmap $w, $h
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
            $bmp.Save($Shot, [System.Drawing.Imaging.ImageFormat]::Png)
            $g.Dispose(); $bmp.Dispose()
            Write-Host "saved $Shot"
        }
    }
}

$log = Join-Path $hleRoot 'touchHLE_log.txt'
if (Test-Path -LiteralPath $log) {
    Copy-Item -LiteralPath $log -Destination (Join-Path $Root '_analysis\perf\game_window.touchhle.log') -Force
    Write-Host ("touchHLE_log.txt: {0} bytes" -f (Get-Item -LiteralPath $log).Length)
}

Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
Write-Host 'restored'
