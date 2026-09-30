# Run the GL-traced build at --scale-hack=3/2 and report every scaled GL call
# the app makes, plus any render-to-texture allocation.
#
# Question this answers: touchHLE scales glViewport/glScissor and the drawable
# renderbuffer, but it cannot scale a texture the APP allocates. If the app
# renders a scene pass into its own texture and then uses it, the pass runs at
# guest scale into a guest-sized texture while the final composite is at 1.5x -
# exactly the kind of mismatch that makes a glow look detached from the scene.
#
# ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Scale = '3/2',
    [int]$WaitSeconds = 55,
    [int]$FarmSeconds = 22
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
using System.Drawing.Imaging;
public class ZfGl {
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
        POINT p = new POINT(); ClientToScreen(h, ref p);
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
    public static void Tap(IntPtr h, double fx, double fy) {
        RECT r; GetClientRect(h, out r);
        int w = r.Right - r.Left, ht = r.Bottom - r.Top;
        int x = (int)(w * fx), y = (int)(ht * fy);
        IntPtr lp = (IntPtr)((y << 16) | (x & 0xFFFF));
        PostMessage(h, 0x0200, IntPtr.Zero, lp);
        PostMessage(h, 0x0201, (IntPtr)1, lp);
        PostMessage(h, 0x0202, IntPtr.Zero, lp);
    }
}
'@ -ErrorAction SilentlyContinue
[void][ZfGl]::SetProcessDPIAware()

$hleRoot = Join-Path $Root 'touchHLE'
$outDir = Join-Path $Root '_analysis\perf'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
$exe = Join-Path $hleRoot 'touchHLE.exe'
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$optionsFile = Join-Path $hleRoot 'touchHLE_options.txt'
$log = Join-Path $hleRoot 'touchHLE_log.txt'
$snap = Join-Path $env:TEMP ('zfgl_' + [Guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force

$optionsOriginal = [System.IO.File]::ReadAllText($optionsFile, [System.Text.UTF8Encoding]::new($false))
$stripped = ($optionsOriginal -split "`r?`n" | ForEach-Object {
    ($_ -split '\s+' | Where-Object { $_ -and $_ -notlike '--scale-hack=*' -and $_ -notlike '--device-size=*' }) -join ' '
}) -join "`r`n"
[System.IO.File]::WriteAllText($optionsFile, $stripped, [System.Text.UTF8Encoding]::new($false))
Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue

$proc = $null
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = ('"{0}" --device-family=ipad --scale-hack={1} --landscape-right --fps-limit=60' -f $ipa, $Scale)
    $psi.WorkingDirectory = $hleRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    # Windows PowerShell 5.1 leaves ProcessStartInfo.EnvironmentVariables null
    # here, so set the variable in this process and let the child inherit it.
    $env:TOUCHHLE_ZF_GL_TRACE = '1'
    $proc = [System.Diagnostics.Process]::Start($psi)
    Write-Host "launched x$Scale pid $($proc.Id)"

    $hwnd = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { break }
        $hwnd = [ZfGl]::FindGame([uint32]$proc.Id)
    }
    if ($hwnd -eq [IntPtr]::Zero) { Write-Host 'FAIL: no window' } else {
        Start-Sleep -Seconds 4
        [ZfGl]::Tap($hwnd, 0.5, 0.53)
        Start-Sleep -Seconds 3
        [ZfGl]::Tap($hwnd, 0.5, 0.53)
        Start-Sleep -Seconds $FarmSeconds
        Write-Host ("farm shot " + [ZfGl]::ShotClient($hwnd, (Join-Path $outDir ("gltrace_x" + ($Scale -replace '/','_') + "_farm.png"))))
    }
} finally {
    if ($proc) { try { if (-not $proc.HasExited) { $proc.Kill() } } catch {} }
    Start-Sleep -Seconds 3
    [System.IO.File]::WriteAllText($optionsFile, $optionsOriginal, [System.Text.UTF8Encoding]::new($false))
    Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
    Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host '=== render-to-texture candidates (glTexImage2D with NULL data) ==='
if (Test-Path -LiteralPath $log) {
    Copy-Item -LiteralPath $log -Destination (Join-Path $outDir ("gltrace_x" + ($Scale -replace '/','_') + ".log")) -Force
    $rtt = Select-String -LiteralPath $log -Pattern 'NULL data|cannot be scaled|render target'
    if ($rtt) { $rtt | Group-Object Line | Sort-Object Count -Descending | Select-Object -First 15 | ForEach-Object { "  {0,5}x  {1}" -f $_.Count, $_.Name.Trim() } }
    else { Write-Host '  (none - the app never allocates a texture as a render target)' }

    Write-Host ''
    Write-Host '=== guest glViewport calls (guest rect -> host rect) ==='
    $vp = Select-String -LiteralPath $log -Pattern 'glViewport'
    if ($vp) { $vp | Group-Object Line | Sort-Object Count -Descending | Select-Object -First 12 | ForEach-Object { "  {0,5}x  {1}" -f $_.Count, $_.Name.Trim() } }
    else { Write-Host '  (none)' }

    Write-Host ''
    Write-Host '=== framebuffer binds ==='
    $fb = Select-String -LiteralPath $log -Pattern 'glBindFramebufferOES|glFramebufferTexture2DOES'
    if ($fb) { $fb | Group-Object Line | Sort-Object Count -Descending | Select-Object -First 12 | ForEach-Object { "  {0,5}x  {1}" -f $_.Count, $_.Name.Trim() } }
    else { Write-Host '  (none - app never renders to a framebuffer object)' }

    Write-Host ''
    Write-Host '=== screen-size queries the app made ==='
    $q = Select-String -LiteralPath $log -Pattern 'glGetIntegerv\('
    if ($q) { $q | Group-Object Line | Sort-Object Count -Descending | Select-Object -First 12 | ForEach-Object { "  {0,5}x  {1}" -f $_.Count, $_.Name.Trim() } }
    else { Write-Host '  (none)' }

    Write-Host ''
    Write-Host ("log lines total: " + (Get-Content -LiteralPath $log | Measure-Object -Line).Lines)
} else { Write-Host '  (no log)' }
Write-Host 'done'
