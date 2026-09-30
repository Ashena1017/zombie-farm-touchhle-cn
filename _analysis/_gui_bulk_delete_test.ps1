# Destructive end-to-end test of bulk delete through the real GUI.
#
# Strategy: refresh a safety copy of every backup, then use the GUI's own
# 全选备份 button to select all backups and 删除所选 to remove them in one go.
# That exercises the exact path a user takes with bulk selection, and it also
# proves the most important safety property: 全选 + 删除 must NOT touch the live
# save, which is listed in the same ListView.
#
# Everything is restored from _analysis\save_backups_safe afterwards, and the
# restore is verified, so the test is repeatable and cannot lose real data.
#
# Note on why clicking is used rather than LVM_SETITEMSTATE: that message takes a
# POINTER to an LVITEM, and since the LVM_* range is >= WM_USER there is no
# cross-process marshalling, so a pointer from another process crashes the
# control. The 全选备份 button avoids the problem entirely.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$TimeoutSeconds = 45
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

$docs = Join-Path $hleRoot 'touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents'
$live = Join-Path $docs 'saveGame.bin2'
$safe = Join-Path $Root '_analysis\save_backups_safe'
$manager = Join-Path $Root 'GameManager.ps1'

# --- 0. refresh the safety copy --------------------------------------------
if (Test-Path -LiteralPath $safe) { Remove-Item -LiteralPath $safe -Recurse -Force }
New-Item -ItemType Directory -Force -Path $safe | Out-Null
Get-ChildItem $docs -Filter 'saveGame.bin2.bak*' -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $safe -Force
}
$safeNames = @(Get-ChildItem $safe -File | ForEach-Object { $_.Name })
Write-Host "safety copy: $($safeNames.Count) file(s)"

$liveHashBefore = (Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash
$backupsBefore = @(Get-ChildItem $docs -Filter 'saveGame.bin2.bak*' -File).Count
Write-Host "backups before: $backupsBefore"
if ($backupsBefore -eq 0) { Write-Host 'FAIL: nothing to test with'; exit 1 }

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class BulkProbe {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    public delegate bool EnumProc(IntPtr h, IntPtr p);

    public static string Text(IntPtr h) { var sb = new StringBuilder(2048); GetWindowTextW(h, sb, 2048); return sb.ToString(); }
    public static string Cls(IntPtr h)  { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }

    public static IntPtr FindTopLevel(uint pid, string titlePart) {
        IntPtr best = IntPtr.Zero; long bestArea = 0;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint wpid; GetWindowThreadProcessId(h, out wpid);
            if (wpid == pid && IsWindowVisible(h) && Text(h).Contains(titlePart)) {
                RECT r; GetWindowRect(h, out r);
                long a = (long)(r.Right - r.Left) * (r.Bottom - r.Top);
                if (a > bestArea) { bestArea = a; best = h; }
            }
            return true;
        }, IntPtr.Zero);
        return best;
    }

    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public static IntPtr[] Descendants(IntPtr parent, string fragment) {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (Cls(h).Contains(fragment)) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }

    public static IntPtr[] TopLevelWindows(uint pid) {
        var list = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint wpid; GetWindowThreadProcessId(h, out wpid);
            if (wpid == pid && IsWindowVisible(h)) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }
}
'@

# Chinese labels built from code points to keep this file pure ASCII.
#   全选备份 = U+5168 U+9009 U+5907 U+4EFD
#   删除所选 = U+5220 U+9664 U+6240 U+9009
$selectAllLabel = [string][char]0x5168 + [char]0x9009 + [char]0x5907 + [char]0x4EFD
$deleteLabel    = [string][char]0x5220 + [char]0x9664 + [char]0x6240 + [char]0x9009

$ok = $true
$proc = $null
$hwnd = [IntPtr]::Zero

try {
    # --- 1. open the GUI and its save tab ----------------------------------
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' + $manager + '"'
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        $hwnd = [BulkProbe]::FindTopLevel([uint32]$proc.Id, 'Zombie Farm')
        if ($hwnd -eq [IntPtr]::Zero) {
            foreach ($p in (Get-Process -Name 'powershell' -ErrorAction SilentlyContinue)) {
                if ($p.MainWindowTitle -match 'Zombie Farm') { $hwnd = $p.MainWindowHandle; break }
            }
        }
        if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
    }
    if ($hwnd -eq [IntPtr]::Zero) { throw 'GUI window never appeared' }
    Start-Sleep -Seconds 3

    $tabs = [BulkProbe]::Descendants($hwnd, 'SysTabControl32')
    $lp = [IntPtr]((12 -shl 16) -bor 90)
    [void][BulkProbe]::PostMessage($tabs[0], 0x0201, [IntPtr]1, $lp)
    [void][BulkProbe]::PostMessage($tabs[0], 0x0202, [IntPtr]0, $lp)
    Start-Sleep -Seconds 3

    $lv = ([BulkProbe]::Descendants($hwnd, 'SysListView32'))[0]
    $rows = [int][BulkProbe]::SendMessage($lv, 0x1004, [IntPtr]::Zero, [IntPtr]::Zero)
    Write-Host "list rows: $rows (expect $($backupsBefore + 1))"

    # --- 2. 全选备份 --------------------------------------------------------
    $btnAll = [BulkProbe]::Descendants($hwnd, 'BUTTON') |
        Where-Object { [BulkProbe]::Text($_) -eq $selectAllLabel } | Select-Object -First 1
    if (-not $btnAll) { throw 'select-all button not found' }
    [void][BulkProbe]::SendMessage($btnAll, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
    Start-Sleep -Seconds 2

    $sel = [int][BulkProbe]::SendMessage($lv, 0x1032, [IntPtr]::Zero, [IntPtr]::Zero)
    Write-Host "selected after 全选备份: $sel"
    if ($sel -ne $rows) {
        Write-Host "  FAIL: expected all $rows rows selected (including the live save row)"
        $ok = $false
    }

    # --- 3. 删除所选, then accept the confirmation --------------------------
    $btnDelete = [BulkProbe]::Descendants($hwnd, 'BUTTON') |
        Where-Object { [BulkProbe]::Text($_) -eq $deleteLabel } | Select-Object -First 1
    if (-not $btnDelete) { throw 'delete button not found' }
    [void][BulkProbe]::PostMessage($btnDelete, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)

    $dlg = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline -and $dlg -eq [IntPtr]::Zero) {
        foreach ($w in ([BulkProbe]::TopLevelWindows([uint32]$proc.Id))) {
            if ($w -ne $hwnd) { $dlg = $w; break }
        }
        if ($dlg -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 300 }
    }
    if ($dlg -eq [IntPtr]::Zero) { throw 'confirmation dialog never appeared' }

    Write-Host "dialog: '$([BulkProbe]::Text($dlg))'"

    # Accept the confirmation. Finding the Yes button by class name proved
    # unreliable (its class is the plain Win32 "Button", not the "BUTTON" fragment
    # used elsewhere, and it sits inside a nested #32770), so send the command a
    # button click would generate instead: WM_COMMAND with IDYES in wParam.
    $WM_COMMAND = 0x0111
    $IDYES = 6
    [void][BulkProbe]::PostMessage($dlg, $WM_COMMAND, [IntPtr]$IDYES, [IntPtr]::Zero)
    Start-Sleep -Seconds 3

    # If the dialog is still up, fall back to the keyboard default button.
    $still = $false
    foreach ($w in ([BulkProbe]::TopLevelWindows([uint32]$proc.Id))) {
        if ($w -ne $hwnd) { $still = $true }
    }
    if ($still) {
        Write-Host '  (WM_COMMAND did not dismiss it; pressing Enter)'
        [void][BulkProbe]::PostMessage($dlg, 0x0100, [IntPtr]0x0D, [IntPtr]::Zero)  # WM_KEYDOWN VK_RETURN
        [void][BulkProbe]::PostMessage($dlg, 0x0101, [IntPtr]0x0D, [IntPtr]::Zero)  # WM_KEYUP
        Start-Sleep -Seconds 3
    }

    # --- 4. verify ----------------------------------------------------------
    Write-Host ''
    $backupsAfter = @(Get-ChildItem $docs -Filter 'saveGame.bin2.bak*' -File).Count
    Write-Host "backups after: $backupsAfter (expect 0)"

    if ($backupsAfter -ne 0) {
        Write-Host '  FAIL: bulk delete did not remove every selected backup'
        $ok = $false
    } else {
        Write-Host '  all selected backups deleted: PASS'
    }

    # The live save must survive even though 全选 selected its row too.
    if (-not (Test-Path -LiteralPath $live)) {
        Write-Host '  FAIL: the live save was deleted!'
        $ok = $false
    } else {
        $h = (Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash
        if ($h -eq $liveHashBefore) {
            Write-Host '  live save survived 全选 + 删除 unchanged: PASS'
        } else {
            Write-Host '  FAIL: live save content changed'
            $ok = $false
        }
    }
} catch {
    Write-Host ("  ERROR: " + $_.Exception.Message)
    $ok = $false
} finally {
    if ($hwnd -ne [IntPtr]::Zero) {
        [void][BulkProbe]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    Start-Sleep -Seconds 2
    if ($null -ne $proc -and -not $proc.HasExited) { try { $proc.Kill() } catch { } }
    Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

# --- 5. restore everything from the safety copy -----------------------------
Write-Host ''
Write-Host '--- restoring from safety copy ---'
$restored = 0
foreach ($f in (Get-ChildItem $safe -File)) {
    Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $docs $f.Name) -Force
    $restored++
}
$backupsRestored = @(Get-ChildItem $docs -Filter 'saveGame.bin2.bak*' -File).Count
Write-Host "restored $restored file(s); backups now: $backupsRestored (expect $backupsBefore)"
if ($backupsRestored -ne $backupsBefore) {
    Write-Host '  FAIL: restore did not bring back every backup'
    $ok = $false
} else {
    Write-Host '  all backups restored: PASS'
}

Write-Host ''
Write-Host ("RESULT: " + $(if ($ok) { 'PASS' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })
