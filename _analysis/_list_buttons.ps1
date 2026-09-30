$root = (Split-Path -Parent $PSScriptRoot)
# List every Button child (recursively) of the GameManager main window, with its
# exact text and class, to debug why FindButtonByText missed the skip button.
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class BtnEnum {
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    public static IntPtr FindMain(uint wantPid, string needle) {
        IntPtr best = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == wantPid && IsWindowVisible(h)) {
                var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512);
                if (sb.ToString().Contains(needle)) best = h;
            }
            return true;
        }, IntPtr.Zero);
        return best;
    }
}
'@
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' + (Join-Path $Root 'GameManager.ps1') + '"'
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)
$main = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds(40)
while ((Get-Date) -lt $deadline -and $main -eq [IntPtr]::Zero) {
    $main = [BtnEnum]::FindMain([uint32]$proc.Id, 'Zombie Farm')
    if ($main -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}
if ($main -eq [IntPtr]::Zero) { Write-Host 'no main window'; $proc.Kill(); exit 1 }
Start-Sleep -Seconds 4
Write-Host "main hwnd=$main; buttons:"
$cb = $null
$cb = [BtnEnum+EnumProc]{
    param($h, $p)
    $cls = New-Object System.Text.StringBuilder 64
    [void][BtnEnum]::GetClassNameW($h, $cls, 64)
    $t = New-Object System.Text.StringBuilder 256
    [void][BtnEnum]::GetWindowTextW($h, $t, 256)
    if ($t.Length -gt 0) {
        $cp = ($t.ToString().ToCharArray() | ForEach-Object { '{0:X4}' -f [int]$_ }) -join ' '
        Write-Host ("  [{0}]  '{1}'  cps=[{2}]" -f $cls.ToString(), $t.ToString(), $cp)
    }
    [void][BtnEnum]::EnumChildWindows($h, $cb, [IntPtr]::Zero)
    return $true
}
[void][BtnEnum]::EnumChildWindows($main, $cb, [IntPtr]::Zero)
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class WM{[DllImport("user32.dll")]public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);}'
[void][WM]::PostMessage($main, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
if (-not $proc.WaitForExit(8000)) { $proc.Kill() }
