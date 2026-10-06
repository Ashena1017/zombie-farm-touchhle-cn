param(
    [ValidateSet('List','Tap','Edit','Shot')][string]$Action = 'List',
    [string]$Text,
    [int]$Index = 0,
    [string]$Value,
    [int]$X = -1,
    [int]$Y = -1,
    [string]$Name = 'android-manager-ui'
)
$ErrorActionPreference = 'Stop'
$adb = 'C:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe'
$device = '127.0.0.1:5557'
$dumpDir = Join-Path $PSScriptRoot 'dumps'
if ($Action -eq 'Shot') {
    & $adb -s $device shell screencap -p /data/local/tmp/zfr-ui.png | Out-Null
    & $adb -s $device pull /data/local/tmp/zfr-ui.png (Join-Path $dumpDir ($Name + '.png'))
    if ($LASTEXITCODE -ne 0) { throw 'Screenshot failed.' }
    exit
}
& $adb -s $device shell uiautomator dump /data/local/tmp/zfr-ui.xml | Out-Null
& $adb -s $device pull /data/local/tmp/zfr-ui.xml (Join-Path $dumpDir ($Name + '.xml')) | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'UI dump failed.' }
[xml]$xml = [IO.File]::ReadAllText((Join-Path $dumpDir ($Name + '.xml')))
$nodes = @($xml.SelectNodes('//node'))
if ($Action -eq 'List') {
    $nodes | Where-Object { $_.text -or $_.class -eq 'android.widget.EditText' } | ForEach-Object {
        '{0} | {1} | enabled={2} | {3}' -f $_.text,$_.class,$_.enabled,$_.bounds
    }
    exit
}
$matches = @(if ($Action -eq 'Edit') {
    @($nodes | Where-Object { $_.class -eq 'android.widget.EditText' })
} else {
    $direct = @($nodes | Where-Object { $_.text -eq $Text -and $_.clickable -eq 'true' })
    if ($direct.Count -gt 0) { $direct } else { @($nodes | Where-Object { $_.text -eq $Text }) }
})
$node = $null
if ($X -ge 0 -and $Y -ge 0) {
    $node = [pscustomobject]@{ text = ''; enabled = 'true'; bounds = "[$X,$Y][$($X+1),$($Y+1)]" }
}
elseif ($matches.Count -gt 0) {
    if ($Index -ge $matches.Count) { throw 'Requested control not found in current UI.' }
    $node = $matches[$Index]
    if ($node.enabled -ne 'true') { throw 'Requested control is disabled.' }
}
else { throw 'Requested control not found in current UI.' }
$bounds = [regex]::Match($node.bounds, '^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$')
if (-not $bounds.Success) { throw 'Invalid control bounds.' }
$logicalX = [int](($bounds.Groups[1].Value -as [int]) + ($bounds.Groups[3].Value -as [int])) / 2
$logicalY = [int](($bounds.Groups[2].Value -as [int]) + ($bounds.Groups[4].Value -as [int])) / 2
$sizeText = (& $adb -s $device shell wm size) -join ' '
$screenSize = [regex]::Match($sizeText, '(\d+)x(\d+)')
if (-not $screenSize.Success) { throw 'Unable to read device screen size.' }
$screenWidth = [int]$screenSize.Groups[1].Value
$screenHeight = [int]$screenSize.Groups[2].Value
$xValues = @(); $yValues = @()
foreach ($entry in $nodes) {
    $rect = [regex]::Match($entry.bounds, '^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$')
    if ($rect.Success) { $xValues += [int]$rect.Groups[3].Value; $yValues += [int]$rect.Groups[4].Value }
}
$xmlMaxX = ($xValues | Measure-Object -Maximum).Maximum
$xmlMaxY = ($yValues | Measure-Object -Maximum).Maximum
if ($xmlMaxX -gt $screenWidth -and $xmlMaxY -le $screenWidth) { $x = $logicalY; $y = $logicalX }
else { $x = $logicalX; $y = $logicalY }
& $adb -s $device shell input tap ([int]$x) ([int]$y)
if ($Action -eq 'Edit') {
    if ($Value -notmatch '^[0-9./]*$') { throw 'Only numeric test values are supported.' }
    & $adb -s $device shell input keyevent 123
    if ($node.text.Length -gt 0) {
        $keys = @(67) * $node.text.Length
        & $adb -s $device shell input keyevent @keys
    }
    if ($Value) { & $adb -s $device shell input text $Value }
}
