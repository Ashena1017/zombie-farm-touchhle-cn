# Prove GameManager.ps1 no longer depends on the other two scripts, by driving the
# REAL UI with those files renamed away.
#
# The -SelfTest audit already showed the self-test path needs nothing, but that
# path does not press buttons. This test opens the actual window, launches the game
# from it, and writes currency from it -- with the helpers absent -- so the claims
# cover the real code paths a user takes.
#
# Renaming rather than copying: a copy would leave the original in place and prove
# nothing. Everything is restored in a finally block.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$TimeoutSeconds = 45,
    [int]$GameSeconds = 30
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

$manager = Join-Path $Root 'GameManager.ps1'
$helpers = @('StartZombieFarmNextHour.ps1', 'SetZombieFarmCurrency.ps1')
$docs = Join-Path $hleRoot 'touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents'
$live = Join-Path $docs 'saveGame.bin2'
$safe = Join-Path $Root '_analysis\save_backups_safe'

# --- safety copy of every backup, and the live save -------------------------
if (Test-Path -LiteralPath $safe) { Remove-Item -LiteralPath $safe -Recurse -Force }
New-Item -ItemType Directory -Force -Path $safe | Out-Null
Copy-Item -LiteralPath $live -Destination (Join-Path $safe 'saveGame.bin2') -Force
Get-ChildItem $docs -Filter 'saveGame.bin2.bak*' -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $safe -Force
}
$liveHashBefore = (Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash
Write-Host "safety copy: $((Get-ChildItem $safe -File | Measure-Object).Count) file(s)"

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class NoDep {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public static string Text(IntPtr h) { var sb = new StringBuilder(4096); GetWindowTextW(h, sb, 4096); return sb.ToString(); }
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

# Chinese labels from code points (file stays ASCII).
#   启动游戏 = U+542F U+52A8 U+6E38 U+620F
#   写入存档 = U+5199 U+5165 U+5B58 U+6863
#   知道了   = U+77E5 U+9053 U+4E86
$startLabel  = [string][char]0x542F + [char]0x52A8 + [char]0x6E38 + [char]0x620F
$applyLabel  = [string][char]0x5199 + [char]0x5165 + [char]0x5B58 + [char]0x6863
$okLabel     = [string][char]0x77E5 + [char]0x9053 + [char]0x4E86

$renamed = @()
$ok = $true
$gui = $null
$hwnd = [IntPtr]::Zero

try {
    # --- hide the helpers ---------------------------------------------------
    foreach ($h in $helpers) {
        $p = Join-Path $Root $h
        if (Test-Path -LiteralPath $p) {
            Move-Item -LiteralPath $p -Destination "$p.hidden" -Force
            $renamed += $h
            Write-Host "hidden: $h"
        }
    }
    if ($renamed.Count -ne $helpers.Count) { throw 'could not hide every helper' }

    # --- open the GUI -------------------------------------------------------
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' + $manager + '"'
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $gui = [System.Diagnostics.Process]::Start($psi)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        foreach ($w in ([NoDep]::TopLevel([uint32]$gui.Id, $true))) {
            if ([NoDep]::Text($w) -match 'Zombie Farm') { $hwnd = $w; break }
        }
        if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
    }
    if ($hwnd -eq [IntPtr]::Zero) { throw 'GUI window never appeared' }
    Start-Sleep -Seconds 3
    Write-Host 'GUI opened with helpers absent: PASS'
    Write-Host ''

    # --- 1. launch the game from the GUI ------------------------------------
    Write-Host '--- pressing 启动游戏 ---'
    $btnStart = [NoDep]::Descendants($hwnd, 'BUTTON') |
        Where-Object { [NoDep]::Text($_) -eq $startLabel } | Select-Object -First 1
    if (-not $btnStart) { throw 'start button not found' }

    # PostMessage, not SendMessage: the handler blocks until the game exits.
    [void][NoDep]::PostMessage($btnStart, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)

    $started = $false
    $deadline = (Get-Date).AddSeconds(25)
    while ((Get-Date) -lt $deadline) {
        if (Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue) { $started = $true; break }
        Start-Sleep -Milliseconds 500
    }
    Write-Host ("  game process started: " + $(if ($started) { 'PASS' } else { 'FAIL - helper still needed?' }))
    if (-not $started) { $ok = $false }
    else { Start-Sleep -Seconds $GameSeconds }

    # Close the game so focus returns to the manager.
    Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 6

    # --- 2. write currency from the GUI -------------------------------------
    Write-Host ''
    Write-Host '--- pressing 写入存档 ---'
    $hwnd = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        foreach ($w in ([NoDep]::TopLevel([uint32]$gui.Id, $true))) {
            if ([NoDep]::Text($w) -match 'Zombie Farm') { $hwnd = $w; break }
        }
        if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
    }
    if ($hwnd -eq [IntPtr]::Zero) { throw 'manager window did not come back' }

    $btnApply = [NoDep]::Descendants($hwnd, 'BUTTON') |
        Where-Object { [NoDep]::Text($_) -eq $applyLabel } | Select-Object -First 1
    if (-not $btnApply) { throw 'apply-currency button not found' }

    $editsBefore = @([NoDep]::Descendants($hwnd, 'EDIT') | ForEach-Object { [NoDep]::Text($_) })
    Write-Host "  numeric fields before: $($editsBefore -join ', ')"

    [void][NoDep]::PostMessage($btnApply, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)

    # Confirmation dialog: accept with WM_COMMAND/IDYES, which is more reliable
    # than hunting for the button (its class is plain Win32 "Button").
    $dlg = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds(10)
    $known = @([NoDep]::TopLevel([uint32]$gui.Id, $true))
    while ((Get-Date) -lt $deadline -and $dlg -eq [IntPtr]::Zero) {
        foreach ($w in ([NoDep]::TopLevel([uint32]$gui.Id, $true))) {
            if ($known -contains $w) { continue }
            if ([NoDep]::Text($w) -match '确认修改') { $dlg = $w; break }
        }
        if ($dlg -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 300 }
    }

    if ($dlg -eq [IntPtr]::Zero) {
        Write-Host '  FAIL: no confirmation dialog (button press produced nothing?)'
        $ok = $false
    } else {
        Write-Host "  dialog: '$([NoDep]::Text($dlg))'"
        [void][NoDep]::PostMessage($dlg, 0x0111, [IntPtr]6, [IntPtr]::Zero)   # WM_COMMAND, IDYES
        Start-Sleep -Seconds 3

        # A backup must have appeared, which only happens if the writer ran.
        $backups = @(Get-ChildItem $docs -Filter 'saveGame.bin2.bak-*' -File)
        Write-Host "  backups after write: $($backups.Count)"
        if ($backups.Count -lt 1) {
            Write-Host '  FAIL: no backup was created, so the write did not happen'
            $ok = $false
        } else {
            Write-Host '  currency write with helper absent: PASS'
        }
    }
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    $ok = $false
} finally {
    # --- close the GUI ------------------------------------------------------
    if ($hwnd -ne [IntPtr]::Zero) {
        [void][NoDep]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    Start-Sleep -Seconds 2
    if ($null -ne $gui -and -not $gui.HasExited) { try { $gui.Kill() } catch { } }
    Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    # --- restore the helpers and the saves ----------------------------------
    foreach ($h in $renamed) {
        $p = Join-Path $Root $h
        if (Test-Path -LiteralPath "$p.hidden") {
            Move-Item -LiteralPath "$p.hidden" -Destination $p -Force
        }
    }
    Write-Host ''
    Write-Host "helpers restored: $(@(Get-ChildItem $Root -Filter '*.ps1' -File | Where-Object { $_.Name -in $helpers }).Count)/$($helpers.Count)"

    # Put the save folder back exactly as it was.
    Get-ChildItem $docs -Filter 'saveGame.bin2.bak-*' -File | Remove-Item -Force -ErrorAction SilentlyContinue
    foreach ($f in (Get-ChildItem $safe -File)) {
        Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $docs $f.Name) -Force
    }
    $liveHashAfter = (Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash
    Write-Host "live save restored to original: $(if ($liveHashAfter -eq $liveHashBefore) { 'yes' } else { 'NO' })"
}

Write-Host ''
Write-Host ("RESULT: " + $(if ($ok) { 'PASS - the manager works with both helper scripts deleted' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })
