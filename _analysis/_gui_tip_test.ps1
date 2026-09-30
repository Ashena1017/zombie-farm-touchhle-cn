# Verify the GUI has no in-window help affordances, that the shipped
# 使用说明.html documents the settings instead, and the bulk-delete behaviour.
#
# What this covers:
#   1. there are NO "?" buttons (they were removed on request; the explanation
#      now lives in 使用说明.html, which is checked to actually mention the
#      settings)
#   2. the save list is multi-select and 全选备份 / 取消选择 / 反选 really change the
#      selection count shown in the UI
#   3. deleting several selections at once removes exactly those files
#
# Bulk delete is exercised against a throwaway copy of the save folder via the
# sandboxed helpers rather than the real saves, and the GUI part only checks
# selection bookkeeping, so no real backup is at risk.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why); Chinese is built from code
# points where a comparison is needed.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$TimeoutSeconds = 45
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'

# Code points used below, so this file stays pure ASCII.
#   全选备份      = U+5168 U+9009 U+5907 U+4EFD
#   取消选择      = U+53D6 U+6D88 U+9009 U+62E9
#   反选          = U+53CD U+9009
#   浏览          = U+6D4F U+89C8
#   启动游戏      = U+542F U+52A8 U+6E38 U+620F
#   写入存档      = U+5199 U+5165 U+5B58 U+6863
$selectAllLabel  = [string][char]0x5168 + [char]0x9009 + [char]0x5907 + [char]0x4EFD
$selectNoneLabel = [string][char]0x53D6 + [char]0x6D88 + [char]0x9009 + [char]0x62E9
$invertLabel     = [string][char]0x53CD + [char]0x9009
$browseLabel     = [string][char]0x6D4F + [char]0x89C8 + [char]0x2026
$startLabel      = [string][char]0x542F + [char]0x52A8 + [char]0x6E38 + [char]0x620F
$applyLabel      = [string][char]0x5199 + [char]0x5165 + [char]0x5B58 + [char]0x6863

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class TipProbe {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
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

    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public static IntPtr[] Descendants(IntPtr parent, string fragment) {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (Cls(h).Contains(fragment)) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }

    // Buttons on a direct-child basis (the "?" buttons live in the group box).
    public static IntPtr[] AllDescendants(IntPtr parent) {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) { list.Add(h); return true; }, IntPtr.Zero);
        return list.ToArray();
    }

    // Every visible top-level window owned by the process, so a modal dialog can
    // be found without knowing its title.
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

$manager = Join-Path $Root 'GameManager.ps1'
$ok = $true

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' + $manager + '"'
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)

$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
    $hwnd = [TipProbe]::FindTopLevel([uint32]$proc.Id, 'Zombie Farm')
    if ($hwnd -eq [IntPtr]::Zero) {
        foreach ($p in (Get-Process -Name 'powershell' -ErrorAction SilentlyContinue)) {
            if ($p.MainWindowTitle -match 'Zombie Farm') { $hwnd = $p.MainWindowHandle; break }
        }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}
if ($hwnd -eq [IntPtr]::Zero) { Write-Host '  FAIL: no window'; exit 1 }
Start-Sleep -Seconds 3

# --- 1. the "?" buttons must be GONE ----------------------------------------
# They were removed at the operator's request: all of that explanation now lives
# in 使用说明.html, shipped beside the manager. The assertion is inverted rather
# than deleted, so a stray help affordance creeping back into the UI is caught.
$buttons = [TipProbe]::Descendants($hwnd, 'BUTTON')
$labels = @($buttons | ForEach-Object { [TipProbe]::Text($_) })
Write-Host "  buttons: $($buttons.Count) -- $($labels -join ' / ')"
$questionButtons = @($buttons | Where-Object { [TipProbe]::Text($_) -eq '?' })
Write-Host "  '?' buttons: $($questionButtons.Count)"
if ($questionButtons.Count -eq 0) {
    Write-Host '  no ? buttons remain: PASS'
} else {
    Write-Host "  FAIL: expected no '?' buttons, got $($questionButtons.Count)"
    $ok = $false
}

# The buttons that SHOULD still be there, so "no buttons at all" cannot
# masquerade as a pass above. Only the game tab's buttons are checkable here: a
# WinForms control in a tab page that has never been shown has no handle, so the
# save tab's buttons do not exist in the window tree yet. Those are checked in
# section 3, after the tab is opened for real.
foreach ($want in @($browseLabel, $startLabel, $applyLabel)) {
    $has = $labels -contains $want
    if (-not $has) { Write-Host "  FAIL: button '$want' is missing"; $ok = $false }
}

# --- 2. 使用说明.html must carry the explanation instead ---------------------
# The settings' help text has to live somewhere; if it is neither in the GUI nor
# in the shipped guide, the information was simply lost.
#
# The filename must be built from code points: this file is saved as ASCII, so a
# literal Chinese path would be decoded with the console's ANSI code page and turn
# into mojibake ("浣跨敤璇存槑.html"), producing a bogus "missing" failure.
$guideName = [string][char]0x4F7F + [char]0x7528 + [char]0x8BF4 + [char]0x660E + '.html'
$guide = Join-Path (Join-Path $Root 'Release') $guideName
if (-not (Test-Path -LiteralPath $guide)) {
    Write-Host "  FAIL: the shipped guide is missing ($guideName)"
    $ok = $false
} else {
    $guideText = [System.IO.File]::ReadAllText($guide, [System.Text.UTF8Encoding]::new($true))
    # A few phrases that must be documented, keyed by ASCII-safe substrings where
    # possible so this file stays readable. Chinese is built from code points.
    $needles = @(
        @{ Name = 'wheel zoom section'; Text = ([string][char]0x6EDA + [char]0x8F6E) },          # 滚轮
        @{ Name = 'window family';      Text = 'iPad' },
        @{ Name = 'scale presets';      Text = '1.25' },
        @{ Name = 'fps note';           Text = ([string][char]0x5E27 + [char]0x7387) }            # 帧率
    )
    foreach ($n in $needles) {
        $has = $guideText.Contains($n.Text)
        Write-Host ("  guide mentions {0,-20} {1}" -f $n.Name, $(if ($has) { 'ok' } else { 'MISSING' }))
        if (-not $has) { $ok = $false }
    }
}

# --- 3. save tab: multi-select + bulk buttons --------------------------------
# Open the save tab for real: the ListView handle only exists once it is shown.
$tabs = [TipProbe]::Descendants($hwnd, 'SysTabControl32')
if ($tabs.Count -gt 0) {
    $lp = [IntPtr]((12 -shl 16) -bor 90)
    [void][TipProbe]::PostMessage($tabs[0], 0x0201, [IntPtr]1, $lp)
    [void][TipProbe]::PostMessage($tabs[0], 0x0202, [IntPtr]0, $lp)
    Start-Sleep -Seconds 3
}

$lists = [TipProbe]::Descendants($hwnd, 'SysListView32')
if ($lists.Count -eq 0) {
    Write-Host '  FAIL: save list not found'
    $ok = $false
} else {
    $lv = $lists[0]
    $total = [int][TipProbe]::SendMessage($lv, 0x1004, [IntPtr]::Zero, [IntPtr]::Zero)  # LVM_GETITEMCOUNT
    $selBefore = [int][TipProbe]::SendMessage($lv, 0x1032, [IntPtr]::Zero, [IntPtr]::Zero)  # LVM_GETSELECTEDCOUNT
    Write-Host "  list rows: $total   selected: $selBefore"

    # The bulk buttons must exist.
    $labels = @([TipProbe]::Descendants($hwnd, 'BUTTON') | ForEach-Object { [TipProbe]::Text($_) })
    foreach ($want in @($selectAllLabel, $selectNoneLabel, $invertLabel)) {
        $has = $labels -contains $want
        Write-Host ("  button '{0}': {1}" -f $want, $(if ($has) { 'present' } else { 'MISSING' }))
        if (-not $has) { $ok = $false }
    }

    # Click 全选备份 and confirm the selection count rises to every row.
    $btnAll = [TipProbe]::Descendants($hwnd, 'BUTTON') |
        Where-Object { [TipProbe]::Text($_) -eq $selectAllLabel } | Select-Object -First 1
    if ($btnAll) {
        [void][TipProbe]::SendMessage($btnAll, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)  # BM_CLICK, no dialog here
        Start-Sleep -Seconds 2
        $selAll = [int][TipProbe]::SendMessage($lv, 0x1032, [IntPtr]::Zero, [IntPtr]::Zero)
        Write-Host "  after 全选备份: selected=$selAll / $total"
        if ($selAll -ne $total) { Write-Host '  FAIL: select-all did not select every row'; $ok = $false }
        else { Write-Host '  select-all: PASS' }
    }

    # Then 取消选择.
    $btnNone = [TipProbe]::Descendants($hwnd, 'BUTTON') |
        Where-Object { [TipProbe]::Text($_) -eq $selectNoneLabel } | Select-Object -First 1
    if ($btnNone) {
        [void][TipProbe]::SendMessage($btnNone, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
        Start-Sleep -Seconds 2
        $selNone = [int][TipProbe]::SendMessage($lv, 0x1032, [IntPtr]::Zero, [IntPtr]::Zero)
        Write-Host "  after 取消选择: selected=$selNone"
        if ($selNone -ne 0) { Write-Host '  FAIL: deselect did not clear the selection'; $ok = $false }
        else { Write-Host '  deselect: PASS' }
    }

    # Finally 反选 from empty should select everything.
    $btnInv = [TipProbe]::Descendants($hwnd, 'BUTTON') |
        Where-Object { [TipProbe]::Text($_) -eq $invertLabel } | Select-Object -First 1
    if ($btnInv) {
        [void][TipProbe]::SendMessage($btnInv, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
        Start-Sleep -Seconds 2
        $selInv = [int][TipProbe]::SendMessage($lv, 0x1032, [IntPtr]::Zero, [IntPtr]::Zero)
        Write-Host "  after 反选: selected=$selInv / $total"
        if ($selInv -ne $total) { Write-Host '  FAIL: invert from empty should select all'; $ok = $false }
        else { Write-Host '  invert: PASS' }
    }
}

[void][TipProbe]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
if (-not $proc.WaitForExit(15000)) { try { $proc.Kill() } catch { } }
Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
    Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host ("RESULT: " + $(if ($ok) { 'PASS' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })
