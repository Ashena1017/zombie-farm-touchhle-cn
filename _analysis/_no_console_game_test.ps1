# Verify that launching the GAME from the GUI produces no console window either.
#
# 游戏管理.exe itself is a GUI-subsystem binary (verified separately), but
# touchHLE.exe is a CONSOLE-subsystem program: if it were started normally from a
# process with no console, Windows would allocate a fresh console window for it --
# bringing back the black window this UI exists to avoid. The launcher's -Quiet
# path uses CreateNoWindow to prevent that, and this proves it works.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$BootSeconds = 30,
    [int]$PlaySeconds = 15
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

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class WinCount {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    public delegate bool EnumProc(IntPtr h, IntPtr p);

    public static string Cls(IntPtr h) { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }
    public static string Txt(IntPtr h) { var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512); return sb.ToString(); }

    public static int ConsoleWindows() {
        var list = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            if (IsWindowVisible(h) && Cls(h).Contains("ConsoleWindowClass")) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.Count;
    }

    public static IntPtr FindTopLevel(uint pid, string titlePart) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint wpid; GetWindowThreadProcessId(h, out wpid);
            if (wpid == pid && IsWindowVisible(h) && Txt(h).Contains(titlePart)) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@

# Identify the launcher without embedding its Chinese filename.
$launcher = Get-ChildItem -LiteralPath $Root -Filter '*.exe' -File |
    Where-Object { $_.Name -notmatch '^touchHLE' } |
    Sort-Object Length | Select-Object -First 1
if (-not $launcher) { Write-Host '  FAIL: launcher not found'; exit 1 }

Write-Host "  launcher: $($launcher.Name)"
Write-Host "  consoles before: $([WinCount]::ConsoleWindows())"

$proc = Start-Process -FilePath $launcher.FullName -PassThru

$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds(40)
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
    $hwnd = [WinCount]::FindTopLevel([uint32]$proc.Id, 'Zombie Farm')
    if ($hwnd -eq [IntPtr]::Zero) {
        foreach ($p in (Get-Process -Name 'powershell' -ErrorAction SilentlyContinue)) {
            if ($p.MainWindowTitle -match 'Zombie Farm') { $hwnd = $p.MainWindowHandle; break }
        }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}
if ($hwnd -eq [IntPtr]::Zero) { Write-Host '  FAIL: manager window did not appear'; exit 1 }
Start-Sleep -Seconds 3

$peak = $null
$consoleBefore = [WinCount]::ConsoleWindows()

# Press the start button by clicking it. Its position is fixed by layout: the first
# button in the game tab, around (130, 60) in client coordinates.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Click {
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
}
'@

# Find the start button by its text via the child enumeration.
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class BtnFind {
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    public static string Cls(IntPtr h) { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }
    public static string Txt(IntPtr h) { var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512); return sb.ToString(); }
    public static IntPtr[] Buttons(IntPtr parent) {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (Cls(h).Contains("BUTTON")) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }
}
'@

# The three launch-tab buttons are: 启动游戏, 启动并跳过时间…, 还原参考存档.
# Rather than match Chinese text, drive the first one via the keyboard: focus it
# and press Space. Simpler and language-independent is to click by coordinates.
# Use BM_CLICK instead: it activates the button without needing geometry.
$buttons = [BtnFind]::Buttons($hwnd)
Write-Host "  buttons found: $($buttons.Count)"
if ($buttons.Count -eq 0) { Write-Host '  FAIL: no buttons'; exit 1 }

# Send BM_CLICK (0x00F5) to each button until the game process starts.
$started = $false
foreach ($b in ($buttons | Select-Object -First 1)) {
    [void][Click]::PostMessage($b, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
    Start-Sleep -Seconds 2
    if (Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue) { $started = $true; break }
    $t = [BtnFind]::Txt($b)
    Write-Host "    clicked '$t' - game not running yet"
}

if (-not $started) {
    Write-Host '  FAIL: could not start the game from the GUI'
    [void][Click]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    Start-Sleep -Seconds 2
    try { $proc.Kill() } catch { }
    exit 1
}

# Poll for console windows while the game boots and runs.
$maxConsoles = 0
for ($i = 0; $i -lt ($BootSeconds + $PlaySeconds); $i++) {
    Start-Sleep -Seconds 1
    $c = [WinCount]::ConsoleWindows()
    if ($c -gt $maxConsoles) { $maxConsoles = $c }
    if ($i -eq $BootSeconds) {
        $game = Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue
        Write-Host "  game running after ${BootSeconds}s: $([bool]$game)"
    }
}

Write-Host "  consoles before: $consoleBefore   peak during game: $maxConsoles"

$ok = $true
if ($maxConsoles -gt $consoleBefore) {
    Write-Host '  FAIL: a console window appeared while the game was running' -ForegroundColor Red
    $ok = $false
} else {
    Write-Host '  => no console window appeared while playing' -ForegroundColor Green
}

# Also confirm a log was written, proving -Quiet captured touchHLE's output.
$log = Join-Path $hleRoot 'zfr_last_run.log'
if (Test-Path -LiteralPath $log) {
    Write-Host "  run log written: $((Get-Item -LiteralPath $log).Length) bytes"
} else {
    Write-Host '  note: no run log yet (game may still be running)'
}

# Clean up.
Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
[void][Click]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Seconds 2
Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
if (-not $proc.HasExited) { try { $proc.Kill() } catch { } }

Write-Host ''
Write-Host ("RESULT: " + $(if ($ok) { 'PASS - no black window while playing' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })
