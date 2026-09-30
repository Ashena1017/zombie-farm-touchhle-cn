# One bounded run that answers two questions about the candidate fix
# (`--device-family=iphone --scale-hack=4`, i.e. a 1920x1280 window):
#
#   1. Does the FARM screen lay out correctly (bottom HUD visible, no cropping)?
#      The title screen was already verified; the farm is what the user reported.
#   2. Does wheel zoom-in still work? -setZoomOutAmount:'s upper clamp is chosen
#      by `winSize.width <= 480` (see _zoom_clamp3.py): branch A (<=480) caps at
#      1.0, branch B (>480) allows 2.0. winSize is the LOGICAL width, and
#      scale-hack does not change it - so an iPhone-family window is 480 wide
#      logically and would take branch A, capping zoom-in at the neutral 1.0.
#      That would be a silent regression of the wheel zoom the user confirmed
#      working, so it gets measured rather than assumed.
#
# Notes:
#  * stdout/stderr are NOT redirected: an unread pipe buffer would block the game.
#  * The save sandbox is snapshotted and restored, so real progress is safe.
#  * ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$WaitSeconds = 60,
    [int]$FarmSeconds = 25,
    [int]$UpNotches = 6,
    [int]$DownNotches = 6,
    [string]$Fam = 'iphone',
    # Scale hack factor: an integer ("2"), a decimal ("1.5") or a fraction
    # ("3/2"). Kept as a string because fractional scales are supported.
    [string]$Scale = '4',
    # Optional --device-size=WxH. Note this sets the LOGICAL canvas, so a value
    # near the native size keeps the layout native while a value just over the
    # game's 480-point zoom threshold may re-enable wheel zoom-in.
    [string]$DeviceSize = '',
    # Prefix for the saved screenshots, so several runs can coexist.
    [string]$Tag = 'zoomfix'
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
$hleRoot = Join-Path $Root 'touchHLE'
$outDir = Join-Path $Root '_analysis\perf'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$progress = Join-Path $outDir 'zoomfix_progress.txt'
[System.IO.File]::WriteAllText($progress, "start`r`n", [System.Text.UTF8Encoding]::new($false))

function Note([string]$m) {
    $line = "{0}  {1}" -f (Get-Date).ToString('HH:mm:ss'), $m
    [System.IO.File]::AppendAllText($progress, $line + "`r`n", [System.Text.UTF8Encoding]::new($false))
    Write-Host $line
}

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
using System.Drawing.Imaging;
public class ZfWin {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
    public delegate bool EnumProc(IntPtr h, IntPtr p);

    public static string Cls(IntPtr h) { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }

    public static IntPtr FindGame(uint pid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint w; GetWindowThreadProcessId(h, out w);
            if (w == pid && IsWindowVisible(h) && !Cls(h).Contains("ConsoleWindowClass")) {
                RECT r; GetClientRect(h, out r);
                if ((r.Right - r.Left) > 100 && (r.Bottom - r.Top) > 100) { found = h; return false; }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static int Cw(IntPtr h) { RECT r; GetClientRect(h, out r); return r.Right - r.Left; }
    public static int Ch(IntPtr h) { RECT r; GetClientRect(h, out r); return r.Bottom - r.Top; }

    public static string ShotClient(IntPtr h, string path) {
        RECT wr; GetWindowRect(h, out wr);
        int ww = wr.Right - wr.Left, wh = wr.Bottom - wr.Top;
        if (ww <= 0 || wh <= 0) return "bad window rect";
        POINT p = new POINT(); p.X = 0; p.Y = 0;
        ClientToScreen(h, ref p);
        int ox = p.X - wr.Left, oy = p.Y - wr.Top;
        int cw = Cw(h), ch = Ch(h);
        using (var full = new Bitmap(ww, wh))
        using (var g = Graphics.FromImage(full)) {
            IntPtr hdc = g.GetHdc();
            bool ok = PrintWindow(h, hdc, 2);
            g.ReleaseHdc(hdc);
            if (!ok) return "PrintWindow failed";
            int cropW = Math.Min(cw, ww - ox), cropH = Math.Min(ch, wh - oy);
            if (cropW <= 0 || cropH <= 0) return "bad crop";
            using (var crop = new Bitmap(cropW, cropH))
            using (var gc = Graphics.FromImage(crop)) {
                gc.DrawImage(full, new Rectangle(0, 0, cropW, cropH),
                             new Rectangle(ox, oy, cropW, cropH), GraphicsUnit.Pixel);
                crop.Save(path, ImageFormat.Png);
            }
            return "ok " + cropW + "x" + cropH;
        }
    }

    // Tap at a fraction of the client area (touchHLE feeds these to the guest).
    public static void Tap(IntPtr h, double fx, double fy) {
        RECT r; GetClientRect(h, out r);
        int w = r.Right - r.Left, ht = r.Bottom - r.Top;
        int x = (int)(w * fx), y = (int)(ht * fy);
        IntPtr lp = (IntPtr)((y << 16) | (x & 0xFFFF));
        PostMessage(h, 0x0200, IntPtr.Zero, lp);
        PostMessage(h, 0x0201, (IntPtr)1, lp);
        PostMessage(h, 0x0202, IntPtr.Zero, lp);
    }

    public static void Wheel(IntPtr h, int notches) {
        RECT r; GetClientRect(h, out r);
        int x = (r.Right - r.Left) / 2, y = (r.Bottom - r.Top) / 2;
        IntPtr lp = (IntPtr)((y << 16) | (x & 0xFFFF));
        int step = notches > 0 ? 1 : -1;
        for (int i = 0; i < Math.Abs(notches); i++) {
            int d = 120 * step;
            if (d < 0) d += 65536;
            PostMessage(h, 0x020A, (IntPtr)(d * 65536), lp);
            System.Threading.Thread.Sleep(140);
        }
    }
}
'@ -ErrorAction SilentlyContinue

[void][ZfWin]::SetProcessDPIAware()

$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
$exe = Join-Path $hleRoot 'touchHLE.exe'
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$optionsFile = Join-Path $hleRoot 'touchHLE_options.txt'
$log = Join-Path $hleRoot 'touchHLE_log.txt'
$snap = Join-Path $env:TEMP ('zfz_' + [Guid]::NewGuid().ToString('N'))

Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force
# Park the options file: it is applied BEFORE command-line options, so a
# --device-size in it would silently override this experiment.
$optionsOriginal = [System.IO.File]::ReadAllText($optionsFile, [System.Text.UTF8Encoding]::new($false))
$stripped = ($optionsOriginal -split "`r?`n" | ForEach-Object {
    ($_ -split '\s+' | Where-Object { $_ -and $_ -notlike '--device-size=*' }) -join ' '
}) -join "`r`n"
[System.IO.File]::WriteAllText($optionsFile, $stripped, [System.Text.UTF8Encoding]::new($false))
Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue

$proc = $null
try {
    $argv = @($ipa, "--device-family=$Fam", "--scale-hack=$Scale", '--landscape-right', '--fps-limit=60')
    if ($DeviceSize) { $argv += "--device-size=$DeviceSize" }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = ($argv | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $psi.WorkingDirectory = $hleRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $proc = [System.Diagnostics.Process]::Start($psi)
    Note ("launched $Fam x$Scale")

    $hwnd = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { break }
        $hwnd = [ZfWin]::FindGame([uint32]$proc.Id)
    }
    if ($hwnd -eq [IntPtr]::Zero) {
        Note 'FAIL: no window'
    } else {
        Note ("window {0}x{1}" -f [ZfWin]::Cw($hwnd), [ZfWin]::Ch($hwnd))
        Start-Sleep -Seconds 6
        $live = [ZfWin]::FindGame([uint32]$proc.Id)
        if ($live -ne [IntPtr]::Zero) { $hwnd = $live }
        Note ("title  " + [ZfWin]::ShotClient($hwnd, (Join-Path $outDir ($Tag + '_0_title.png'))))

        # 开始游戏 sits at the horizontal centre, just below the middle.
        [ZfWin]::Tap($hwnd, 0.5, 0.53)
        Start-Sleep -Seconds 4
        [ZfWin]::Tap($hwnd, 0.5, 0.53)
        Start-Sleep -Seconds $FarmSeconds
        Note ("farm   " + [ZfWin]::ShotClient($hwnd, (Join-Path $outDir ($Tag + '_1_farm.png'))))

        [ZfWin]::Wheel($hwnd, $UpNotches)
        Start-Sleep -Seconds 2
        Note ("zoom-in  " + [ZfWin]::ShotClient($hwnd, (Join-Path $outDir ($Tag + '_2_zoomin.png'))))
        [ZfWin]::Wheel($hwnd, -$DownNotches)
        Start-Sleep -Seconds 2
        Note ("zoom-out " + [ZfWin]::ShotClient($hwnd, (Join-Path $outDir ($Tag + '_3_zoomout.png'))))
    }
} finally {
    if ($proc) { try { if (-not $proc.HasExited) { $proc.Kill() } } catch {} }
    Start-Sleep -Seconds 3
    [System.IO.File]::WriteAllText($optionsFile, $optionsOriginal, [System.Text.UTF8Encoding]::new($false))
    Note 'options restored'
    Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
    Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
    Note 'save sandbox restored'
}

Note '=== ZombieFarm zoom log lines ==='
if (Test-Path -LiteralPath $log) {
    Copy-Item -LiteralPath $log -Destination (Join-Path $outDir ($Tag + '.touchhle.log')) -Force
    $hits = Select-String -LiteralPath $log -Pattern 'ZombieFarm zoom'
    if ($hits) { $hits | ForEach-Object { Note ("  " + $_.Line) } } else { Note '  (none)' }
} else { Note '  (no log)' }
Note 'done'
