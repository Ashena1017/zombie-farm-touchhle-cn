$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $repositoryRoot 'run\windows'

[pscustomobject]@{
    Runtime = $runtimeRoot
    Emulator = Join-Path $runtimeRoot 'touchHLE'
    Ipa = Join-Path $repositoryRoot 'zombie_farm_ipa'
}
