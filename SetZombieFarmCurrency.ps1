[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(0, [Int32]::MaxValue)]
    [Int32]$Brains,

    [Parameter(Mandatory = $true)]
    [ValidateRange(0, [Int32]::MaxValue)]
    [Int32]$Gold,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$SavePath
)

$ErrorActionPreference = 'Stop'

function Find-BytePattern {
    param(
        [Parameter(Mandatory = $true)]
        [byte[]]$Data,

        [Parameter(Mandatory = $true)]
        [byte[]]$Pattern
    )

    $matches = [System.Collections.Generic.List[int]]::new()
    if ($Pattern.Length -eq 0 -or $Data.Length -lt $Pattern.Length) {
        return $matches.ToArray()
    }

    $lastStart = $Data.Length - $Pattern.Length
    for ($offset = 0; $offset -le $lastStart; $offset++) {
        if ($Data[$offset] -ne $Pattern[0]) {
            continue
        }

        $matched = $true
        for ($index = 1; $index -lt $Pattern.Length; $index++) {
            if ($Data[$offset + $index] -ne $Pattern[$index]) {
                $matched = $false
                break
            }
        }

        if ($matched) {
            $matches.Add($offset)
        }
    }

    return $matches.ToArray()
}

function Get-CurrencyLayout {
    param(
        [Parameter(Mandatory = $true)]
        [byte[]]$Data
    )

    if ($Data.Length -lt 4 -or [BitConverter]::ToInt32($Data, 0) -ne 14) {
        throw 'This is not a supported Zombie Farm/ZFR version-14 binary save file.'
    }

    # Version-14 saves contain variable-length profile data before this
    # serialized marker. Currency fields have stable positions relative to it.
    [byte[]]$profileMarker = @(
        0x01, 0x09, 0x00, 0x00, 0x00,
        0x55, 0x4E, 0x44, 0x45, 0x46, 0x49, 0x4E, 0x45, 0x44
    )
    $markerOffsets = @(Find-BytePattern -Data $Data -Pattern $profileMarker)
    if ($markerOffsets.Count -ne 1) {
        throw "Could not identify one unique version-14 player-data block (found $($markerOffsets.Count)). The save was not changed."
    }

    $markerOffset = $markerOffsets[0]
    $goldOffset = $markerOffset + 0x46
    $brainOffset = $markerOffset + 0x4A
    $requiredLength = $markerOffset + 0x5E
    if ($Data.Length -lt $requiredLength) {
        throw 'The player-data block is truncated. Restore an unmodified backup before trying again.'
    }

    # These fields surround the currency values and are invariant across the
    # new-game and mature saves. The bounded indexes also catch files damaged
    # by the old fixed-offset script before another write can make things worse.
    $layoutVersion = [BitConverter]::ToInt32($Data, $markerOffset + 0x42)
    $reservedValue = [BitConverter]::ToInt32($Data, $markerOffset + 0x52)
    $firstIndex = [BitConverter]::ToInt32($Data, $markerOffset + 0x56)
    $secondIndex = [BitConverter]::ToInt32($Data, $markerOffset + 0x5A)
    if (
        $layoutVersion -ne 4 -or
        $reservedValue -ne 0 -or
        $firstIndex -lt 0 -or $firstIndex -gt 1000000 -or
        $secondIndex -lt 0 -or $secondIndex -gt 1000000
    ) {
        throw 'The save player-data block failed validation. It may already be damaged; restore an unmodified backup. The save was not changed.'
    }

    $oldGold = [BitConverter]::ToInt32($Data, $goldOffset)
    $oldBrains = [BitConverter]::ToInt32($Data, $brainOffset)
    if ($oldGold -lt 0 -or $oldBrains -lt 0) {
        throw 'The current currency values are invalid. Restore an unmodified backup before trying again.'
    }

    return [PSCustomObject]@{
        MarkerOffset = $markerOffset
        GoldOffset = $goldOffset
        BrainOffset = $brainOffset
        Gold = $oldGold
        Brains = $oldBrains
    }
}

function Get-UniqueBackupPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $candidate = "$Path.bak-$stamp"
    $suffix = 1
    while (Test-Path -LiteralPath $candidate) {
        $candidate = "$Path.bak-$stamp-$suffix"
        $suffix++
    }
    return $candidate
}

if ([string]::IsNullOrWhiteSpace($SavePath)) {
    # The emulator lives in its own folder now (the tree mirrors the shipped
    # ./Release layout); fall back to the flat layout so a copy of this script
    # dropped next to an older installation still works.
    $hleRoot = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'touchHLE\touchHLE.exe')) {
        Join-Path $PSScriptRoot 'touchHLE'
    } else {
        $PSScriptRoot
    }
    # Prefer the current ZFR save, but also support the two folder names used
    # by earlier builds when this script is copied to another installation.
    $defaultSaveCandidates = @(
        (Join-Path $hleRoot 'touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents\saveGame.bin2'),
        (Join-Path $hleRoot 'touchHLE_sandbox\com.playforge.ZombieFarmChinese\Documents\saveGame.bin2'),
        (Join-Path $hleRoot 'touchHLE_sandbox\com.playforge.ZFR.LZ54D2GT3D\Documents\saveGame.bin2')
    )
    $SavePath = $defaultSaveCandidates | Where-Object {
        Test-Path -LiteralPath $_ -PathType Leaf
    } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($SavePath)) {
        throw 'Save file not found. Use -SavePath to specify the Documents\saveGame.bin2 file.'
    }
} else {
    if (-not [System.IO.Path]::IsPathRooted($SavePath)) {
        $SavePath = Join-Path (Get-Location).Path $SavePath
    }
    $SavePath = [System.IO.Path]::GetFullPath($SavePath)
}

if (Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue) {
    throw 'Close touchHLE before changing the save file.'
}

if (-not (Test-Path -LiteralPath $SavePath -PathType Leaf)) {
    throw "Save file not found: $SavePath"
}

$data = [System.IO.File]::ReadAllBytes($SavePath)
$layout = Get-CurrencyLayout -Data $data

Write-Host "Save:    $SavePath"
Write-Host ('Layout:  marker=0x{0:X}, Gold=0x{1:X}, Brains=0x{2:X}' -f $layout.MarkerOffset, $layout.GoldOffset, $layout.BrainOffset)
Write-Host "Current: Brains=$($layout.Brains), Gold=$($layout.Gold)"
Write-Host "New:     Brains=$Brains, Gold=$Gold"

if ($PSCmdlet.ShouldProcess($SavePath, 'update brains and gold')) {
    [byte[]]$updatedData = $data.Clone()
    [BitConverter]::GetBytes($Gold).CopyTo($updatedData, $layout.GoldOffset)
    [BitConverter]::GetBytes($Brains).CopyTo($updatedData, $layout.BrainOffset)

    $backupPath = Get-UniqueBackupPath -Path $SavePath
    $saveDirectory = [System.IO.Path]::GetDirectoryName($SavePath)
    $saveName = [System.IO.Path]::GetFileName($SavePath)
    $tempPath = Join-Path $saveDirectory ('.{0}.tmp-{1}' -f $saveName, [Guid]::NewGuid().ToString('N'))

    try {
        [System.IO.File]::WriteAllBytes($tempPath, $updatedData)
        $tempData = [System.IO.File]::ReadAllBytes($tempPath)
        $tempLayout = Get-CurrencyLayout -Data $tempData
        if (
            $tempData.Length -ne $data.Length -or
            $tempLayout.MarkerOffset -ne $layout.MarkerOffset -or
            $tempLayout.Gold -ne $Gold -or
            $tempLayout.Brains -ne $Brains
        ) {
            throw 'Verification of the temporary save failed. The original save was not changed.'
        }

        # File.Replace atomically swaps the validated temporary file into
        # place and writes the old file to the requested backup path.
        [System.IO.File]::Replace($tempPath, $SavePath, $backupPath)
        $tempPath = $null

        $writtenData = [System.IO.File]::ReadAllBytes($SavePath)
        $writtenLayout = Get-CurrencyLayout -Data $writtenData
        if (
            $writtenData.Length -ne $data.Length -or
            $writtenLayout.MarkerOffset -ne $layout.MarkerOffset -or
            $writtenLayout.Gold -ne $Gold -or
            $writtenLayout.Brains -ne $Brains
        ) {
            Copy-Item -LiteralPath $backupPath -Destination $SavePath -Force
            throw 'Post-write verification failed. The backup was restored automatically.'
        }

        Write-Host "Updated save. Backup: $backupPath"
    } finally {
        if ($null -ne $tempPath -and (Test-Path -LiteralPath $tempPath)) {
            Remove-Item -LiteralPath $tempPath -Force
        }
    }
}
