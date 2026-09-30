# A/B probe, take 2: does the game's layout follow the LOGICAL canvas or the window?
#
# Take 1 captured the browser instead of the game: SetForegroundWindow fails when
# the caller is not already the foreground process, so CopyFromScreen grabbed
# whatever was on top. This version uses PrintWindow(PW_RENDERFULLCONTENT), which
# renders the window's own content into a DC regardless of z-order, and crops the
# client area out of the full window image using the real border offsets.
#
#   A  iphone, scale-hack=1            -> window  480x320  (known-good reference)
#   B  iphone, scale-hack=3            -> window 1440x960  (bigger WINDOW, native logical size)
#   C  iphone, device-size=1620x1080   -> window 1620x1080 (bigger LOGICAL canvas, current setting)
#
# If B matches A and C does not, the layout is driven by the logical size - i.e.
# the game only composes correctly for its native point sizes.
#
# The options file is applied BEFORE command-line options (lib.rs), so any
# --device-size left in it would leak into A and B; it is parked and restored.
# The save sandbox is snapshotted and restored too.
#
# ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$WaitSeconds = 45,
    [int]$SettleSeconds = 7
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
$hleRoot = Join-Path $Root 'touchHLE'
$outDir = Join-Path $Root '_analysis\perf'
$progress = Join-Path $outDir 'pw2_progress.txt'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
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
public class PwWin {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
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

    // Render the window via PrintWindow, then crop to the client area so the
    // result is directly comparable across sizes (frame width must not skew the
    // downscaled comparison).
    // Returns "ok WxH" or an error string.
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
            bool ok = PrintWindow(h, hdc, 2);   // PW_RENDERFULLCONTENT
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

    // Mean and spread of sampled pixels: a blank/black capture has ~zero spread,
    // which would otherwise look like a successful shot.
    public static string Stats(string path) {
        using (var bmp = new Bitmap(path)) {
            long sum = 0, sum2 = 0, n = 0;
            for (int y = 0; y < bmp.Height; y += 7)
                for (int x = 0; x < bmp.Width; x += 7) {
                    Color c = bmp.GetPixel(x, y);
                    int v = (c.R + c.G + c.B) / 3;
                    sum += v; sum2 += (long)v * v; n++;
                }
            double mean = (double)sum / n;
            double var = (double)sum2 / n - mean * mean;
            return string.Format("mean {0:F1} sd {1:F1}", mean, Math.Sqrt(Math.Max(var, 0)));
        }
    }
}
'@ -ErrorAction SilentlyContinue

[void][PwWin]::SetProcessDPIAware()

$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
$exe = Join-Path $hleRoot 'touchHLE.exe'
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$optionsFile = Join-Path $hleRoot 'touchHLE_options.txt'
$snap = Join-Path $env:TEMP ('pwz_' + [Guid]::NewGuid().ToString('N'))

Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force
$optionsOriginal = [System.IO.File]::ReadAllText($optionsFile, [System.Text.UTF8Encoding]::new($false))
$stripped = ($optionsOriginal -split "`r?`n" | ForEach-Object {
    ($_ -split '\s+' | Where-Object { $_ -and $_ -notlike '--device-size=*' }) -join ' '
}) -join "`r`n"
[System.IO.File]::WriteAllText($optionsFile, $stripped, [System.Text.UTF8Encoding]::new($false))
Note ("options parked; device-size still present: " + ($stripped -match '--device-size='))

$cases = @(
    @{ Tag = 'R_iphone_x1_480x320';    Extra = @('--device-family=iphone', '--scale-hack=1') },
    @{ Tag = 'X2_iphone_960x640';      Extra = @('--device-family=iphone', '--scale-hack=2') },
    @{ Tag = 'X3_iphone_1440x960';     Extra = @('--device-family=iphone', '--scale-hack=3') },
    @{ Tag = 'X4_iphone_1920x1280';    Extra = @('--device-family=iphone', '--scale-hack=4') },
    @{ Tag = 'P_ipad_x1_1024x768';     Extra = @('--device-family=ipad', '--scale-hack=1') }
)

try {
    foreach ($c in $cases) {
        $argv = @($ipa, '--landscape-right', '--fps-limit=60') + $c.Extra
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $exe
        $psi.Arguments = ($argv | ForEach-Object { '"' + $_ + '"' }) -join ' '
        $psi.WorkingDirectory = $hleRoot
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true

        $proc = $null
        try {
            $proc = [System.Diagnostics.Process]::Start($psi)
            $hwnd = [IntPtr]::Zero
            $deadline = (Get-Date).AddSeconds($WaitSeconds)
            while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
                Start-Sleep -Milliseconds 500
                if ($proc.HasExited) { break }
                $hwnd = [PwWin]::FindGame([uint32]$proc.Id)
            }
            if ($hwnd -eq [IntPtr]::Zero) { Note ("  {0,-20} : no window" -f $c.Tag); continue }
            Start-Sleep -Seconds $SettleSeconds
            $live = [PwWin]::FindGame([uint32]$proc.Id)
            if ($live -ne [IntPtr]::Zero) { $hwnd = $live }

            $path = Join-Path $outDir ("pw2_" + $c.Tag + ".png")
            $res = [PwWin]::ShotClient($hwnd, $path)
            $st = if (Test-Path -LiteralPath $path) { [PwWin]::Stats($path) } else { 'no file' }
            Note ("  {0,-20} : client {1,5}x{2,-5} capture={3} [{4}]" -f `
                $c.Tag, [PwWin]::Cw($hwnd), [PwWin]::Ch($hwnd), $res, $st)
        } finally {
            if ($proc) { try { if (-not $proc.HasExited) { $proc.Kill() } } catch {} }
            Start-Sleep -Seconds 2
        }
    }
} finally {
    [System.IO.File]::WriteAllText($optionsFile, $optionsOriginal, [System.Text.UTF8Encoding]::new($false))
    Note 'options restored'
    Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
    Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
    Note 'save sandbox restored'
}
Note 'done'
