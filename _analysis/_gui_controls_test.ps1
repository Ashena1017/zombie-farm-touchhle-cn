# Verify the new UI's controls.
#
# Approach note: UI Automation reports every control in this window as
# ControlType.Pane, because WinForms exposes them via versioned custom window
# classes (WindowsForms10.*) that UIA cannot classify. So this uses raw Win32
# class-name matching (verified to work) plus SendMessage combo-box messages.
#
# A WinForms NumericUpDown is likewise not enumerated as an "UpDown" child: its
# spinner is internal and only the inner EDIT appears as a child window, so the
# custom framerate box is identified by its value.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why); Chinese is built from code
# points where a comparison is needed.
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

# custom = U+81EA U+5B9A U+4E49 ,  frame = U+5E27
$customLabel = [string][char]0x81EA + [char]0x5B9A + [char]0x4E49
$frameLabel  = [string][char]0x5E27

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class UiProbe {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
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

    public static IntPtr[] Descendants(IntPtr parent, string fragment) {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (Cls(h).Contains(fragment)) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }

    public static IntPtr FindOtherTopLevel(uint pid, IntPtr exclude, string titlePart) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint wpid; GetWindowThreadProcessId(h, out wpid);
            if (h != exclude && wpid == pid && IsWindowVisible(h) && Text(h).Contains(titlePart)) {
                found = h;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static string[] ComboItems(IntPtr combo) {
        int n = (int)SendMessage(combo, 0x0146, IntPtr.Zero, IntPtr.Zero);
        var items = new List<string>();
        for (int i = 0; i < n; i++) {
            int len = (int)SendMessage(combo, 0x0149, (IntPtr)i, IntPtr.Zero);
            if (len <= 0) { items.Add(""); continue; }
            var sb = new StringBuilder(len + 2);
            SendMessageStr(combo, 0x0148, (IntPtr)i, sb);
            items.Add(sb.ToString());
        }
        return items.ToArray();
    }
    public static int ComboSelected(IntPtr c) { return (int)SendMessage(c, 0x0147, IntPtr.Zero, IntPtr.Zero); }

    // Change a combo's selection so the app actually NOTICES.
    //
    // CB_SETCURSEL alone changes the selection but raises no CBN_SELCHANGE, so a
    // WinForms SelectedIndexChanged handler never runs and nothing is saved - the
    // setting silently looks unchanged. Send the notification a real selection
    // would send, which is what makes the app persist the new value.
    //
    // The notification must go to the TOP-LEVEL form, not to the combo's immediate
    // parent: these combos sit inside a GroupBox, and WM_COMMAND delivered to a
    // GroupBox is not routed onward to the form's handler, so the setting was
    // never saved. The live size readout still updated - it is refreshed by a
    // timer that reads the controls directly - which is exactly what made this
    // look like a saving bug instead of a test bug.
    public static void ComboSelect(IntPtr c, int i) {
        SendMessage(c, 0x014E, (IntPtr)i, IntPtr.Zero);          // CB_SETCURSEL
        IntPtr root = GetAncestor(c, 2);                          // GA_ROOT
        int id = GetDlgCtrlID(c);
        // WM_COMMAND with HIWORD(wParam) = CBN_SELCHANGE and LOWORD = control id.
        IntPtr wparam = (IntPtr)((1 << 16) | (id & 0xFFFF));
        SendMessage(root, 0x0111, wparam, c);
    }

    [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flags);
    [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
}
'@

$WM_CLOSE = 0x0010
$optionsFile = Join-Path $hleRoot 'touchHLE_options.txt'
$manager = Join-Path $Root 'GameManager.ps1'

function Get-OptionsLine {
    (([System.IO.File]::ReadAllText($optionsFile)) -split "`r?`n") |
        Where-Object { $_ -match '^com\.playforge' } | Select-Object -First 1
}

# Normalise the starting state before launching the GUI.
#
# The assertions below compare the dropdown's SELECTED INDEX against the expected
# default, so a leftover value from a previous experiment (e.g. --scale-hack=3/2,
# which is still valid but is not a preset any more, so the UI shows 自定义) would
# make the "default is selected" check fail for a reason that has nothing to do
# with the code. Writing the recommended configuration first makes the test
# independent of whatever the machine was left in.
Write-Host '  normalising settings to the recommended configuration first'
& powershell -NoProfile -ExecutionPolicy Bypass -File $manager `
    -Set 'fps_limit=60,window_family=ipad,window_scale=1.5,wheel_zoom=1.1' | Out-Null
Write-Host "  start : $(Get-OptionsLine)"

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' + $manager + '"'
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)

$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
    $hwnd = [UiProbe]::FindTopLevel([uint32]$proc.Id, 'Zombie Farm')
    if ($hwnd -eq [IntPtr]::Zero) {
        foreach ($p in (Get-Process -Name 'powershell' -ErrorAction SilentlyContinue)) {
            if ($p.MainWindowTitle -match 'Zombie Farm') { $hwnd = $p.MainWindowHandle; break }
        }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}
if ($hwnd -eq [IntPtr]::Zero) { Write-Host '  FAIL: no window'; exit 1 }
Start-Sleep -Seconds 3

$ok = $true
$tabs = [UiProbe]::Descendants($hwnd, 'SysTabControl32')
$pageHeights = @{}
if ($tabs.Count -gt 0) {
    # Visit settings and game once so both pages create their native control handles.
    foreach ($x in @(90, 30)) {
        $lp = [IntPtr]((12 -shl 16) -bor $x)
        [void][UiProbe]::PostMessage($tabs[0], 0x0201, [IntPtr]1, $lp)
        [void][UiProbe]::PostMessage($tabs[0], 0x0202, [IntPtr]0, $lp)
        Start-Sleep -Milliseconds 700
        $r = New-Object UiProbe+RECT
        [void][UiProbe]::GetWindowRect($hwnd, [ref]$r)
        $pageHeights[$x] = $r.Bottom - $r.Top
    }
} else {
    Write-Host '  FAIL: manager tab control not found'
    $ok = $false
}

# --- 1. fps presets --------------------------------------------------------
$combos = [UiProbe]::Descendants($hwnd, 'COMBOBOX')
Write-Host "  combo boxes: $($combos.Count)"
$fpsCombo = [IntPtr]::Zero
foreach ($c in $combos) {
    $items = [UiProbe]::ComboItems($c)
    if (($items -join '|') -match $frameLabel) { $fpsCombo = $c; break }
}
if ($fpsCombo -eq [IntPtr]::Zero) {
    Write-Host '  FAIL: fps combo not found'
    $ok = $false
} else {
    $items = [UiProbe]::ComboItems($fpsCombo)
    Write-Host "  fps choices: $($items -join ' | ')"
    foreach ($want in @('30', '60', '90', '120')) {
        if (($items -join ' ') -notmatch "\b$want\b") {
            Write-Host "  FAIL: preset $want missing"
            $ok = $false
        }
    }
    $hasCustom = ($items -join ' ') -match $customLabel
    Write-Host ("  custom entry present: " + $(if ($hasCustom) { 'PASS' } else { 'FAIL' }))
    if (-not $hasCustom) { $ok = $false }
    Write-Host ("  6 choices (30/60/90/120/off/custom): " +
        $(if ($items.Count -eq 6) { 'PASS' } else { "FAIL (got $($items.Count))" }))
    if ($items.Count -ne 6) { $ok = $false }
}

# --- 2. the custom fps box -------------------------------------------------
$edits = [UiProbe]::Descendants($hwnd, 'EDIT')
$values = @($edits | ForEach-Object { [UiProbe]::Text($_) })
Write-Host "  edit boxes: $($edits.Count)  values: $($values -join ', ')"

# Find the custom fps editor by its position on the same row and to the right of
# the fps dropdown. The game tab now owns the currency editors, so child-window
# creation order no longer identifies the fps editor reliably.
$customEdit = $null
$fpsRect = New-Object UiProbe+RECT
[void][UiProbe]::GetWindowRect($fpsCombo, [ref]$fpsRect)
foreach ($e in $edits) {
    $r = New-Object UiProbe+RECT
    [void][UiProbe]::GetWindowRect($e, [ref]$r)
    $sameRow = ($r.Top -lt $fpsRect.Bottom) -and ($r.Bottom -gt $fpsRect.Top)
    if ($sameRow -and $r.Left -ge $fpsRect.Right) { $customEdit = $e; break }
}

if ($null -eq $customEdit) {
    Write-Host '  FAIL: custom fps box not found'
    $ok = $false
} else {
    Write-Host "  custom fps box value: $([UiProbe]::Text($customEdit))"
    $enabledBefore = [UiProbe]::IsWindowEnabled($customEdit)
    Write-Host ("  disabled while a preset is selected: " +
        $(if (-not $enabledBefore) { 'PASS' } else { 'FAIL' }))
    if ($enabledBefore) { $ok = $false }

    $items = [UiProbe]::ComboItems($fpsCombo)
    $customIndex = -1
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ($items[$i] -match $customLabel) { $customIndex = $i; break }
    }
    if ($customIndex -lt 0) {
        Write-Host '  FAIL: custom item index not found'
        $ok = $false
    } else {
        [UiProbe]::ComboSelect($fpsCombo, $customIndex)
        Start-Sleep -Seconds 2
        $enabledAfter = [UiProbe]::IsWindowEnabled($customEdit)
        Write-Host ("  enabled after choosing the custom entry: " +
            $(if ($enabledAfter) { 'PASS' } else { 'FAIL' }))
        if (-not $enabledAfter) { $ok = $false }
        Write-Host "  options line now: $(Get-OptionsLine)"
    }
}

# --- 2b. the window row: family + scale + a live size readout ---------------
# The whole point of the row is that the family and the scale are chosen
# separately while the resulting window size stays visible, so all three parts are
# checked together. The readout is a Label, and its text is what the operator
# actually reads before launching.
Write-Host ''
Write-Host '--- window row ---'

$famCombo = [IntPtr]::Zero
$sclCombo = [IntPtr]::Zero
foreach ($c in $combos) {
    $it = [UiProbe]::ComboItems($c)
    $joined = $it -join ' '
    if ($famCombo -eq [IntPtr]::Zero -and $joined -match 'iPad' -and $joined -match 'iPhone') { $famCombo = $c; continue }
    # The scale combo holds the three DECIMAL presets. Matched on 1.25 and 1.75,
    # which the wheel-zoom combo (1.1 / 1.2 / 1.5) does not have, so the two
    # cannot be confused even though both contain a 1.5.
    if ($sclCombo -eq [IntPtr]::Zero -and $it.Count -le 5 -and
        ($joined -match '1\.25') -and ($joined -match '1\.75')) {
        $sclCombo = $c
    }
}
if ($famCombo -eq [IntPtr]::Zero) { Write-Host '  FAIL: device family combo not found'; $ok = $false }
if ($sclCombo -eq [IntPtr]::Zero) { Write-Host '  FAIL: scale combo not found'; $ok = $false }

if ($famCombo -ne [IntPtr]::Zero -and $sclCombo -ne [IntPtr]::Zero) {
    # Every label in the window, so the live size readout can be found by content.
    function Get-Labels {
        $out = @()
        foreach ($l in [UiProbe]::Descendants($hwnd, 'STATIC')) { $out += [UiProbe]::Text($l) }
        return $out
    }
    function Find-SizeLabel {
        # Identified by its prefix (U+7A97 U+53E3 = window, then a space, then
        # "W x H"), not by a particular size - a smaller combination like
        # iPhone x1.25 is 600x400, which no 4-digit match would find.
        $prefix = [string][char]0x7A97 + [char]0x53E3
        foreach ($l in [UiProbe]::Descendants($hwnd, 'STATIC')) {
            $t = [UiProbe]::Text($l)
            if ($t.StartsWith($prefix) -and $t -match '\d') { return $t }
        }
        return ''
    }

    # Defaults must be iPad (index 0) and x1.5 (index 1), with the readout showing
    # the size that combination really produces.
    Write-Host ("  family selected: {0}" -f [UiProbe]::ComboSelected($famCombo))
    Write-Host ("  scale  selected: {0}" -f [UiProbe]::ComboSelected($sclCombo))
    $sizeText = Find-SizeLabel
    Write-Host "  size readout   : '$sizeText'"
    $defOk = ([UiProbe]::ComboSelected($famCombo) -eq 0) -and
             ([UiProbe]::ComboSelected($sclCombo) -eq 1) -and
             ($sizeText -match '1536') -and ($sizeText -match '1152')
    Write-Host ("  default ipad + x1.5 -> 1536x1152 readout: " + $(if ($defOk) { 'PASS' } else { 'FAIL' }))
    if (-not $defOk) { $ok = $false }

    # Switch to the x1.25 preset and confirm BOTH the saved option and the readout
    # change. Index 0 is a real change from the x1.5 default.
    [UiProbe]::ComboSelect($sclCombo, 0)
    Start-Sleep -Seconds 2
    $line = Get-OptionsLine
    $sizeText = Find-SizeLabel
    Write-Host "  after selecting x1.25 -> options: $line"
    Write-Host "  after selecting x1.25 -> readout: '$sizeText'"
    $sclOk = ($line -match '--scale-hack=1\.25') -and ($sizeText -match '1280') -and ($sizeText -match '960')
    Write-Host ("  x1.25 saved and readout follows: " + $(if ($sclOk) { 'PASS' } else { 'FAIL' }))
    if (-not $sclOk) { $ok = $false }

    # x1.75 must give the larger window, so the presets are not all aliases.
    [UiProbe]::ComboSelect($sclCombo, 2)
    Start-Sleep -Seconds 2
    $line = Get-OptionsLine
    $sizeText = Find-SizeLabel
    Write-Host "  after selecting x1.75 -> options: $line"
    Write-Host "  after selecting x1.75 -> readout: '$sizeText'"
    $upOk = ($line -match '--scale-hack=1\.75') -and ($sizeText -match '1792') -and ($sizeText -match '1344')
    Write-Host ("  x1.75 saved and readout follows: " + $(if ($upOk) { 'PASS' } else { 'FAIL' }))
    if (-not $upOk) { $ok = $false }

    # Switch to iPhone and confirm the family is saved independently of the scale.
    [UiProbe]::ComboSelect($famCombo, 1)
    Start-Sleep -Seconds 2
    $line = Get-OptionsLine
    $sizeText = Find-SizeLabel
    Write-Host "  after selecting iPhone -> options: $line"
    Write-Host "  after selecting iPhone -> readout: '$sizeText'"
    # iphone x1.75 = 560x840 portrait -> 840x560 landscape.
    $famOk = ($line -match '--device-family=iphone') -and ($line -match '--scale-hack=1\.75') -and
             ($sizeText -match '840') -and ($sizeText -match '560')
    Write-Host ("  iPhone with the scale kept: " + $(if ($famOk) { 'PASS' } else { 'FAIL' }))
    if (-not $famOk) { $ok = $false }

    # Put the recommended combination back, so the machine is left as found.
    [UiProbe]::ComboSelect($famCombo, 0)
    Start-Sleep -Milliseconds 800
    [UiProbe]::ComboSelect($sclCombo, 1)
    Start-Sleep -Seconds 2
    $line = Get-OptionsLine
    $restored = ($line -match '--device-family=ipad') -and ($line -match '--scale-hack=1\.5')
    Write-Host "  restored to ipad + x1.5: $(if ($restored) { 'PASS' } else { 'FAIL' })  $line"
    if (-not $restored) { $ok = $false }
}

# --- 2c. the wheel-zoom setting --------------------------------------------
# The operator asked for this to be adjustable with a default of 1.1, so the
# preset list and the default both matter.
Write-Host ''
Write-Host '--- wheel zoom ---'
$wheelCombo = [IntPtr]::Zero
foreach ($c in $combos) {
    $it = [UiProbe]::ComboItems($c)
    $joined = $it -join ' '
    # Must look like a wheel-zoom list, not the IPA dropdown: several IPA names
    # contain "1.1" (e.g. "...-v11fix.ipa"), so a loose match picks the wrong
    # control. Requiring two of the three presets and a short item count is
    # unambiguous - the IPA list has 30+ entries.
    if ($it.Count -le 6 -and ($joined -match '1\.1') -and ($joined -match '1\.5')) {
        $wheelCombo = $c
        break
    }
}
if ($wheelCombo -eq [IntPtr]::Zero) {
    Write-Host '  FAIL: wheel-zoom combo not found'
    $ok = $false
} else {
    $items = [UiProbe]::ComboItems($wheelCombo)
    Write-Host "  choices: $($items -join ' | ')"
    $wants = @('1.1', '1.2', '1.5')
    foreach ($w in $wants) {
        if (($items -join ' ') -notmatch [regex]::Escape($w)) {
            Write-Host "  FAIL: preset $w missing"
            $ok = $false
        }
    }
    $line = Get-OptionsLine
    $wheelDefaultOk = $line -match '--zf-wheel-zoom-step=1\.1'
    Write-Host ("  default 1.1 written to the options file: " + $(if ($wheelDefaultOk) { 'PASS' } else { 'FAIL' }))
    if (-not $wheelDefaultOk) { $ok = $false }

    # Select 1.5 (index 2) and confirm it is persisted.
    [UiProbe]::ComboSelect($wheelCombo, 2)
    Start-Sleep -Seconds 2
    $line = Get-OptionsLine
    $wheelOk = $line -match '--zf-wheel-zoom-step=1\.5'
    Write-Host "  after selecting 1.5 -> options: $line"
    Write-Host ("  1.5 saved: " + $(if ($wheelOk) { 'PASS' } else { 'FAIL' }))
    if (-not $wheelOk) { $ok = $false }

    # Back to the default.
    [UiProbe]::ComboSelect($wheelCombo, 0)
    Start-Sleep -Seconds 2
    $line = Get-OptionsLine
    $backOk = $line -match '--zf-wheel-zoom-step=1\.1'
    Write-Host "  restored to 1.1: $(if ($backOk) { 'PASS' } else { 'FAIL' })"
    if (-not $backOk) { $ok = $false }
}

# --- 2d. the custom scale entry accepts a fraction -------------------------
# The scale editor is a free-text box (a NumericUpDown cannot express "7/4"), so
# this proves a typed fraction really reaches the options file.
Write-Host ''
Write-Host '--- custom scale entry ---'
if ($sclCombo -ne [IntPtr]::Zero) {
    # The last item is 自定义.
    $customIdx = [UiProbe]::ComboItems($sclCombo).Count - 1
    [UiProbe]::ComboSelect($sclCombo, $customIdx)
    Start-Sleep -Seconds 2

    # Find the scale text box. It is the EDIT that is a sibling of the scale combo
    # (same container, immediately to its right), which is unambiguous. Matching on
    # the text alone is NOT safe: the custom fps box holds "75", which also parses
    # as a valid scale.
    $scaleEdit = [IntPtr]::Zero
    $sclRect = New-Object UiProbe+RECT
    [void][UiProbe]::GetWindowRect($sclCombo, [ref]$sclRect)
    foreach ($e in [UiProbe]::Descendants($hwnd, 'EDIT')) {
        $r = New-Object UiProbe+RECT
        [void][UiProbe]::GetWindowRect($e, [ref]$r)
        # Same row (vertically overlapping) and to the right of the combo.
        $sameRow = ($r.Top -lt $sclRect.Bottom) -and ($r.Bottom -gt $sclRect.Top)
        if ($sameRow -and $r.Left -ge $sclRect.Right) { $scaleEdit = $e; break }
    }
    if ($scaleEdit -eq [IntPtr]::Zero) {
        Write-Host '  FAIL: scale text box not found'
        $ok = $false
    } else {
        Write-Host "  scale box text: '$([UiProbe]::Text($scaleEdit))'"
        $enabled = [UiProbe]::IsWindowEnabled($scaleEdit)
        Write-Host ("  enabled after choosing 自定义: " + $(if ($enabled) { 'PASS' } else { 'FAIL' }))
        if (-not $enabled) { $ok = $false }

        # Type "7/4" the way a user would: WM_SETTEXT then a change notification.
        [void][UiProbe]::SendMessageStr($scaleEdit, 0x000C, [IntPtr]::Zero, "7/4")
        Start-Sleep -Seconds 2
        $line = Get-OptionsLine
        $sizeText = Find-SizeLabel
        Write-Host "  after typing 7/4 -> options: $line"
        Write-Host "  after typing 7/4 -> readout: '$sizeText'"
        # ipad x7/4 = 1792x1344.
        $fracOk = ($line -match '--scale-hack=7/4') -and ($sizeText -match '1792') -and ($sizeText -match '1344')
        Write-Host ("  fraction accepted and saved: " + $(if ($fracOk) { 'PASS' } else { 'FAIL' }))
        if (-not $fracOk) { $ok = $false }

        # An invalid value must NOT be written: the options file has to stay
        # something touchHLE can start from.
        $beforeBad = Get-OptionsLine
        [void][UiProbe]::SendMessageStr($scaleEdit, 0x000C, [IntPtr]::Zero, "abc")
        Start-Sleep -Seconds 2
        $afterBad = Get-OptionsLine
        $badOk = ($afterBad -eq $beforeBad) -and ($afterBad -notmatch 'abc')
        Write-Host "  invalid text left the file alone: $(if ($badOk) { 'PASS' } else { 'FAIL' })  $afterBad"
        if (-not $badOk) { $ok = $false }
    }

    # Restore the recommended preset (index 1 = x1.5).
    [UiProbe]::ComboSelect($sclCombo, 1)
    Start-Sleep -Seconds 2
}

# --- 3. the save list must be populated ------------------------------------
# The ListView lives in the third tab page and WinForms does not create the
# handle of a control in a tab that has never been shown, so it does not exist in
# the window tree until the tab is opened. Click the tab header for real (mouse
# messages) rather than trying to fake a tab change.
$tabs = [UiProbe]::Descendants($hwnd, 'SysTabControl32')
Write-Host "  tab controls: $($tabs.Count)"
if ($tabs.Count -gt 0) {
    # Third tab header sits roughly 150px in, ~12px down, in tab-control coords.
    $lp = [IntPtr]((12 -shl 16) -bor 150)
    [void][UiProbe]::PostMessage($tabs[0], 0x0201, [IntPtr]1, $lp)   # WM_LBUTTONDOWN
    [void][UiProbe]::PostMessage($tabs[0], 0x0202, [IntPtr]0, $lp)   # WM_LBUTTONUP
    Start-Sleep -Seconds 3
    $r = New-Object UiProbe+RECT
    [void][UiProbe]::GetWindowRect($hwnd, [ref]$r)
    $pageHeights[150] = $r.Bottom - $r.Top
}

$lists = [UiProbe]::Descendants($hwnd, 'SysListView32')
Write-Host "  list views after opening the save tab: $($lists.Count)"
if ($lists.Count -eq 0) {
    Write-Host '  FAIL: save list view missing'
    $ok = $false
} else {
    # LVM_GETITEMCOUNT is 0x1004 only for the plain ListView; this is a
    # WinForms ListView in Details view, so use the documented constant.
    $LVM_GETITEMCOUNT = 0x1004
    $count = [int][UiProbe]::SendMessage($lists[0], $LVM_GETITEMCOUNT, [IntPtr]::Zero, [IntPtr]::Zero)
    # The live save is always listed, so >= 1 is the invariant that actually
    # holds. Requiring ">= 10 backups" made this test depend on how many backups
    # happen to exist on the machine, which is state, not correctness - it failed
    # on a clean sandbox where zero backups is the correct answer.
    $backups = @(Get-ChildItem -LiteralPath (Join-Path $script:hleRoot 'touchHLE_sandbox') -Recurse -Filter 'saveGame.bin2.bak*' -ErrorAction SilentlyContinue)
    $expect = 1 + $backups.Count
    Write-Host "  backup files on disk: $($backups.Count)  => expected rows: $expect"
    Write-Host "  rows listed: $count"
    if ($count -eq $expect) { Write-Host '  save list matches the save folder: PASS' }
    else { Write-Host "  FAIL: expected $expect rows (live save + backups)"; $ok = $false }
}

$heightOk = ($pageHeights[90] -lt $pageHeights[30]) -and
            ($pageHeights[30] -lt $pageHeights[150])
Write-Host ("  content-fit window heights (settings/game/saves): {0}/{1}/{2} -> {3}" -f `
    $pageHeights[90], $pageHeights[30], $pageHeights[150],
    $(if ($heightOk) { 'PASS' } else { 'FAIL' }))
if (-not $heightOk) { $ok = $false }

# Exercise the day/night button itself. Its theme update touches native handles,
# so a normal launch and the settings-control checks above do not cover this path.
$formRect = New-Object UiProbe+RECT
[void][UiProbe]::GetWindowRect($hwnd, [ref]$formRect)
$themeButton = [IntPtr]::Zero
foreach ($button in [UiProbe]::Descendants($hwnd, 'BUTTON')) {
    $buttonRect = New-Object UiProbe+RECT
    [void][UiProbe]::GetWindowRect($button, [ref]$buttonRect)
    if ($buttonRect.Left -ge ($formRect.Right - 80) -and
        $buttonRect.Top -le ($formRect.Top + 80)) {
        $themeButton = $button
        break
    }
}
if ($themeButton -eq [IntPtr]::Zero) {
    Write-Host '  FAIL: day/night button not found'
    $ok = $false
} else {
    $themeFailure = $false
    for ($i = 0; $i -lt 2; $i++) {
        [void][UiProbe]::SendMessage($themeButton, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
        Start-Sleep -Milliseconds 500
        $dialog = [UiProbe]::FindOtherTopLevel([uint32]$proc.Id, $hwnd, 'Zombie Farm')
        if ($dialog -ne [IntPtr]::Zero) {
            Write-Host "  FAIL: theme click opened a dialog: $([UiProbe]::Text($dialog))"
            $themeFailure = $true
            $ok = $false
            break
        }
    }
    if (-not $themeFailure) { Write-Host '  day/night button toggled twice without an exception dialog: PASS' }
}

Write-Host ''
# Leave the machine as it was found: this test changes the fps dropdown (to
# 自定义) and the window/wheel settings (restored inline above), so the
# recommended configuration is rewritten through the manager's own path.
& powershell -NoProfile -ExecutionPolicy Bypass -File $manager `
    -Set 'fps_limit=60,window_family=ipad,window_scale=1.5,wheel_zoom=1.1' | Out-Null
$final = Get-OptionsLine
$restoredAll = ($final -match '--fps-limit=60') -and ($final -match '--device-family=ipad') -and
               ($final -match '--scale-hack=1\.5') -and ($final -match '--zf-wheel-zoom-step=1\.1')
Write-Host "  restored the recommended configuration: $(if ($restoredAll) { 'PASS' } else { 'FAIL' })"
if (-not $restoredAll) { $ok = $false }

[void][UiProbe]::PostMessage($hwnd, $WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
if (-not $proc.WaitForExit(15000)) { try { $proc.Kill() } catch { } }
Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
    Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host ("RESULT: " + $(if ($ok) { 'PASS' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })
