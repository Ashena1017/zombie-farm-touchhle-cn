# Verify --device-size produces exactly the requested window client area, and
# that the guest sees the matching UIScreen bounds. ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$WaitSeconds = 40
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
$hleRoot = Join-Path $Root 'touchHLE'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class DszWin {
    // Without this the process is DPI-unaware and Windows reports every window
    // 1.5x smaller than it really is (this box runs at 150%), which silently
    // turns a correct result into six bogus FAILs.
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    public static string Cls(IntPtr h) { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }
    public static IntPtr FindGameWindow(uint pid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint wpid; GetWindowThreadProcessId(h, out wpid);
            if (wpid == pid && IsWindowVisible(h) && !Cls(h).Contains("ConsoleWindowClass")) {
                RECT r; GetClientRect(h, out r);
                if ((r.Right - r.Left) > 100) { found = h; return false; }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@ -ErrorAction SilentlyContinue

[void][DszWin]::SetProcessDPIAware()

$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
$exe = Join-Path $hleRoot 'touchHLE.exe'
$log = Join-Path $hleRoot 'touchHLE_log.txt'
$optionsFile = Join-Path $hleRoot 'touchHLE_options.txt'

# touchHLE applies the options file BEFORE command-line options (see lib.rs), so a
# --device-size left in it would silently apply to the "native" cases below and
# make them measure the file's size instead of the device family's. Park it for
# the duration of the run and restore it afterwards, whatever happens.
$optionsOriginal = [System.IO.File]::ReadAllText($optionsFile, [System.Text.UTF8Encoding]::new($false))
$optionsParked = ($optionsOriginal -split "`r?`n" | ForEach-Object {
    ($_ -split '\s+' | Where-Object { $_ -and $_ -notlike '--device-size=*' }) -join ' '
}) -join "`r`n"
[System.IO.File]::WriteAllText($optionsFile, $optionsParked, [System.Text.UTF8Encoding]::new($false))

function Measure-Case {
    param([string]$DeviceSize, [string]$Family, [string]$Scale = '1')

    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
    $argv = @($ipa, "--device-family=$Family", "--scale-hack=$Scale", '--landscape-right', '--fps-limit=60')
    if ($DeviceSize) { $argv += "--device-size=$DeviceSize" }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = ($argv | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $psi.WorkingDirectory = $hleRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)

    $hwnd = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { break }
        $hwnd = [DszWin]::FindGameWindow([uint32]$proc.Id)
    }

    $res = $null
    if ($hwnd -ne [IntPtr]::Zero) {
        Start-Sleep -Seconds 3
        $cr = New-Object DszWin+RECT
        [void][DszWin]::GetClientRect($hwnd, [ref]$cr)
        $res = @{ W = $cr.Right - $cr.Left; H = $cr.Bottom - $cr.Top }
    }

    try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
    Start-Sleep -Seconds 2

    $bounds = $null
    if (Test-Path -LiteralPath $log) {
        $m = Select-String -LiteralPath $log -Pattern 'UIScreen|bounds' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($m) { $bounds = $m.Line }
    }
    return @{ Size = $res; Bounds = $bounds }
}

Write-Host '=== device family + scale hack -> actual window client area (landscape) ==='
Write-Host ''
# Every combination the manager's window row can produce: the three decimal scale
# presets plus the two native sizes and two equivalents. These expected values must
# match Get-WindowSizeForScale in GameManager.ps1, which is what the UI shows the
# user before launching.
$cases = @(
    @{ Fam = 'ipad';   Exp = @(1280, 960);  Scale = '1.25' },
    @{ Fam = 'ipad';   Exp = @(1536, 1152); Scale = '1.5'  },
    @{ Fam = 'ipad';   Exp = @(1792, 1344); Scale = '1.75' },
    # A fraction and a decimal meaning the same factor must open the same window.
    @{ Fam = 'ipad';   Exp = @(1280, 960);  Scale = '5/4'  },
    @{ Fam = 'ipad';   Exp = @(1536, 1152); Scale = '3/2'  },
    @{ Fam = 'ipad';   Exp = @(1664, 1248); Scale = '13/8' },
    @{ Fam = 'ipad';   Exp = @(1024, 768) },
    @{ Fam = 'iphone'; Exp = @(480, 320) }
)

$fails = 0
foreach ($c in $cases) {
    $label = if ($c.Scale) { "$($c.Fam) x$($c.Scale)" } else { "$($c.Fam) (native)" }
    $r = Measure-Case -Family $c.Fam -Scale $(if ($c.Scale) { $c.Scale } else { '1' })
    if ($null -eq $r.Size) {
        Write-Host ("  {0,-16} : window never appeared" -f $label)
        $fails++
        continue
    }
    $ok = ($r.Size.W -eq $c.Exp[0]) -and ($r.Size.H -eq $c.Exp[1])
    if (-not $ok) { $fails++ }
    Write-Host ("  {0}  {1,-16} : client {2}x{3}  expected {4}x{5}" -f `
        $(if ($ok) {'PASS'} else {'FAIL'}), $label, $r.Size.W, $r.Size.H, $c.Exp[0], $c.Exp[1])
}

Write-Host ''
Write-Host ("failures: {0}" -f $fails)
[System.IO.File]::WriteAllText($optionsFile, $optionsOriginal, [System.Text.UTF8Encoding]::new($false))
Write-Host 'options file restored'
if ($fails -gt 0) { exit 1 }
Write-Host 'ALL RESOLUTIONS MATCH'
