# Fetch the exact upstream commit the user's touchHLE.exe was built from.
#
# The binary reports "touchHLE fa3d095", and fa3d095 is a real commit in
# github.com/touchHLE/touchHLE ("Fix Zombie Farm action manager corruption",
# 2026-08-19) that is NOT on the trunk line. Cloning trunk therefore gives a
# tree without the Zombie Farm adaptation, which is why a trunk build crashes on
# the app.
#
# This fetches fa3d095 into touchHLE-fork so its source can be inspected and
# rebuilt with our run-loop change.
$ErrorActionPreference = 'Continue'

$root = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

$dst  = Join-Path $hleRoot 'touchHLE-fork'
$log  = Join-Path $root '_analysis\_fork_fetch.log'
$sha  = 'fa3d09511d471f505e41abed7c535e4dfbd7c59c'

function Log([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
}
Set-Content -LiteralPath $log -Value "fork fetch started $(Get-Date -Format o)" -Encoding utf8

function Run([string]$exe, [string[]]$argv, [string]$tag) {
    $tmp = Join-Path $env:TEMP "fork_$tag.out"
    & $exe @argv *> $tmp
    $code = $LASTEXITCODE
    if (Test-Path $tmp) {
        Get-Content -LiteralPath $tmp -Tail 5 -ErrorAction SilentlyContinue |
            ForEach-Object { Log "    | $_" }
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
    Log "  $exe $($argv -join ' ') => exit=$code"
    return $code
}

New-Item -ItemType Directory -Force -Path $dst | Out-Null
Push-Location $dst
try {
    if (-not (Test-Path (Join-Path $dst '.git'))) {
        [void](Run 'git' @('init','-q') 'init')
        [void](Run 'git' @('remote','add','origin','https://github.com/touchHLE/touchHLE.git') 'remote')
    } else {
        Log 'already a git repo, reusing'
    }
    # Fetch just that one commit (GitHub allows fetching arbitrary SHAs).
    [void](Run 'git' @('fetch','--depth','1','origin',$sha) 'fetch')
    [void](Run 'git' @('checkout','-q','FETCH_HEAD') 'co')

    $head = (& git rev-parse HEAD 2>$null)
    Log "HEAD = $head"
    Log "--- last commit ---"
    & git log -1 --format='%H%n%an%n%ad%n%s' 2>&1 | ForEach-Object { Log "  $_" }

    Log '--- does this tree contain the Zombie Farm adaptation? ---'
    $hits = Select-String -Path (Join-Path $dst 'src\*.rs'),(Join-Path $dst 'src\**\*.rs') `
        -Pattern 'ZombieFarm workaround|zombie_farm|Zombie Farm' -ErrorAction SilentlyContinue
    Log "  matches in src/: $(($hits | Measure-Object).Count)"
    $hits | Select-Object -First 12 | ForEach-Object {
        Log ("   {0}:{1}" -f ($_.Path -replace [regex]::Escape("$dst\"),''), $_.LineNumber)
    }

    Log '--- .gitmodules (pins may differ from trunk) ---'
    if (Test-Path (Join-Path $dst '.gitmodules')) {
        Get-Content (Join-Path $dst '.gitmodules') | ForEach-Object { Log "  $_" }
    }
    Log '--- submodule SHAs git records for this commit ---'
    & git ls-tree HEAD vendor 2>&1 | ForEach-Object { Log "  $_" }
} finally { Pop-Location }
Log 'fork fetch DONE'
