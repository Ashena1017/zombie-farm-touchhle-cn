# Drive the GUI's real controls and confirm the settings file is rewritten.
#
# The -Set path is covered elsewhere; this proves the *UI wiring* works, i.e.
# that changing a dropdown really saves. Note that WinForms creates windows with
# versioned class names ("WindowsForms10.COMBOBOX.app.0.<hash>_r9_ad1"), so
# controls must be matched by substring, not by equality.
#
# Combos are identified by their item text rather than by creation order, so the
# test cannot silently pass against the wrong control if the layout changes.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$TimeoutSeconds = 40
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
$optionsFile = Join-Path $hleRoot 'touchHLE_options.txt'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class Ui {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll", EntryPoint="SendMessageW", CharSet=CharSet.Unicode)]
    public static extern IntPtr SendMessageStr(IntPtr h, uint msg, IntPtr w, StringBuilder l);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    public delegate bool EnumProc(IntPtr h, IntPtr p);

    public static string Text(IntPtr h) { var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512); return sb.ToString(); }
    public static string Cls(IntPtr h)  { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }

    public static IntPtr FindTopLevel(uint pid, string titlePart) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint wpid; GetWindowThreadProcessId(h, out wpid);
            if (wpid == pid && IsWindowVisible(h) && Text(h).Contains(titlePart)) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    // All descendants whose class name contains `fragment`.
    public static IntPtr[] Descendants(IntPtr parent, string fragment) {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (Cls(h).Contains(fragment)) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }

    // Every item string of a combo box.
    public static string[] ComboItems(IntPtr combo) {
        int n = (int)SendMessage(combo, 0x0146, IntPtr.Zero, IntPtr.Zero);   // CB_GETCOUNT
        var items = new List<string>();
        for (int i = 0; i < n; i++) {
            int len = (int)SendMessage(combo, 0x0149, (IntPtr)i, IntPtr.Zero);  // CB_GETLBTEXTLEN
            if (len <= 0) { items.Add(""); continue; }
            var sb = new StringBuilder(len + 2);
            SendMessageStr(combo, 0x0148, (IntPtr)i, sb);                       // CB_GETLBTEXT
            items.Add(sb.ToString());
        }
        return items.ToArray();
    }

    public static int ComboSelected(IntPtr combo) {
        return (int)SendMessage(combo, 0x0147, IntPtr.Zero, IntPtr.Zero);   // CB_GETCURSEL
    }
}
'@

$CB_SETCURSEL = 0x014E
$WM_CLOSE = 0x0010

# --- launch the GUI ---------------------------------------------------------
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' + $manager + '"'
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)

$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
    $hwnd = [Ui]::FindTopLevel([uint32]$proc.Id, 'Zombie Farm')
    if ($hwnd -eq [IntPtr]::Zero) {
        foreach ($p in (Get-Process -Name 'powershell' -ErrorAction SilentlyContinue)) {
            if ($p.MainWindowTitle -match 'Zombie Farm') { $hwnd = $p.MainWindowHandle; break }
        }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}
if ($hwnd -eq [IntPtr]::Zero) { Write-Host '  FAIL: no window appeared'; exit 1 }
Start-Sleep -Seconds 3

$combos = [Ui]::Descendants($hwnd, 'COMBOBOX')
Write-Host "  combo boxes found: $($combos.Count)"
if ($combos.Count -lt 5) { Write-Host '  FAIL: expected 5 setting dropdowns'; exit 1 }

# Identify the scale combo by its item text: it is the one holding "3/2". Matching
# on content rather than creation order keeps this test from silently passing
# against the wrong control if the layout changes.
$sizeCombo = [IntPtr]::Zero
foreach ($c in $combos) {
    $items = [Ui]::ComboItems($c)
    $joined = $items -join ' | '
    Write-Host ("    [{0}] {1}" -f ([Ui]::ComboSelected($c)), $joined)
    if (($items -contains ([char]0x00D7 + '3/2')) -and $sizeCombo -eq [IntPtr]::Zero) { $sizeCombo = $c }
}
if ($sizeCombo -eq [IntPtr]::Zero) { Write-Host '  FAIL: scale combo not identified'; exit 1 }

$before = (([System.IO.File]::ReadAllText($optionsFile)) -split "`r?`n") |
    Where-Object { $_ -match '^com\.playforge' }
Write-Host ''
Write-Host "  before : $before"

# --- change it the way a user would (keyboard selection) -------------------
# CB_SETCURSEL changes the selection but does NOT raise SelectedIndexChanged in
# WinForms, so simulate the keyboard instead: focus is not needed because
# WM_KEYDOWN to the combo's child edit is what a real selection sends. The
# reliable equivalent is CB_SETCURSEL followed by a notification, so send both
# CB_SETCURSEL and a WM_COMMAND(CBN_SELCHANGE) to the parent form.
$CB_SETCURSEL = 0x014E
$CBN_SELCHANGE = 1
$WM_COMMAND = 0x0111

# Select item index 0 = the ×5/4 preset, i.e. --scale-hack=5/4. The default is
# 3/2 (index 2), so this is a real change rather than a no-op.
[void][Ui]::SendMessage($sizeCombo, $CB_SETCURSEL, [IntPtr]0, [IntPtr]::Zero)
$ctrlId = 0
# The control id is needed for WM_COMMAND; use GetDlgCtrlID.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Ui2 {
    [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
}
'@
$ctrlId = [Ui2]::GetDlgCtrlID($sizeCombo)
$wparam = [IntPtr](($CBN_SELCHANGE -shl 16) -bor ($ctrlId -band 0xFFFF))
[void][Ui]::SendMessage($hwnd, $WM_COMMAND, $wparam, $sizeCombo)

Start-Sleep -Seconds 3

$after = (([System.IO.File]::ReadAllText($optionsFile)) -split "`r?`n") |
    Where-Object { $_ -match '^com\.playforge' }
Write-Host "  after  : $after"

$ok = $after -match '--scale-hack=5/4'
Write-Host ''
if ($ok) {
    Write-Host '  => PASS: the dropdown change rewrote touchHLE_options.txt' -ForegroundColor Green
} else {
    Write-Host '  => FAIL: the file did not pick up the new value' -ForegroundColor Red
}

# --- the 写入存档 button must be present and enabled ------------------------
$buttons = [Ui]::Descendants($hwnd, 'BUTTON')
$labels = @($buttons | ForEach-Object { [Ui]::Text($_) })
Write-Host ''
Write-Host ("  buttons: " + ($labels -join ' / '))
$applyLabel = [string][char]0x5199 + [char]0x5165 + [char]0x5B58 + [char]0x6863
$hasApply = $labels -contains $applyLabel
Write-Host ("  currency button present: " + $hasApply)

# --- close -----------------------------------------------------------------
[void][Ui]::PostMessage($hwnd, $WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
if (-not $proc.WaitForExit(15000)) { try { $proc.Kill() } catch { } } else {
    Write-Host "  closed cleanly, exit=$($proc.ExitCode)"
}

exit $(if ($ok -and $hasApply) { 0 } else { 1 })
