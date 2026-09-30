$root = (Split-Path -Parent $PSScriptRoot)
# Probe --device-size argument validation without launching a window.
# Uses [Process]::Start (Start-Process crashes on this machine due to NO_PROXY).
$ErrorActionPreference = 'Continue'
$hleRoot = "$root\touchHLE"
$exe = Join-Path $hleRoot 'touchHLE.exe'
$ipa = "$root\zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"

function Try-Arg([string]$extra) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = ('"{0}" {1} --headless' -f $ipa, $extra)
    $psi.WorkingDirectory = $hleRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    if (-not $p.WaitForExit(15000)) { try { $p.Kill() } catch {} ; return @{ Arg = $extra; Code = 'timeout'; Err = '' } }
    $err = $p.StandardError.ReadToEnd()
    $out = $p.StandardOutput.ReadToEnd()
    return @{ Arg = $extra; Code = $p.ExitCode; Err = (($err + "`n" + $out).Trim()) }
}

Write-Host '=== --device-size argument handling ==='
foreach ($a in @('--device-size=1080x720', '--device-size=2160x1440', '--device-size=bogus',
                 '--device-size=1280', '--device-size=0x720', '--device-size=99999x99999')) {
    $r = Try-Arg $a
    $first = ($r.Err -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
    Write-Host ("  {0,-28} exit={1,-8} {2}" -f $a, $r.Code, $first)
}
