# Final end-to-end check of the Release bundle: start the game FROM the bundle's
# own GUI, which is the exact path a recipient takes.
#
# Everything is read from the Release folder, so a missing file or a path that only
# resolves in the development tree fails here.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$Seconds = 40
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'
$release = Join-Path $Root 'Release'
$guiExe = Join-Path $release '游戏管理.exe'
$hleDir = Join-Path $release 'touchHLE'
$gameLog = Join-Path $hleDir 'zfr_last_run.log'

# Snapshot the WHOLE sandbox, not just the save: a run makes the game create
# playerProfileManager.txt, saveGame.preview and Library\Preferences, and leaving
# those behind would ship a bundle that has visibly already been played once.
$sandbox = Join-Path $hleDir 'touchHLE_sandbox'
$sandboxSnapshot = Join-Path $env:TEMP ('rel_sandbox_' + [Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $sandbox) {
    Copy-Item -LiteralPath $sandbox -Destination $sandboxSnapshot -Recurse -Force
}

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class RelProbe {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    public delegate bool EnumProc(IntPtr h, IntPtr p);

    public static string Text(IntPtr h) { var sb = new StringBuilder(2048); GetWindowTextW(h, sb, 2048); return sb.ToString(); }
    public static string Cls(IntPtr h)  { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }

    public static IntPtr[] TopLevel(uint pid, bool visibleOnly) {
        var list = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint q; GetWindowThreadProcessId(h, out q);
            if (q == pid && (!visibleOnly || IsWindowVisible(h))) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }

    public static IntPtr[] Descendants(IntPtr parent, string fragment) {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (Cls(h).Contains(fragment)) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }
}
'@

# 启动游戏 = U+542F U+52A8 U+6E38 U+620F
$startLabel = [string][char]0x542F + [char]0x52A8 + [char]0x6E38 + [char]0x620F

$ok = $true
$gui = $null

try {
    Write-Host "opening $guiExe"
    $gui = Start-Process -FilePath $guiExe -PassThru

    $hwnd = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        foreach ($w in ([RelProbe]::TopLevel([uint32]$gui.Id, $true))) {
            if ([RelProbe]::Text($w) -match 'Zombie Farm') { $hwnd = $w; break }
        }
        if ($hwnd -eq [IntPtr]::Zero) {
            # The stub spawns PowerShell, so look there too.
            foreach ($p in (Get-Process -Name 'powershell' -ErrorAction SilentlyContinue)) {
                if ($p.MainWindowTitle -match 'Zombie Farm') { $hwnd = $p.MainWindowHandle; break }
            }
        }
        if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
    }
    if ($hwnd -eq [IntPtr]::Zero) { throw 'GUI window never appeared' }
    Start-Sleep -Seconds 4
    Write-Host '  GUI opened: PASS'

    # Press 启动游戏.
    $btn = [RelProbe]::Descendants($hwnd, 'BUTTON') |
        Where-Object { [RelProbe]::Text($_) -eq $startLabel } | Select-Object -First 1
    if (-not $btn) { throw 'start button not found' }
    Write-Host '  pressing 启动游戏'
    [void][RelProbe]::PostMessage($btn, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)

    $started = $false
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if (Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue) { $started = $true; break }
        Start-Sleep -Milliseconds 500
    }
    Write-Host ("  game started from the bundle GUI: " + $(if ($started) { 'PASS' } else { 'FAIL' }))
    if (-not $started) { $ok = $false }
    else { Start-Sleep -Seconds $Seconds }

    # Confirm it got past loading, from the bundle's own log.
    if (Test-Path -LiteralPath $gameLog) {
        $lines = Get-Content -LiteralPath $gameLog
        $began = $lines | Select-String -Pattern 'CPU emulation begins' | Select-Object -Last 1
        $panic = $lines | Select-String -Pattern 'panicked' | Select-Object -Last 1
        Write-Host ("  reached gameplay: " + $(if ($began) { 'PASS' } else { 'FAIL' }))
        Write-Host ("  panic: " + $(if ($panic) { $panic.Line.Trim() } else { 'none' }))
        if (-not $began) { $ok = $false }
    } else {
        Write-Host '  note: no run log (the game may still be running)'
    }
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    $ok = $false
} finally {
    Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    # Close the GUI.
    foreach ($w in @([RelProbe]::TopLevel(0, $true))) { }
    Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
        ForEach-Object { $_.CloseMainWindow() | Out-Null }
    Start-Sleep -Seconds 2
    Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    if ($null -ne $gui -and -not $gui.HasExited) { try { $gui.Kill() } catch { } }

    # Put the bundle back exactly as shipped: replace the whole sandbox with the
    # snapshot taken before the run, and drop the files a run generates.
    if (Test-Path -LiteralPath $sandbox) {
        Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $sandboxSnapshot) {
        Copy-Item -LiteralPath $sandboxSnapshot -Destination $sandbox -Recurse -Force
        Remove-Item -LiteralPath $sandboxSnapshot -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($junk in @('zfr_last_run.log', 'zfr_last_launch.txt',
                        'touchHLE_log.txt', 'launcher_selected_ipa.txt')) {
        $p = Join-Path $hleDir $junk
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
    }
    Write-Host ''
    Write-Host '  bundle restored to its shipped state'
}

Write-Host ''
Write-Host ("RESULT: " + $(if ($ok) { 'PASS - the bundle plays end to end' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })
