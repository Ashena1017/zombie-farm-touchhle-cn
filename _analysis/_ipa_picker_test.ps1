# Verify the IPA picker end to end: switching the dropdown must re-point the app id,
# and therefore the save folder and settings line, to the chosen IPA's bundle id.
#
# This is the part that could silently do nothing: the dropdown could update its own
# text while the manager keeps using the old id, and everything would LOOK fine
# until saves went to the wrong place.
#
# Uses the three distinct bundle ids present in zombie_farm_ipa\:
#   com.playforge.ZombieFarm.ZFR      (29 files, the main line)
#   com.playforge.ZFR.LZ54D2GT3D      (ZFR 1.0.zh-CN-unsigned.ipa)
#   com.playforge.ZombieFarmChinese   (Zombie_Farm_1.181.modified.ipa)
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

$optionsFile = Join-Path $hleRoot 'touchHLE_options.txt'
$selectionFile = Join-Path $Root 'launcher_selected_ipa.txt'

# Preserve the user's remembered choice so the test does not change it for real.
$selectionBackup = $null
if (Test-Path -LiteralPath $selectionFile) {
    $selectionBackup = [System.IO.File]::ReadAllText($selectionFile)
}
$optionsBackup = [System.IO.File]::ReadAllText($optionsFile)

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class IpaProbe {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll", EntryPoint="SendMessageW", CharSet=CharSet.Unicode)]
    public static extern IntPtr SendMessageStr(IntPtr h, uint m, IntPtr w, StringBuilder l);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    public delegate bool EnumProc(IntPtr h, IntPtr p);

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

    // All labels' text, so the info line can be read back.
    public static string[] AllTexts(IntPtr parent) {
        var list = new List<string>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            string t = Text(h);
            if (t.Length > 0) { list.Add(Cls(h) + "|" + t); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
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
    public static int ComboSel(IntPtr c) { return (int)SendMessage(c, 0x0147, IntPtr.Zero, IntPtr.Zero); }
    public static void ComboSelect(IntPtr c, int i) { SendMessage(c, 0x014E, (IntPtr)i, IntPtr.Zero); }
}
'@

$ok = $true
$gui = $null
$hwnd = [IntPtr]::Zero

try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' + (Join-Path $Root 'GameManager.ps1') + '"'
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $gui = [System.Diagnostics.Process]::Start($psi)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        foreach ($w in ([IpaProbe]::TopLevel([uint32]$gui.Id, $true))) {
            if ([IpaProbe]::Text($w) -match 'Zombie Farm') { $hwnd = $w; break }
        }
        if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
    }
    if ($hwnd -eq [IntPtr]::Zero) { throw 'GUI window never appeared' }
    Start-Sleep -Seconds 4

    # --- 1. the dropdown must list every IPA ---------------------------------
    $combos = [IpaProbe]::Descendants($hwnd, 'COMBOBOX')
    Write-Host "combo boxes: $($combos.Count)"

    # The IPA combo is the one whose items look like .ipa file names.
    $ipaCombo = [IntPtr]::Zero
    foreach ($c in $combos) {
        $items = [IpaProbe]::ComboItems($c)
        if (($items -join '|') -match '\.ipa') { $ipaCombo = $c; break }
    }
    if ($ipaCombo -eq [IntPtr]::Zero) { throw 'IPA dropdown not found' }

    $items = [IpaProbe]::ComboItems($ipaCombo)
    $ipaCount = @(Get-ChildItem (Join-Path $Root 'zombie_farm_ipa') -Filter '*.ipa' -File).Count
    Write-Host "IPA entries in dropdown: $($items.Count)   files on disk: $ipaCount"
    if ($items.Count -ne $ipaCount) {
        Write-Host '  FAIL: dropdown does not list every IPA'
        $ok = $false
    } else {
        Write-Host '  every IPA listed: PASS'
    }

    # The odd bundle ids should be spelled out so they are recognisable.
    $withId = @($items | Where-Object { $_ -match '\[com\.' })
    Write-Host "  entries showing their app id: $($withId.Count)"
    foreach ($w in $withId) { Write-Host "    $w" }
    if ($withId.Count -lt 2) {
        Write-Host '  FAIL: the minority app ids should be visible in the labels'
        $ok = $false
    }

    # --- 2. find the two non-main IPAs by index ------------------------------
    $idxAlt = @()
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ($items[$i] -match 'LZ54D2GT3D|ZombieFarmChinese') { $idxAlt += $i }
    }
    Write-Host "  indices of the non-standard ids: $($idxAlt -join ', ')"
    if ($idxAlt.Count -ne 2) {
        Write-Host '  FAIL: expected exactly 2 alternative-id IPAs'
        $ok = $false
    }

    function Get-InfoLine {
        param([IntPtr]$H)
        foreach ($t in ([IpaProbe]::AllTexts($H))) {
            if ($t -match 'app id:') { return $t }
        }
        return ''
    }

    # --- 3. switch to the first alternative and check the id follows ---------
    if ($idxAlt.Count -ge 1) {
        Write-Host ''
        Write-Host '--- switching to the first alternative IPA ---'
        $before = Get-InfoLine $hwnd
        Write-Host "  before: $before"

        [IpaProbe]::ComboSelect($ipaCombo, $idxAlt[0])
        Start-Sleep -Seconds 3
        $after = Get-InfoLine $hwnd
        Write-Host "  after : $after"

        if ($after -match 'LZ54D2GT3D' -and $after -ne $before) {
            Write-Host '  app id followed the selection: PASS'
        } else {
            Write-Host '  FAIL: the info line did not pick up the new app id'
            $ok = $false
        }

        # The remembered choice must have been written.
        if (Test-Path -LiteralPath $selectionFile) {
            $saved = ([System.IO.File]::ReadAllText($selectionFile)).Trim()
            Write-Host "  remembered: $saved"
            if ($saved -match 'unsigned') { Write-Host '  selection persisted: PASS' }
            else { Write-Host '  FAIL: wrong IPA remembered'; $ok = $false }
        } else {
            Write-Host '  FAIL: no selection file was written'
            $ok = $false
        }
    }

    # --- 4. switch to the second alternative ---------------------------------
    if ($idxAlt.Count -ge 2) {
        Write-Host ''
        Write-Host '--- switching to the second alternative IPA ---'
        [IpaProbe]::ComboSelect($ipaCombo, $idxAlt[1])
        Start-Sleep -Seconds 3
        $after2 = Get-InfoLine $hwnd
        Write-Host "  after : $after2"
        if ($after2 -match 'ZombieFarmChinese') {
            Write-Host '  app id followed again: PASS'
        } else {
            Write-Host '  FAIL: second switch did not take effect'
            $ok = $false
        }
    }

    # --- 5. back to the main line --------------------------------------------
    $idxMain = -1
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ($items[$i] -match 'v27fix' -and $items[$i] -notmatch '\[com\.') { $idxMain = $i; break }
    }
    if ($idxMain -ge 0) {
        Write-Host ''
        Write-Host '--- switching back to the main IPA ---'
        [IpaProbe]::ComboSelect($ipaCombo, $idxMain)
        Start-Sleep -Seconds 3
        $after3 = Get-InfoLine $hwnd
        Write-Host "  after : $after3"
        if ($after3 -match 'com\.playforge\.ZombieFarm\.ZFR') {
            Write-Host '  restored to the main id: PASS'
        } else {
            Write-Host '  FAIL: could not switch back'
            $ok = $false
        }
    }
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    $ok = $false
} finally {
    if ($hwnd -ne [IntPtr]::Zero) {
        [void][IpaProbe]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    Start-Sleep -Seconds 2
    if ($null -ne $gui -and -not $gui.HasExited) { try { $gui.Kill() } catch { } }
    Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
        Stop-Process -Force -ErrorAction SilentlyContinue

    # Restore the user's remembered choice and the options file.
    if ($null -ne $selectionBackup) {
        [System.IO.File]::WriteAllText($selectionFile, $selectionBackup,
            (New-Object System.Text.UTF8Encoding($false)))
    } elseif (Test-Path -LiteralPath $selectionFile) {
        Remove-Item -LiteralPath $selectionFile -Force
    }
    [System.IO.File]::WriteAllText($optionsFile, $optionsBackup,
        (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ''
    Write-Host 'restored the remembered IPA choice and touchHLE_options.txt'
}

Write-Host ''
Write-Host ("RESULT: " + $(if ($ok) { 'PASS' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })
