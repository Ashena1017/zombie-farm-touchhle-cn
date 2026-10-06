# Zombie Farm 游戏管理 — WinForms GUI.
#
# Scope: Zombie Farm / ZFR only, which is the single app this project runs.
# Settings live in touchHLE_options.txt on the app's own line -- touchHLE's native
# per-app mechanism -- so they also apply when touchHLE is started some other way,
# and there is one place to look when something seems wrong.
#
# SELF-CONTAINED: every feature is implemented in this file. It does not call
# StartZombieFarmNextHour.ps1 or SetZombieFarmCurrency.ps1; launching, the
# cumulative time offset, reading/writing the save's currency fields, and save
# backup management are all done here. Those two scripts remain for command-line
# and analysis use, but the manager works with them deleted.
#
# Launched by 游戏管理.exe, which is compiled as a GUI-subsystem binary so that no
# console window ("black window") appears. See _analysis\launcher\.
#
#   .\GameManager.ps1                 show the window
#   .\GameManager.ps1 -SelfTest       verify settings + save management, no UI
#   .\GameManager.ps1 -Set k=v,...    write settings headlessly
#   .\GameManager.ps1 -ShowSettings   print the stored settings
#
# This file MUST be saved as UTF-8 *with a BOM*: Windows PowerShell 5.1 decodes a
# BOM-less script using the console ANSI code page, which turns Chinese text into
# byte sequences that can contain a quote character and produce bogus parse
# errors. Run _analysis\_ensure_bom.ps1 after editing.

param(
    [switch]$SelfTest,
    [string[]]$Set,
    [switch]$ShowSettings
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:Root = $PSScriptRoot

# Where touchHLE's own files live.
#
# The release bundle keeps them in a "touchHLE" subfolder (touchHLE.exe,
# touchHLE_dylibs, touchHLE_fonts, touchHLE_sandbox, the options files), while the
# development tree has them next to this script. Both are supported: if the
# subfolder exists it is used, otherwise the root.
#
# This matters because touchHLE resolves its resources from the CURRENT DIRECTORY
# (src/paths.rs returns Path::new(".") on Windows), NOT from the executable's
# location. Launching from the wrong directory panics with
#   Unexpected I/O failure ... "touchHLE_dylibs/libz.1.2.3.dylib"
# so Start-GameProcess sets the working directory explicitly. Verified both ways.
$script:HleDir = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'touchHLE\touchHLE.exe')) {
    Join-Path $PSScriptRoot 'touchHLE'
} else {
    $PSScriptRoot
}

$script:OptionsFile = Join-Path $script:HleDir 'touchHLE_options.txt'
$script:IpaDir = Join-Path $script:Root 'zombie_farm_ipa'
# Records which IPA the user picked, so the choice survives a restart. Kept at the
# top level, since it describes the manager's state rather than touchHLE's.
$script:SelectionFile = Join-Path $script:Root 'launcher_selected_ipa.txt'
# Remembers the last "skip ahead" duration (hours/minutes) typed into the
# 启动并跳过时间 dialog, so the next launch pre-fills it. Same reasoning as
# SelectionFile: manager state, top level, tiny plain-text file.
$script:SkipMemoryFile = Join-Path $script:Root 'launcher_skip_memory.txt'
$script:NightModeFile = Join-Path $script:Root 'launcher_night_mode.txt'
$script:NightMode = (Test-Path -LiteralPath $script:NightModeFile -PathType Leaf) -and
    ([System.IO.File]::ReadAllText($script:NightModeFile).Trim() -eq '1')

# NOTE: this manager is self-contained. It does NOT call
# StartZombieFarmNextHour.ps1 or SetZombieFarmCurrency.ps1 -- the launching and
# currency-writing logic is implemented in this file. Those two scripts still
# exist for command-line and analysis use, but nothing here depends on them.

# The app identifier and save folder depend on WHICH IPA is selected: the
# zombie_farm_ipa folder holds three different bundle ids, and both
# touchHLE_options.txt and the sandbox directory are keyed on that id. So they are
# resolved at startup by Read-IpaInfo / Initialize-IpaList rather than hardcoded.
$script:CurrentIpa = $null                          # set once the IPA is read
$script:AppId = 'com.playforge.ZombieFarm.ZFR'      # placeholder until then
$script:SaveDir = ''
$script:LiveSave = ''

# Everything matching "<BackupPrefix>*" is treated as a backup, except the
# per-backup .zf-offset companion file. The reference save that RestoreTestSave.ps1
# uses (saveGame.bin2.bak) remains an ordinary, legacy backup.
$script:BackupPrefix = 'saveGame.bin2.bak'
$script:BackupOffsetSuffix = '.zf-offset'

# Read Info.plist out of an IPA without extracting it.
#
# An IPA is a zip and its Info.plist is normally a BINARY plist (bplist00), which
# PowerShell cannot parse. Scanning the raw bytes for the key does NOT work: in a
# bplist the keys live in one object and the values in another, referenced by
# index, so whatever text follows "CFBundleIdentifier" is the next key's marker
# byte, not the value. (That mistake produced an app id of "_".) So this
# implements a minimal bplist reader and falls back to XML for non-binary files.
#
# Only what is needed is parsed: strings, integers, and the dictionary lookup.
# Returns $null in AppId on failure instead of throwing, because an unreadable IPA
# should show as such in the list rather than break the whole UI.
function Read-BinaryPlist {
    param([Parameter(Mandatory = $true)][byte[]]$Data)

    if ($Data.Length -lt 40) { return $null }
    $magic = [System.Text.Encoding]::ASCII.GetString($Data, 0, 8)
    if ($magic -ne 'bplist00') { return $null }

    # Trailer: 6 unused, offsetIntSize, objectRefSize, numObjects, topObject,
    # offsetTableOffset (each of the last five is a big-endian integer).
    $trailer = $Data.Length - 32
    $offsetIntSize = $Data[$trailer + 6]
    $objectRefSize = $Data[$trailer + 7]

    function Read-BeUInt {
        param([byte[]]$Buf, [int]$Pos, [int]$Size)
        $v = [int64]0
        for ($k = 0; $k -lt $Size; $k++) { $v = ($v -shl 8) -bor $Buf[$Pos + $k] }
        return $v
    }

    $numObjects = Read-BeUInt -Buf $Data -Pos ($trailer + 8) -Size 8
    $topObject = Read-BeUInt -Buf $Data -Pos ($trailer + 16) -Size 8
    $offsetTableOffset = Read-BeUInt -Buf $Data -Pos ($trailer + 24) -Size 8
    if ($offsetTableOffset -le 0 -or $offsetTableOffset -ge $Data.Length) { return $null }

    # Object offsets, so object N can be located.
    $offsets = New-Object 'int64[]' $numObjects
    for ($i = 0; $i -lt $numObjects; $i++) {
        $p = $offsetTableOffset + ($i * $offsetIntSize)
        if ($p + $offsetIntSize -gt $Data.Length) { return $null }
        $offsets[$i] = Read-BeUInt -Buf $Data -Pos $p -Size $offsetIntSize
    }

    # Decode the object at the given index into a simple value.
    #
    # Length handling: when an object's low nibble is 0xF, the real count follows
    # as an integer whose own size is 2^nextByte. `$Data[$p]` is the MARKER byte
    # (e.g. 0x10), not the nibble, so the size must be taken from the low nibble
    # of that marker: `1 -shl ($Data[$p] -band 0x0F)`. Using the whole byte gave
    # 1<<16 and read garbage.
    $decode = {
        param([int64]$Index, [int]$Depth)

        if ($Depth -gt 6 -or $Index -lt 0 -or $Index -ge $numObjects) { return $null }
        $pos = $offsets[$Index]
        if ($pos -lt 0 -or $pos -ge $Data.Length) { return $null }

        $marker = $Data[$pos]
        $type = $marker -shr 4
        $info = $marker -band 0x0F

        # Byte length of this object's payload, and where it starts.
        $len = $info
        $p = $pos + 1
        if ($info -eq 0x0F) {
            $intSize = 1 -shl ($Data[$p] -band 0x0F)
            $len = Read-BeUInt -Buf $Data -Pos ($p + 1) -Size $intSize
            $p += 1 + $intSize
        }

        switch ($type) {
            0x1 {   # integer
                if ($info -eq 0) { return [int64]0 }
                return Read-BeUInt -Buf $Data -Pos ($pos + 1) -Size (1 -shl $info)
            }
            0x2 {   # real
                if ($info -eq 2) { return [double][BitConverter]::ToSingle($Data, $pos + 1) }
                if ($info -eq 3) { return [double][BitConverter]::ToDouble($Data, $pos + 1) }
                return $null
            }
            0x4 {   # data
                if ($p + $len -gt $Data.Length) { return $null }
                if ($len -eq 0) { return ,@() }
                return ,$Data[$p..($p + $len - 1)]
            }
            0x5 {   # ASCII string
                if ($p + $len -gt $Data.Length) { return $null }
                return [System.Text.Encoding]::ASCII.GetString($Data, $p, $len)
            }
            0x6 {   # UTF-16BE string
                if ($p + ($len * 2) -gt $Data.Length) { return $null }
                return [System.Text.Encoding]::BigEndianUnicode.GetString($Data, $p, $len * 2)
            }
            0xA {   # array
                $out = @()
                for ($k = 0; $k -lt $len; $k++) {
                    $ref = Read-BeUInt -Buf $Data -Pos ($p + $k * $objectRefSize) -Size $objectRefSize
                    $out += ,(& $decode $ref ($Depth + 1))
                }
                return ,$out
            }
            0xD {   # dictionary
                $keysPos = $p
                $valsPos = $p + ($len * $objectRefSize)
                $map = @{}
                for ($k = 0; $k -lt $len; $k++) {
                    $kr = Read-BeUInt -Buf $Data -Pos ($keysPos + $k * $objectRefSize) -Size $objectRefSize
                    $key = & $decode $kr ($Depth + 1)
                    if ($key -isnot [string]) { continue }
                    $vr = Read-BeUInt -Buf $Data -Pos ($valsPos + $k * $objectRefSize) -Size $objectRefSize
                    $map[$key] = & $decode $vr ($Depth + 1)
                }
                return $map
            }
            default { return $null }
        }
    }

    $root = & $decode $topObject 0
    if ($root -isnot [hashtable]) { return $null }
    return $root
}

function Read-IpaInfo {
    param([Parameter(Mandatory = $true)][string]$Path)

    $result = [pscustomobject]@{
        Path = $Path
        Name = [System.IO.Path]::GetFileName($Path)
        AppId = $null
        Executable = $null
        Version = $null
        Size = 0
        Error = $null
    }

    try {
        $result.Size = (Get-Item -LiteralPath $Path).Length
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        $zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
        try {
            $entry = $zip.Entries | Where-Object {
                $_.FullName -like 'Payload/*.app/Info.plist'
            } | Select-Object -First 1
            if (-not $entry) {
                $result.Error = '没有 Payload/*.app/Info.plist'
                return $result
            }
            $stream = $entry.Open()
            try {
                $ms = New-Object System.IO.MemoryStream
                $stream.CopyTo($ms)
                $bytes = $ms.ToArray()
            } finally { $stream.Dispose() }

            $plist = Read-BinaryPlist -Data $bytes

            if ($null -eq $plist) {
                # Not a binary plist: try the XML form.
                $text = [System.Text.Encoding]::UTF8.GetString($bytes)
                $m = [regex]::Match($text, 'CFBundleIdentifier</key>\s*<string>([^<]+)</string>')
                if ($m.Success) {
                    $result.AppId = $m.Groups[1].Value
                    $m2 = [regex]::Match($text, 'CFBundleExecutable</key>\s*<string>([^<]+)</string>')
                    if ($m2.Success) { $result.Executable = $m2.Groups[1].Value }
                } else {
                    $result.Error = 'Info.plist 既不是二进制也不是可识别的 XML 格式'
                }
            } else {
                if ($plist.ContainsKey('CFBundleIdentifier')) {
                    $result.AppId = [string]$plist['CFBundleIdentifier']
                }
                if ($plist.ContainsKey('CFBundleExecutable')) {
                    $result.Executable = [string]$plist['CFBundleExecutable']
                }
                if ($plist.ContainsKey('CFBundleShortVersionString')) {
                    $result.Version = [string]$plist['CFBundleShortVersionString']
                } elseif ($plist.ContainsKey('CFBundleVersion')) {
                    $result.Version = [string]$plist['CFBundleVersion']
                }
                if (-not $result.AppId) { $result.Error = 'Info.plist 里没有 CFBundleIdentifier' }
            }
        } finally { $zip.Dispose() }
    } catch {
        $result.Error = $_.Exception.Message
    }
    return $result
}

# Try each default options line in turn until one applies.
#
# touchHLE matches the identifier exactly, and only one line is honoured per app,
# so the settings must move to whichever id the chosen IPA actually has.
function Set-CurrentIpa {
    param([Parameter(Mandatory = $true)]$IpaInfo)

    $script:CurrentIpa = $IpaInfo
    if ($IpaInfo.AppId) { $script:AppId = $IpaInfo.AppId }

    $script:SaveDir = Join-Path $script:HleDir ('touchHLE_sandbox\{0}\Documents' -f $script:AppId)
    $script:LiveSave = Join-Path $script:SaveDir 'saveGame.bin2'
}

function Get-IpaList {
    if (-not (Test-Path -LiteralPath $script:IpaDir)) { return @() }
    return @(Get-ChildItem -LiteralPath $script:IpaDir -Filter '*.ipa' -File |
        Sort-Object Name)
}

# The remembered choice, or the built-in default if that file is missing or names
# an IPA that no longer exists.
function Get-DefaultIpaPath {
    if (Test-Path -LiteralPath $script:SelectionFile) {
        $saved = ([System.IO.File]::ReadAllText($script:SelectionFile)).Trim()
        if ($saved) {
            $candidate = if ([System.IO.Path]::IsPathRooted($saved)) {
                $saved
            } else {
                Join-Path $script:IpaDir $saved
            }
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }
    $fallback = Join-Path $script:IpaDir 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
    if (Test-Path -LiteralPath $fallback) { return $fallback }
    $any = Get-IpaList | Select-Object -First 1
    if ($any) { return $any.FullName }
    return $null
}

function Save-IpaSelection {
    param([Parameter(Mandatory = $true)][string]$Path)
    # Store just the file name so the folder can be moved.
    [System.IO.File]::WriteAllText(
        $script:SelectionFile, [System.IO.Path]::GetFileName($Path),
        (New-Object System.Text.UTF8Encoding($false)))
}

# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------
#
# Each setting maps to one touchHLE command-line option.
#
#   Text  is what the dropdown shows, and must be SHORT: a WinForms combo does not
#         wrap, it just widens/clips, and long "value — explanation" strings
#         overflowed the control.
#   Tip   is the full explanation, shown in a dialog when the "?" button beside
#         the setting is clicked. Multi-line is fine there.
#
# Defaults reproduce the recommended configuration: 60fps plus the run-loop fix
# that lifts ZFR from 30fps to 60fps (see README section 2.5).

$script:SettingDefs = [ordered]@{
    fps_limit = @{
        Label       = '游戏帧率'
        Prefix      = '--fps-limit='
        Default     = '60'
        AllowCustom = $true
        CustomKind  = 'int'
        CustomMin   = 1
        CustomMax   = 1000
        Choices     = @(
            @{ Value = '30';     Text = '30 帧' }
            @{ Value = '60';     Text = '60 帧' }
            @{ Value = '90';     Text = '90 帧' }
            @{ Value = '120';    Text = '120 帧' }
            @{ Value = 'off';    Text = '不限帧' }
            @{ Value = 'custom'; Text = '自定义' }
        )
        CustomLabel = '自定义帧率'
        CustomSuffix = '帧'
        CustomInitial = 75
        CustomX = 458
    }
    wheel_zoom = @{
        Label       = '滚轮缩放倍率'
        Prefix      = '--zf-wheel-zoom-step='
        Default     = '1.1'
        AllowCustom = $true
        CustomKind  = 'decimal'
        CustomMin   = 1.01
        CustomMax   = 2.0
        CustomStep  = 0.01
        CustomDecimals = 2
        Choices     = @(
            @{ Value = '1.1'; Text = '×1.1（默认）' }
            @{ Value = '1.2'; Text = '×1.2' }
            @{ Value = '1.5'; Text = '×1.5' }
            @{ Value = 'custom'; Text = '自定义' }
        )
        CustomLabel = '自定义倍率'
        CustomInitial = 1.1
        CustomX = 458
    }
    # Window size is TWO touchHLE options, presented as one row:
    #   --device-family  picks the emulated screen (iPhone / iPad) AND the
    #                    iPhone/iPad UI idiom the game lays itself out for
    #   --scale-hack     multiplies that screen's size to get the window
    #   window size == device screen x scale-hack
    # Verified against the real window rectangle: iPhone x1 = 480x320, iPad x1 =
    # 1024x768, iPad x1.5 = 1536x1152 (all exact).
    #
    # They are two independent settings (not one list) because that is how the
    # user asked for them: "左边可以选 ipad 形式的还是 iphone 形式的，右侧可以
    # 自定义 --scale-hack 的大小". A live label at the end of the row computes the
    # resulting window size, so the pair still reads as one decision.
    #
    # The two share a row; see the layout loop below.
    #
    # WHY THE WINDOW IS SCALED, NOT THE EMULATED SCREEN
    # -------------------------------------------------
    # This game is fixed-resolution: its UI is laid out in POINTS against a
    # 480x320 (iPhone) or 768x1024 (iPad) screen and its art is fixed size. The
    # largest artwork in the IPA is 1024x768 (MainMenuBG.png is 1024x683); the
    # median of its 806 PNGs is 88px wide. `UIScreen.bounds` reports the emulated
    # size verbatim (ui_screen.rs), so RAISING the emulated size does not scale
    # the UI up - it hands the game a bigger canvas and the game draws the same
    # small UI on it, with the background art stretched to fill. That is the
    # "拉扯"/tiny-UI symptom, and it is why 16:9 (and any big --device-size)
    # looked wrong even though the window and its aspect ratio were correct.
    # `--scale-hack` instead keeps the emulated size native and only enlarges the
    # render target and window, so the layout stays exactly right. Confirmed by
    # capture at every size offered below, title screen and farm both.
    #
    # A `--device-size=` override is therefore NOT used for sizing any more. It
    # also turned out to force the game back to its iPhone layout regardless of
    # --device-family, which is why every custom size looked wrong.
    #
    # WHY iPAD IS THE DEFAULT FAMILY
    # ------------------------------
    # The iPad idiom lays out far better at large window sizes: the user reported
    # the iPhone entries as "画面排布会非常糟糕" (logo tiny, HUD cramped) once
    # scaled up, while the same scale on iPad renders correctly. iPhone remains
    # selectable because seeing the original phone layout is occasionally useful,
    # but iPad x1.5 is the recommended combination.
    #
    # WHY THE SCALE FACTOR CAN BE FRACTIONAL
    # --------------------------------------
    # The iPad screen is 1024x768, so integer scales jump straight from 1024x768
    # to 2048x1536 - and the latter does not fit a 2560x1440 display (its frame is
    # about 2070x1592 against roughly 1368 usable height). Fractional values fill
    # the gap: 1.5 gives 1536x1152, which fits with room to spare. The scale hack
    # is also used for the renderbuffer size, so touchHLE stores it as an exact
    # numerator/denominator pair and window and framebuffer stay in agreement
    # instead of drifting by a rounding error.
    #
    # WHY THE FAMILY HAS NO CUSTOM ENTRY
    # ----------------------------------
    # `--device-family` selects a fixed screen size AND the iPhone/iPad UI idiom
    # (ui_device.rs's userInterfaceIdiom). There is nothing continuous to
    # customize: touchHLE accepts exactly "iphone" and "ipad".
    window_family = @{
        Label   = '窗口大小 / 分辨率'
        Prefix  = '--device-family='
        Default = 'ipad'
        # Both window settings share one row: family on the left, scale (and its
        # custom entry) on the right, with a live size readout at the end. The
        # explicit geometry keeps the two dropdowns, the custom editor and the
        # readout inside the 626px group box without overlapping:
        #   label 14..164 | family 170..272 | scale 300..380
        #   custom 396..446 | size 452..616
        Row     = 'window'
        ComboX  = 170
        ComboW  = 102
        Choices = @(
            @{ Value = 'ipad';   Text = 'iPad（平板）' }
            @{ Value = 'iphone'; Text = 'iPhone（手机）' }
        )
    }
    window_scale = @{
        # No Label: this control shares window_family's row and the row's single
        # label already covers both.
        Label       = ''
        Prefix      = '--scale-hack='
        Default     = '1.5'
        AllowCustom = $true
        # A decimal or a fraction, so both "1.75" and "7/4" are accepted. That
        # keeps a hand-edited file (which may well say 13/8) loading and being
        # written back unchanged instead of being silently rounded to a preset.
        CustomKind  = 'scale'
        CustomMin   = 1.0
        CustomMax   = 3.0
        CustomLabel = ''
        # Start the custom box at a value that is NOT one of the presets, so a box
        # reading "1.5" next to a ×1.5 preset cannot look like the same setting
        # listed twice.
        CustomInitial = '7/4'
        CustomX     = 396
        CustomWidth = 46
        Choices     = @(
            @{ Value = '1.25'; Text = '×1.25' }
            @{ Value = '1.5';  Text = '×1.5' }
            @{ Value = '1.75'; Text = '×1.75' }
            @{ Value = 'custom'; Text = '自定义' }
        )
        Row         = 'window'
        ComboX      = 300
        ComboW      = 80
    }
    fullscreen = @{
        Label   = '显示模式'
        Prefix  = '--fullscreen'
        Default = '0'
        Choices = @(
            @{ Value = '0'; Text = '窗口模式' }
            @{ Value = '1'; Text = '全屏' }
        )
    }
    run_loop_fix = @{
        Label   = '高速帧率修复'
        Prefix  = '--non-blocking-zero-timeout-run-loop'
        Default = '1'
        Choices = @(
            @{ Value = '1'; Text = '开启' }
            @{ Value = '0'; Text = '关闭' }
        )
    }
}

# Parse a number written as an integer ("2"), a decimal ("1.75") or a fraction
# ("7/4"). Returns $null when it is not a number, so callers can reject it.
#
# Mirrors touchHLE's own options.rs:parse_scale_factor, which is what actually
# consumes the value, so anything the UI accepts touchHLE also accepts.
function ConvertTo-Number {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    $text = $Value.Trim()
    $den = 1.0
    if ($text.Contains('/')) {
        $parts = $text.Split('/')
        if ($parts.Count -ne 2) { return $null }
        $numText = $parts[0].Trim()
        $denText = $parts[1].Trim()
        if (-not $denText -or $denText -notmatch '^[0-9]+(\.[0-9]+)?$') { return $null }
        $den = [double]$denText
        if ($den -eq 0) { return $null }
    } else {
        $numText = $text
    }
    if ($numText -notmatch '^[0-9]+(\.[0-9]+)?$') { return $null }
    $num = [double]$numText
    $result = $num / $den
    if ([double]::IsNaN($result) -or [double]::IsInfinity($result)) { return $null }
    return $result
}

# Would touchHLE accept this exact spelling for `key`?
#
# This is deliberately about the SPELLING, not just the numeric value: touchHLE
# parses --scale-hack itself, so "7/4" and "1.75" are both valid and both mean
# the same window, and a hand-edited file must keep loading. Only the generic
# forms touchHLE understands are allowed - a value like "1.75x" or "3//2" is
# rejected here even though it might parse loosely.
function Test-CustomSpelling {
    param([string]$Kind, [string]$Value)

    switch ($Kind) {
        'int' { return $Value -match '^[0-9]+$' }
        # A decimal or a fraction, i.e. exactly what parse_scale_factor accepts.
        'scale' { return $Value -match '^[0-9]+(\.[0-9]+)?(/[0-9]+(\.[0-9]+)?)?$' }
        # Same, but touchHLE's --zf-wheel-zoom-step does a plain f32 parse, so a
        # fraction would be rejected there; decimals only.
        'decimal' { return $Value -match '^[0-9]+(\.[0-9]+)?$' }
        default { return $false }
    }
}

# Is `value` acceptable for `key`?
#
# Presets always are. A setting with AllowCustom additionally accepts any number
# in its Custom range in one of the spellings touchHLE itself parses, so a
# hand-edited file with an unusual value still loads instead of silently
# reverting to the default (which would rewrite the user's file behind their
# back).
function Test-SettingValue {
    param([string]$Key, [string]$Value)

    $def = $script:SettingDefs[$Key]
    if ($null -eq $def) { return $false }

    foreach ($c in $def.Choices) {
        if ($c.Value -eq $Value) { return $true }
    }
    if (-not $def.AllowCustom) { return $false }

    $kind = if ($def.ContainsKey('CustomKind')) { $def.CustomKind } else { 'int' }
    if (-not (Test-CustomSpelling -Kind $kind -Value $Value)) { return $false }

    $n = ConvertTo-Number -Value $Value
    if ($null -eq $n) { return $false }
    return $n -ge $def.CustomMin -and $n -le $def.CustomMax
}

# The window size a (family, scale) pair actually produces, in landscape, which
# is the orientation the launcher uses (--landscape-right).
#
# Pure function of its arguments (no UI access), so -SelfTest can verify the
# arithmetic without a window. Implemented with the same arithmetic as touchHLE's
# own options.rs scale_dim (round half up on the rational num/den), so the label
# cannot disagree with the window the emulator really opens - and
# _device_size_e2e.ps1 measures the real client area to keep that claim honest
# rather than assumed.
function Get-WindowSizeForScale {
    param([string]$Family, [string]$Scale)

    $portrait = if ($Family -eq 'iphone') { @(320, 480) } else { @(768, 1024) }

    $num = ConvertTo-Number -Value $Scale
    if ($null -eq $num -or $num -le 0) { return '倍率无效' }

    # Exact rational arithmetic, mirroring parse_scale_factor's reduction, then
    # the same rounding scale_dim uses. Kept as decimals rather than doubles so a
    # fraction like 13/8 cannot drift by one pixel.
    $parts = $Scale.Split('/')
    $n = [decimal](ConvertTo-Number -Value $parts[0])
    $d = if ($parts.Count -eq 2) { [decimal](ConvertTo-Number -Value $parts[1]) } else { [decimal]1 }
    if ($d -eq 0) { return '倍率无效' }

    # Landscape swaps the portrait dimensions: width = height * scale.
    $w = [int][Math]::Floor(([decimal]$portrait[1] * $n / $d) + [decimal]0.5)
    $h = [int][Math]::Floor(([decimal]$portrait[0] * $n / $d) + [decimal]0.5)
    return ("{0} × {1}" -f $w, $h)
}

# ---------------------------------------------------------------------------
# touchHLE_options.txt read/write
# ---------------------------------------------------------------------------
#
# touchHLE reads this file as UTF-8 and matches on the exact app identifier, so
# the ZFR line is the only line this script touches; comments and other apps are
# preserved byte-for-byte.

function Read-OptionsFile {
    if (-not (Test-Path -LiteralPath $script:OptionsFile)) {
        return @{ Lines = @(); Exists = $false }
    }
    $lines = [System.IO.File]::ReadAllLines(
        $script:OptionsFile, (New-Object System.Text.UTF8Encoding($false)))
    return @{ Lines = $lines; Exists = $true }
}

# The app id is taken before the first colon, after stripping comments, so an
# option value containing ':' cannot confuse the parse.
function Get-AppIdFromLine {
    param([string]$Line)

    $body = $Line
    $hash = $body.IndexOf('#')
    if ($hash -ge 0) { $body = $body.Substring(0, $hash) }
    $body = $body.Trim()
    if (-not $body) { return $null }

    $parts = $body.Split(':', 2)
    if ($parts.Count -ne 2) { return $null }
    return $parts[0].Trim()
}

function Get-OptionsLine {
    param([string[]]$Lines)

    foreach ($line in $Lines) {
        if ((Get-AppIdFromLine -Line $line) -eq $script:AppId) {
            $body = $line
            $hash = $body.IndexOf('#')
            if ($hash -ge 0) { $body = $body.Substring(0, $hash) }
            return $body.Split(':', 2)[1].Trim()
        }
    }
    return $null
}

function Get-CurrentSettings {
    $file = Read-OptionsFile
    $line = Get-OptionsLine -Lines $file.Lines

    $settings = [ordered]@{}
    foreach ($key in $script:SettingDefs.Keys) {
        $settings[$key] = $script:SettingDefs[$key].Default
    }
    if ($null -eq $line) { return $settings }

    $tokens = $line.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
    foreach ($key in $script:SettingDefs.Keys) {
        $def = $script:SettingDefs[$key]

        if ($def.Prefix.EndsWith('=')) {
            foreach ($token in $tokens) {
                if (-not $token.StartsWith($def.Prefix)) { continue }

                # A value equal to a preset is stored as that preset, so the
                # dropdown highlights it. Anything else that touchHLE accepts
                # (a custom framerate or scale) is kept verbatim rather than
                # being rounded to a preset, so the file is never rewritten
                # behind the user's back.
                #
                # There is no longer any "most specific match" rule: every
                # setting maps to exactly ONE option now. The previous model
                # bundled --device-family and --scale-hack into a single
                # `device_size` choice whose option set could be a subset of
                # another's (the native entries sat inside every scaled entry's
                # set), which forced a specificity comparison to disambiguate.
                $raw = $token.Substring($def.Prefix.Length)
                if (Test-SettingValue -Key $key -Value $raw) {
                    $settings[$key] = $raw
                }
                break
            }
        } elseif ($tokens -contains $def.Prefix) {
            $settings[$key] = '1'
        } else {
            # The line exists but does not name this flag, so touchHLE is running
            # it OFF - and the UI must say so rather than fall back to `Default`.
            # `Default` is the RECOMMENDED setting the manager writes into a fresh
            # file; it is not what an absent flag means. Reporting it here made
            # turning 高速帧率修复 off look like it had not saved (the options file
            # was correct, but the dropdown snapped back to 开启).
            #
            # When there is no line at all the defaults above still apply, because
            # then nothing has been configured yet and the first edit writes the
            # recommended line.
            $settings[$key] = '0'
        }
    }
    return $settings
}

function Save-Settings {
    param([Parameter(Mandatory = $true)]$Settings)

    $file = Read-OptionsFile
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($l in $file.Lines) { $lines.Add($l) }

    $tokens = @()
    foreach ($key in $script:SettingDefs.Keys) {
        $def = $script:SettingDefs[$key]
        $value = [string]$Settings[$key]

        if ($def.Prefix.EndsWith('=')) {
            # Values are written even when they equal the default, so the file
            # itself documents the current configuration.
            $tokens += ('{0}{1}' -f $def.Prefix, $value)
        } elseif ($value -eq '1') {
            $tokens += $def.Prefix
        }
    }
    $newLine = '{0}: {1}' -f $script:AppId, ($tokens -join ' ')

    $replaced = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ((Get-AppIdFromLine -Line $lines[$i]) -eq $script:AppId) {
            $lines[$i] = $newLine
            $replaced = $true
            break
        }
    }
    if (-not $replaced) {
        $insertAt = $lines.Count
        while ($insertAt -gt 0 -and -not $lines[$insertAt - 1].Trim()) { $insertAt-- }
        $lines.Insert($insertAt, $newLine)
    }

    [System.IO.File]::WriteAllText(
        $script:OptionsFile, (($lines -join "`r`n") + "`r`n"),
        (New-Object System.Text.UTF8Encoding($false)))
}

function Read-SkipMemory {
    # Last chosen skip duration as @{ Hours; Minutes }, or $null when absent or
    # malformed. Never throws: a corrupt memory file just means "no memory".
    if (-not (Test-Path -LiteralPath $script:SkipMemoryFile)) { return $null }
    try {
        $raw = [System.IO.File]::ReadAllText($script:SkipMemoryFile).Trim()
        $m = [regex]::Match($raw, '^(\d{1,4})\s*[: ,]\s*(\d{1,2})$')
        if (-not $m.Success) { return $null }
        $h = [int]$m.Groups[1].Value
        $min = [int]$m.Groups[2].Value
        if ($min -gt 59) { return $null }
        return @{ Hours = $h; Minutes = $min }
    } catch { return $null }
}

function Save-SkipMemory {
    param([int]$Hours, [int]$Minutes)
    try {
        [System.IO.File]::WriteAllText(
            $script:SkipMemoryFile, ('{0}:{1:00}' -f $Hours, $Minutes),
            (New-Object System.Text.UTF8Encoding($false)))
    } catch { <# remembering is a nicety, not a requirement #> }
}

function Test-GameRunning {
    return [bool](Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue)
}

# Paths the launcher needs. Defined up here (rather than next to the launching
# code further down) so the -SelfTest block, which runs before that code is
# parsed into scope, can still verify them.
function Get-LaunchPaths {
    $ipa = $null
    if ($null -ne $script:CurrentIpa) { $ipa = $script:CurrentIpa.Path }
    if (-not $ipa) { $ipa = Get-DefaultIpaPath }

    return [pscustomobject]@{
        # touchHLE's own state lives beside touchHLE.exe.
        OffsetFile  = Join-Path $script:HleDir 'touchHLE_time_offset_seconds.txt'
        Fingerprint = Join-Path $script:HleDir 'zfr_last_launch.txt'
        TouchHLE    = Join-Path $script:HleDir 'touchHLE.exe'
        Ipa         = $ipa
        # Resources are found relative to the CURRENT DIRECTORY, so this is what
        # the child process must be started in.
        WorkingDir  = $script:HleDir
    }
}

# ---------------------------------------------------------------------------
# Save management (backup / restore / delete)
# ---------------------------------------------------------------------------
#
# Everything matching saveGame.bin2.bak* is listed, except its hidden .zf-offset
# companion file. Restoring archives both the current save and its time offset.

function Get-BackupFiles {
    param([string]$Directory = $script:SaveDir)

    if (-not (Test-Path -LiteralPath $Directory)) { return @() }
    $prefix = $script:BackupPrefix
    return @(Get-ChildItem -LiteralPath $Directory -File |
        Where-Object {
            $_.Name -like "$prefix*" -and
            -not $_.Name.EndsWith($script:BackupOffsetSuffix, [System.StringComparison]::OrdinalIgnoreCase)
        } |
        Sort-Object LastWriteTime -Descending)
}

function Get-BackupOffsetPath {
    param([Parameter(Mandatory = $true)][string]$BackupPath)
    return "$BackupPath$($script:BackupOffsetSuffix)"
}

function Read-TimeOffset {
    param([string]$Path = (Get-LaunchPaths).OffsetFile)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return [int64]0 }
    $text = [System.IO.File]::ReadAllText($Path).Trim()
    if (-not $text) { return [int64]0 }
    [int64]$value = 0
    if (-not [int64]::TryParse($text, [ref]$value) -or $value -lt 0) {
        throw "累计时间偏移文件内容无效：$Path"
    }
    return $value
}

function Write-TimeOffset {
    param(
        [Parameter(Mandatory = $true)][int64]$Value,
        [string]$Path = (Get-LaunchPaths).OffsetFile
    )

    if ($Value -lt 0) { throw '累计时间偏移不能为负数。' }
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temp = Join-Path $directory ('.time-offset-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
    $replaced = "$Path.bak-$([Guid]::NewGuid().ToString('N'))"
    try {
        [System.IO.File]::WriteAllText($temp, [string]$Value, [System.Text.Encoding]::ASCII)
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            [System.IO.File]::Replace($temp, $Path, $replaced)
            Remove-Item -LiteralPath $replaced -Force -ErrorAction SilentlyContinue
        } else {
            [System.IO.File]::Move($temp, $Path)
        }
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $replaced) {
            Remove-Item -LiteralPath $replaced -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-BackupOffset {
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [Parameter(Mandatory = $true)][int64]$Value
    )

    $metadataPath = Get-BackupOffsetPath -BackupPath $BackupPath
    $temp = Join-Path (Split-Path -Parent $BackupPath) ('.zf-offset-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
    try {
        [System.IO.File]::WriteAllText($temp, [string]$Value, [System.Text.Encoding]::ASCII)
        [System.IO.File]::Move($temp, $metadataPath)
        [System.IO.File]::SetAttributes($metadataPath, [System.IO.FileAttributes]::Hidden)
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
    }
}

# Short label for a backup row: the label the backup was made with (e.g. manual,
# pre-restore), or "备份" for a plain timestamped snapshot.
function Get-BackupKind {
    param([System.IO.FileInfo]$File)

    $m = [regex]::Match($File.Name, '^saveGame\.bin2\.bak-(\d{8}-\d{6})(?:-(.+))?$')
    if ($m.Success) {
        if ($m.Groups[2].Success) { return $m.Groups[2].Value }
        return '备份'
    }
    return '备份'
}

function New-SaveBackup {
    param(
        [string]$Directory = $script:SaveDir,
        [string]$Label = 'manual',
        [string]$SourcePath,
        [string]$OffsetFile = (Get-LaunchPaths).OffsetFile
    )

    if (-not $SourcePath) { $SourcePath = Join-Path $Directory 'saveGame.bin2' }
    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw '找不到当前存档，无法备份。'
    }

    $offset = Read-TimeOffset -Path $OffsetFile
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $target = Join-Path $Directory ("{0}-{1}-{2}" -f $script:BackupPrefix, $stamp, $Label)
    $suffix = 1
    while ((Test-Path -LiteralPath $target) -or (Test-Path -LiteralPath (Get-BackupOffsetPath -BackupPath $target))) {
        $target = Join-Path $Directory ("{0}-{1}-{2}-{3}" -f $script:BackupPrefix, $stamp, $Label, $suffix)
        $suffix++
    }

    Copy-Item -LiteralPath $SourcePath -Destination $target
    try {
        Write-BackupOffset -BackupPath $target -Value $offset
    } catch {
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Get-BackupOffsetPath -BackupPath $target) -Force -ErrorAction SilentlyContinue
        throw
    }
    return $target
}

function Restore-SaveBackup {
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [string]$Directory = $script:SaveDir,
        [string]$OffsetFile = (Get-LaunchPaths).OffsetFile
    )

    if (-not (Test-Path -LiteralPath $BackupPath)) { throw "备份不存在：$BackupPath" }

    $metadataPath = Get-BackupOffsetPath -BackupPath $BackupPath
    $restoreOffset = $null
    if (Test-Path -LiteralPath $metadataPath -PathType Leaf) {
        $restoreOffset = Read-TimeOffset -Path $metadataPath
    }

    $live = Join-Path $Directory 'saveGame.bin2'
    # Archive the current save first so a restore is itself undoable.
    $preRestore = $null
    if (Test-Path -LiteralPath $live) {
        $preRestore = New-SaveBackup -Directory $Directory -Label 'pre-restore' -SourcePath $live -OffsetFile $OffsetFile
    }
    try {
        Copy-Item -LiteralPath $BackupPath -Destination $live -Force
        if ($null -ne $restoreOffset) {
            Write-TimeOffset -Value $restoreOffset -Path $OffsetFile
        }
    } catch {
        if ($preRestore -and (Test-Path -LiteralPath $preRestore)) {
            Copy-Item -LiteralPath $preRestore -Destination $live -Force
        }
        throw
    }
    return $live
}

function Remove-SaveBackup {
    param([Parameter(Mandatory = $true)][string]$BackupPath)

    if (-not (Test-Path -LiteralPath $BackupPath)) { throw "备份不存在：$BackupPath" }

    # Only delete things that are actually backups, by name. This is a whitelist
    # rather than a comparison against the live save's exact path, so it holds for
    # any directory (the self-test runs against a temporary one) and refuses to
    # touch the live save, the .preview file, or anything else that is not a
    # backup. The live save is saveGame.bin2, which does not match this pattern.
    $leaf = [System.IO.Path]::GetFileName($BackupPath)
    if ($leaf -notlike "$($script:BackupPrefix)*") {
        throw "拒绝删除：$leaf 不是备份文件。"
    }

    $item = Get-Item -LiteralPath $BackupPath
    Remove-Item -LiteralPath $BackupPath -Force
    $metadataPath = Get-BackupOffsetPath -BackupPath $BackupPath
    if (Test-Path -LiteralPath $metadataPath) {
        Remove-Item -LiteralPath $metadataPath -Force
    }
    return $item.Name
}

# ---------------------------------------------------------------------------
# Save file currency (brains / gold)
# ---------------------------------------------------------------------------
#
# Self-contained: reading AND writing are implemented here rather than delegating
# to SetZombieFarmCurrency.ps1, so the manager has no helper-script dependency.
#
# A version-14 save starts with int32 14 and contains one serialised player-data
# block, identified by a fixed marker. Currency fields sit at stable offsets from
# that marker:
#
#     marker + 0x42   layout version (must be 4)
#     marker + 0x46   gold      (int32)
#     marker + 0x4A   brains    (int32)
#     marker + 0x52   reserved  (must be 0)
#     marker + 0x56   first index  (0..1000000)
#     marker + 0x5A   second index (0..1000000)
#     marker + 0x5E   end of the fields that must exist
#
# The surrounding invariant fields are checked as well, so a save damaged by an
# earlier tool is refused instead of being made worse.

function Get-CurrencyLayout {
    param([Parameter(Mandatory = $true)][byte[]]$Data)

    if ($Data.Length -lt 4 -or [BitConverter]::ToInt32($Data, 0) -ne 14) {
        throw '这不是受支持的 Zombie Farm / ZFR 版本 14 存档。'
    }

    $marker = [byte[]]@(0x01,0x09,0x00,0x00,0x00,0x55,0x4E,0x44,0x45,0x46,0x49,0x4E,0x45,0x44)
    $markerOffset = -1
    for ($i = 0; $i -le $Data.Length - $marker.Length; $i++) {
        if ($Data[$i] -ne $marker[0]) { continue }
        $ok = $true
        for ($j = 1; $j -lt $marker.Length; $j++) {
            if ($Data[$i + $j] -ne $marker[$j]) { $ok = $false; break }
        }
        if ($ok) {
            if ($markerOffset -ge 0) {
                throw '存档里有多个玩家数据块，无法确定用哪一个。存档未被修改。'
            }
            $markerOffset = $i
        }
    }
    if ($markerOffset -lt 0) {
        throw '找不到版本 14 的玩家数据块。存档未被修改。'
    }

    $goldOffset = $markerOffset + 0x46
    $brainOffset = $markerOffset + 0x4A
    if ($Data.Length -lt ($markerOffset + 0x5E)) {
        throw '玩家数据块不完整。请先还原一个未经修改的备份。'
    }

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
        throw '玩家数据块校验失败，可能已经损坏。请先还原一个未经修改的备份。存档未被修改。'
    }

    $gold = [BitConverter]::ToInt32($Data, $goldOffset)
    $brains = [BitConverter]::ToInt32($Data, $brainOffset)
    if ($gold -lt 0 -or $brains -lt 0) {
        throw '当前金币或脑子的数值无效。请先还原一个未经修改的备份。'
    }

    return [pscustomobject]@{
        MarkerOffset = $markerOffset
        GoldOffset   = $goldOffset
        BrainOffset  = $brainOffset
        Gold         = $gold
        Brains       = $brains
    }
}

# Read-only view used to populate the UI. Returns $null instead of throwing when
# the save is absent or unreadable, because "no save yet" is a normal state.
function Get-Currency {
    param([string]$SavePath = $script:LiveSave)

    if (-not (Test-Path -LiteralPath $SavePath)) { return $null }
    try {
        $data = [System.IO.File]::ReadAllBytes($SavePath)
        $layout = Get-CurrencyLayout -Data $data
        return [pscustomobject]@{ Gold = $layout.Gold; Brains = $layout.Brains }
    } catch {
        return $null
    }
}

# Write new values, with the same safety properties as the original script:
#   * the file is written to a temporary file and re-read to verify it
#   * File.Replace atomically swaps it in and keeps the old file as a backup
#   * the result is re-read and verified; on failure the backup is put back
# Returns the path of the backup that was created.
function Set-Currency {
    param(
        [Parameter(Mandatory = $true)][int]$Gold,
        [Parameter(Mandatory = $true)][int]$Brains,
        [string]$SavePath = $script:LiveSave,
        [string]$OffsetFile = (Get-LaunchPaths).OffsetFile
    )

    if ($Gold -lt 0 -or $Brains -lt 0) { throw '金币和脑子不能是负数。' }
    if (-not (Test-Path -LiteralPath $SavePath -PathType Leaf)) {
        throw "找不到存档：$SavePath"
    }

    $data = [System.IO.File]::ReadAllBytes($SavePath)
    $layout = Get-CurrencyLayout -Data $data

    [byte[]]$updated = $data.Clone()
    [BitConverter]::GetBytes($Gold).CopyTo($updated, $layout.GoldOffset)
    [BitConverter]::GetBytes($Brains).CopyTo($updated, $layout.BrainOffset)

    $dir = [System.IO.Path]::GetDirectoryName($SavePath)
    $name = [System.IO.Path]::GetFileName($SavePath)

    # Unique backup name, so two writes in the same second cannot collide.
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $backupPath = "$SavePath.bak-$stamp"
    $suffix = 1
    while ((Test-Path -LiteralPath $backupPath) -or (Test-Path -LiteralPath (Get-BackupOffsetPath -BackupPath $backupPath))) {
        $backupPath = "$SavePath.bak-$stamp-$suffix"
        $suffix++
    }
    $offset = Read-TimeOffset -Path $OffsetFile

    $tempPath = Join-Path $dir ('.{0}.tmp-{1}' -f $name, [Guid]::NewGuid().ToString('N'))
    try {
        [System.IO.File]::WriteAllBytes($tempPath, $updated)

        # Verify the temp file before touching the real one.
        $tempLayout = Get-CurrencyLayout -Data ([System.IO.File]::ReadAllBytes($tempPath))
        if (
            $tempLayout.MarkerOffset -ne $layout.MarkerOffset -or
            $tempLayout.Gold -ne $Gold -or
            $tempLayout.Brains -ne $Brains
        ) {
            throw '写入校验失败，原存档未被修改。'
        }

        Write-BackupOffset -BackupPath $backupPath -Value $offset
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
            throw '写入后校验失败，已自动从备份还原。'
        }
    } catch {
        if (-not (Test-Path -LiteralPath $backupPath)) {
            Remove-Item -LiteralPath (Get-BackupOffsetPath -BackupPath $backupPath) -Force -ErrorAction SilentlyContinue
        }
        throw
    } finally {
        if ($null -ne $tempPath -and (Test-Path -LiteralPath $tempPath)) {
            Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
        }
    }

    return $backupPath
}

# ---------------------------------------------------------------------------
# Headless modes
# ---------------------------------------------------------------------------

# Resolve which IPA is selected before anything that depends on the app id. This
# is what the GUI's Add_Shown handler does for the interactive path; the headless
# modes need it too, or the settings/save paths would use the placeholder id.
function Initialize-CurrentIpa {
    $path = Get-DefaultIpaPath
    if (-not $path) {
        $script:CurrentIpa = $null
        return $null
    }
    $info = Read-IpaInfo -Path $path
    Set-CurrentIpa -IpaInfo $info
    return $info
}

if ($ShowSettings) {
    [void](Initialize-CurrentIpa)
    Write-Host "app_id=$script:AppId"
    Write-Host "save_dir=$script:SaveDir"
    $s = Get-CurrentSettings
    foreach ($key in $script:SettingDefs.Keys) { Write-Host ("{0}={1}" -f $key, $s[$key]) }
    exit 0
}

if ($Set) {
    # Resolve which IPA is selected FIRST. Without this the app id is still the
    # placeholder set at the top of this file (com.playforge.ZombieFarm.ZFR), so
    # `-Set` wrote its own line into touchHLE_options.txt while the GUI and
    # -ShowSettings read a DIFFERENT line - the two silently disagreed, and
    # whichever IPA was actually selected never saw the change. Adding a second
    # app id also meant the file grew a duplicate-looking line for a bundle that
    # may not even be the one being launched.
    [void](Initialize-CurrentIpa)

    $settings = Get-CurrentSettings
    $changed = $false

    # Accept `-Set a=1,b=2` and `-Set a=1 b=2`: powershell -File binds only the
    # first token to the array, so split on commas and spaces alike.
    foreach ($pair in ($Set -split '[,\s]+' | Where-Object { $_ })) {
        $parts = $pair.Split('=', 2)
        if ($parts.Count -ne 2) {
            Write-Host "Expected key=value, got '$pair'" -ForegroundColor Red
            exit 2
        }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()

        if (-not $script:SettingDefs.Contains($key)) {
            Write-Host "Unknown setting '$key'" -ForegroundColor Red
            exit 2
        }
        if (-not (Test-SettingValue -Key $key -Value $value)) {
            $allowed = @($script:SettingDefs[$key].Choices | ForEach-Object { $_.Value })
            Write-Host ("Invalid value '{0}' for '{1}'; allowed: {2}" -f `
                $value, $key, ($allowed -join ', ')) -ForegroundColor Red
            exit 2
        }
        $settings[$key] = $value
        $changed = $true
    }

    if ($changed) {
        Save-Settings -Settings $settings
        # Name the app id too: with several bundle ids in the folder, "which line
        # did that write?" is the first thing to check when a change seems to have
        # had no effect.
        Write-Host ("Saved for {0}: {1}" -f $script:AppId, (Get-OptionsLine -Lines (Read-OptionsFile).Lines))
    }
    exit 0
}

if ($SelfTest) {
    $optionsBackup = $null
    if (Test-Path -LiteralPath $script:OptionsFile) {
        $optionsBackup = [System.IO.File]::ReadAllText($script:OptionsFile)
    }
    # The selftest must be read-only toward the REAL save: the currency write
    # test runs on a copy inside a throwaway %TEMP% directory. The live save's
    # hash is baselined once the IPA is resolved (see below) and re-checked
    # right before the verdict, so a future edit that breaks this invariant
    # fails the selftest instead of passing silently. (If the game itself is
    # running it could also write the save concurrently -- close the game
    # before running -SelfTest.)
    $liveHashBefore = $null
    $ok = $true

    # Save-management tests run against a throwaway directory so the real saves
    # are never touched by a test.
    $sandbox = Join-Path $env:TEMP ('zfr_savetest_' + [Guid]::NewGuid().ToString('N'))
    $offsetFixture = Join-Path $sandbox 'touchHLE_time_offset_seconds.txt'

    try {
        Write-Host "--- IPA selection ---"
        $ipaList = Get-IpaList
        Write-Host ("  IPAs found           : {0}" -f $ipaList.Count)
        if ($ipaList.Count -eq 0) { Write-Host '  FAIL: no IPA found'; $ok = $false }

        $info = Initialize-CurrentIpa
        if (-not $info) {
            Write-Host '  FAIL: could not resolve a default IPA'
            $ok = $false
        } else {
            Write-Host ("  selected             : {0}" -f $info.Name)
            Write-Host ("  detected app id      : {0}" -f $(if ($info.AppId) { $info.AppId } else { '<none>' }))
            $idOk = [bool]$info.AppId
            if (-not $idOk) { $ok = $false }

            # The app id must actually drive the derived paths.
            $expected = Join-Path $script:HleDir ('touchHLE_sandbox\{0}\Documents' -f $info.AppId)
            $pathOk = ($script:SaveDir -eq $expected)
            Write-Host ("  save dir follows id  : {0}" -f $(if ($pathOk) { 'PASS' } else { "FAIL ($($script:SaveDir))" }))
            if (-not $pathOk) { $ok = $false }

            # Baseline the real save's hash now that LiveSave is resolved.
            if (Test-Path -LiteralPath $script:LiveSave) {
                $liveHashBefore = (Get-FileHash -LiteralPath $script:LiveSave -Algorithm SHA256).Hash
            }
        }

        # Every IPA in the folder must be readable, since the dropdown lists them.
        Write-Host ''
        Write-Host '--- every IPA readable ---'
        $unreadable = @()
        foreach ($f in $ipaList) {
            $i = Read-IpaInfo -Path $f.FullName
            if (-not $i.AppId) { $unreadable += $f.Name }
        }
        if ($unreadable.Count -eq 0) {
            Write-Host ("  all {0} IPA(s) have a readable app id: PASS" -f $ipaList.Count)
        } else {
            Write-Host ("  FAIL: {0} IPA(s) unreadable" -f $unreadable.Count)
            foreach ($u in $unreadable) { Write-Host "    $u" }
            $ok = $false
        }

        # Distinct ids matter: settings and saves are keyed on them.
        $ids = @($ipaList | ForEach-Object {
            $x = Read-IpaInfo -Path $_.FullName
            if ($x.AppId) { $x.AppId }
        } | Sort-Object -Unique)
        Write-Host ("  distinct app ids     : {0}" -f $ids.Count)
        foreach ($id in $ids) { Write-Host "    $id" }

        Write-Host ''
        Write-Host '--- settings ---'
        Write-Host "app id : $script:AppId"
        Write-Host "file   : $script:OptionsFile"
        Write-Host ''

        Write-Host '--- settings: defaults ---'
        $s = Get-CurrentSettings
        foreach ($k in $s.Keys) { Write-Host ("  {0,-14} = {1}" -f $k, $s[$k]) }

        Write-Host ''
        Write-Host '--- settings: write custom 75 fps + scale 7/4 ---'
        $s['fps_limit'] = '75'
        $s['window_family'] = 'iphone'
        $s['window_scale'] = '7/4'
        $s['wheel_zoom'] = '1.25'
        Save-Settings -Settings $s
        Write-Host ("  line: " + (Get-OptionsLine -Lines (Read-OptionsFile).Lines))

        $s2 = Get-CurrentSettings
        $rt = $s2['fps_limit'] -eq '75' -and $s2['window_scale'] -eq '7/4' -and
              $s2['window_family'] -eq 'iphone' -and $s2['wheel_zoom'] -eq '1.25' -and
              $s2['run_loop_fix'] -eq '1'
        Write-Host ("  custom fps + family + scale + wheel round-trip : " + $(if ($rt) { 'PASS' } else { 'FAIL' }))
        if (-not $rt) { $ok = $false }

        # Every preset of every setting must survive a write/read cycle. The
        # window settings are separate options now, so a reader that confused
        # --device-family with --scale-hack would show up here.
        #
        # Flag settings (Prefix without '=') are skipped here: they are present or
        # absent rather than carrying a value, so "0" is not a value the line can
        # express - writing 0 omits the token and the reader reports 1. They get
        # their own check below.
        $rtFails = 0
        $rtChecked = 0
        foreach ($key in $script:SettingDefs.Keys) {
            $def = $script:SettingDefs[$key]
            if (-not $def.Prefix.EndsWith('=')) { continue }
            foreach ($choice in $def.Choices) {
                if ($choice.Value -eq 'custom') { continue }
                $s[$key] = $choice.Value
                Save-Settings -Settings $s
                $back = (Get-CurrentSettings)[$key]
                $rtChecked++
                if ($back -ne $choice.Value) {
                    $rtFails++
                    Write-Host ("  {0}.{1} -> read back '{2}'  FAIL" -f $key, $choice.Value, $back)
                }
                # Restore the shared-row partner so the next iteration starts from
                # a line that still names every option.
                if ($key -eq 'window_family') { $s['window_family'] = 'ipad' }
            }
        }
        Write-Host ("  all {0} preset values round-trip : {1}" -f `
            $rtChecked, $(if ($rtFails -eq 0) { 'PASS' } else { "FAIL ($rtFails)" }))
        if ($rtFails -ne 0) { $ok = $false }

        # A flag setting round-trips as the only two states its line spelling can
        # express: token present (1) and token absent (0).
        $flagDef = $script:SettingDefs['run_loop_fix']
        $flagFails = 0
        foreach ($want in @('1', '0')) {
            $s['run_loop_fix'] = $want
            Save-Settings -Settings $s
            $tokens = (Get-OptionsLine -Lines (Read-OptionsFile).Lines).Split(' ')
            $present = ($tokens -contains $flagDef.Prefix)
            $back = (Get-CurrentSettings)['run_loop_fix']
            $pass = (($want -eq '1') -eq $present) -and ($back -eq $want)
            if (-not $pass) { $flagFails++ }
            Write-Host ("  flag run_loop_fix={0} -> token present={1}, read back '{2}'  {3}" -f `
                $want, $present, $back, $(if ($pass) { 'ok' } else { 'FAIL' }))
        }
        Write-Host ("  flag on/off round-trip : " + $(if ($flagFails -eq 0) { 'PASS' } else { 'FAIL' }))
        if ($flagFails -ne 0) { $ok = $false }
        $s['run_loop_fix'] = '1'

        # restore the intended settings for the remaining checks
        $s['fps_limit'] = '60'
        $s['window_family'] = 'ipad'
        $s['window_scale'] = '1.5'
        $s['wheel_zoom'] = '1.1'
        Save-Settings -Settings $s

        Write-Host ''
        Write-Host '--- settings: custom value validation ---'
        $cases = @(
            @{ K = 'fps_limit';   V = '75';    Want = $true;  Note = 'in range' }
            @{ K = 'fps_limit';   V = '1';     Want = $true;  Note = 'lower bound' }
            @{ K = 'fps_limit';   V = '1000';  Want = $true;  Note = 'upper bound' }
            @{ K = 'fps_limit';   V = '0';     Want = $false; Note = 'below range' }
            @{ K = 'fps_limit';   V = '1001';  Want = $false; Note = 'above range' }
            @{ K = 'fps_limit';   V = 'abc';   Want = $false; Note = 'not a number' }
            @{ K = 'fps_limit';   V = 'off';   Want = $true;  Note = 'preset' }
            @{ K = 'fps_limit';   V = '';      Want = $false; Note = 'empty' }
            # The scale accepts a fraction or a decimal, because touchHLE does.
            @{ K = 'window_scale'; V = '7/4';   Want = $true;  Note = 'fraction, in range' }
            @{ K = 'window_scale'; V = '1.75';  Want = $true;  Note = 'a preset' }
            @{ K = 'window_scale'; V = '13/8';  Want = $true;  Note = 'equivalent fraction' }
            @{ K = 'window_scale'; V = '1';     Want = $true;  Note = 'lower bound' }
            @{ K = 'window_scale'; V = '3';     Want = $true;  Note = 'upper bound' }
            @{ K = 'window_scale'; V = '0.5';   Want = $false; Note = 'below range' }
            @{ K = 'window_scale'; V = '4';     Want = $false; Note = 'above range' }
            @{ K = 'window_scale'; V = '7/0';   Want = $false; Note = 'zero denominator' }
            @{ K = 'window_scale'; V = 'abc';   Want = $false; Note = 'not a number' }
            @{ K = 'window_scale'; V = '3/2/2'; Want = $false; Note = 'malformed fraction' }
            @{ K = 'window_scale'; V = '1.75x'; Want = $false; Note = 'trailing junk' }
            # The wheel step is a plain decimal: touchHLE parses it as an f32, so a
            # fraction must be rejected rather than silently misread.
            @{ K = 'wheel_zoom';  V = '1.5';   Want = $true;  Note = 'preset' }
            @{ K = 'wheel_zoom';  V = '1.01';  Want = $true;  Note = 'lower bound' }
            @{ K = 'wheel_zoom';  V = '2';     Want = $true;  Note = 'upper bound' }
            @{ K = 'wheel_zoom';  V = '1.0';   Want = $false; Note = 'below range' }
            @{ K = 'wheel_zoom';  V = '2.01';  Want = $false; Note = 'above range' }
            @{ K = 'wheel_zoom';  V = '3/2';   Want = $false; Note = 'fraction not accepted' }
            @{ K = 'wheel_zoom';  V = '';      Want = $false; Note = 'empty' }
            # The family is a closed set: no numeric value belongs here.
            @{ K = 'window_family'; V = 'ipad';   Want = $true;  Note = 'preset' }
            @{ K = 'window_family'; V = 'iphone'; Want = $true;  Note = 'preset' }
            @{ K = 'window_family'; V = '1.5';    Want = $false; Note = 'not a family' }
            @{ K = 'window_family'; V = '';       Want = $false; Note = 'empty' }
        )
        foreach ($c in $cases) {
            $got = Test-SettingValue -Key $c.K -Value $c.V
            $pass = $got -eq $c.Want
            if (-not $pass) { $ok = $false }
            Write-Host ("  {0,-13} {1,-8} -> {2,-5} ({3}) {4}" -f `
                $c.K, "'$($c.V)'", $got, $c.Note, $(if ($pass) { 'ok' } else { 'FAIL' }))
        }

        Write-Host ''
        Write-Host '--- settings: window size arithmetic ---'
        # Each combination must produce the window touchHLE's own scale_dim
        # produces. These are the numbers _device_size_e2e.ps1 measures against
        # the real client area, so this keeps the label honest even without
        # launching the game. (This runs before the UI exists, so the pure
        # function is used rather than the live controls.)
        $sizeCases = @(
            @{ Fam = 'ipad';   Scale = '1.25'; Want = '1280 × 960' }
            @{ Fam = 'ipad';   Scale = '1.5';  Want = '1536 × 1152' }
            @{ Fam = 'ipad';   Scale = '1.75'; Want = '1792 × 1344' }
            @{ Fam = 'ipad';   Scale = '1';    Want = '1024 × 768' }
            @{ Fam = 'ipad';   Scale = '2';    Want = '2048 × 1536' }
            @{ Fam = 'iphone'; Scale = '1';    Want = '480 × 320' }
            @{ Fam = 'iphone'; Scale = '1.5';  Want = '720 × 480' }
            # A decimal and its fraction must give the same window, or the two
            # spellings touchHLE accepts would disagree with the readout.
            @{ Fam = 'ipad';   Scale = '5/4';  Want = '1280 × 960' }
            @{ Fam = 'ipad';   Scale = '3/2';  Want = '1536 × 1152' }
            @{ Fam = 'ipad';   Scale = '7/4';  Want = '1792 × 1344' }
        )
        foreach ($c in $sizeCases) {
            $got = Get-WindowSizeForScale -Family $c.Fam -Scale $c.Scale
            $pass = ($got -eq $c.Want)
            if (-not $pass) { $ok = $false }
            Write-Host ("  {0,-7} x{1,-5} -> {2,-13} (want {3}) {4}" -f `
                $c.Fam, $c.Scale, $got, $c.Want, $(if ($pass) { 'ok' } else { 'FAIL' }))
        }

        Write-Host ''
        Write-Host '--- settings: the option line names every option exactly once ---'
        # A duplicated option (e.g. two --scale-hack= tokens, or a leftover
        # --device-size=) would make touchHLE apply whichever comes last, so the
        # file and the UI could silently disagree.
        $line = Get-OptionsLine -Lines (Read-OptionsFile).Lines
        $tokens = @($line.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries))
        $dupFails = 0
        foreach ($key in $script:SettingDefs.Keys) {
            $prefix = $script:SettingDefs[$key].Prefix
            if (-not $prefix.EndsWith('=')) { continue }
            $n = @($tokens | Where-Object { $_.StartsWith($prefix) }).Count
            if ($n -ne 1) {
                $dupFails++
                Write-Host ("  {0} appears {1} time(s)  FAIL" -f $prefix, $n)
            }
        }
        # The retired --device-size= must not reappear: it forces the iPhone
        # layout and was the cause of the "拉扯" symptom.
        if ($tokens -match '^--device-size=') {
            $dupFails++
            Write-Host '  --device-size= present  FAIL (retired option)'
        }
        Write-Host ("  every option named once, no retired options : " + `
            $(if ($dupFails -eq 0) { 'PASS' } else { "FAIL ($dupFails)" }))
        if ($dupFails -ne 0) { $ok = $false }

        Write-Host ''
        Write-Host '--- settings: file stays valid UTF-8, comments kept, idempotent ---'
        $bytes = [System.IO.File]::ReadAllBytes($script:OptionsFile)
        $strict = New-Object System.Text.UTF8Encoding($false, $true)
        try { $null = $strict.GetString($bytes); Write-Host '  valid UTF-8 : PASS' }
        catch { Write-Host '  valid UTF-8 : FAIL'; $ok = $false }
        $before = ($optionsBackup -split "`r?`n" | Where-Object { $_ -match '^\s*#' }).Count
        $after = ((Read-OptionsFile).Lines | Where-Object { $_ -match '^\s*#' }).Count
        Write-Host ("  comments    : {0} -> {1}" -f $before, $after)
        if ($after -lt $before) { Write-Host '  FAIL: comments lost'; $ok = $false }

        $s3 = Get-CurrentSettings
        Save-Settings -Settings $s3
        $s4 = Get-CurrentSettings
        $stable = $true
        foreach ($k in $s4.Keys) { if ($s4[$k] -ne $s3[$k]) { $stable = $false } }
        Write-Host ("  idempotent  : " + $(if ($stable) { 'PASS' } else { 'FAIL' }))
        if (-not $stable) { $ok = $false }

        Write-Host ''
        Write-Host '--- save management (sandboxed) ---'
        New-Item -ItemType Directory -Force -Path $sandbox | Out-Null
        [System.IO.File]::WriteAllText($offsetFixture, '7200', [System.Text.Encoding]::ASCII)

        # Build a live save plus one pre-existing backup.
        $live = Join-Path $sandbox 'saveGame.bin2'
        [System.IO.File]::WriteAllBytes($live, [byte[]](1..40))
        [System.IO.File]::WriteAllBytes((Join-Path $sandbox 'saveGame.bin2.bak'), [byte[]](1..20))

        $count0 = (Get-BackupFiles -Directory $sandbox).Count
        Write-Host ("  initial backups      : {0}" -f $count0)

        # 1. new backup
        $made = New-SaveBackup -Directory $sandbox -Label 'manual' -OffsetFile $offsetFixture
        $count1 = (Get-BackupFiles -Directory $sandbox).Count
        $sizeOk = (Get-Item -LiteralPath $made).Length -eq 40
        $savedOffset = Read-TimeOffset -Path (Get-BackupOffsetPath -BackupPath $made)
        $sidecarsHiddenFromList = @((Get-BackupFiles -Directory $sandbox | Where-Object { $_.Name.EndsWith($script:BackupOffsetSuffix) })).Count -eq 0
        Write-Host ("  after 新增备份        : {0}  (+{1})  content={2}" -f `
            $count1, ($count1 - $count0), $(if ($sizeOk) { 'ok' } else { 'FAIL' }))
        if ($count1 -ne ($count0 + 1) -or -not $sizeOk) { $ok = $false }
        Write-Host ("  backup time offset   : {0} sec  {1}" -f $savedOffset, $(if ($savedOffset -eq 7200 -and $sidecarsHiddenFromList) { 'PASS' } else { 'FAIL' }))
        if ($savedOffset -ne 7200 -or -not $sidecarsHiddenFromList) { $ok = $false }

        # 2. restore: live is overwritten with the backup's content, and the old
        #    live save is archived first.
        [System.IO.File]::WriteAllBytes($live, [byte[]](9..30))
        [System.IO.File]::WriteAllText($offsetFixture, '9999', [System.Text.Encoding]::ASCII)
        [void](Restore-SaveBackup -BackupPath $made -Directory $sandbox -OffsetFile $offsetFixture)
        $restored = [System.IO.File]::ReadAllBytes($live)
        $restoreOk = $restored.Length -eq 40 -and $restored[0] -eq 1 -and $restored[39] -eq 40
        $restoredOffset = Read-TimeOffset -Path $offsetFixture
        $count2 = (Get-BackupFiles -Directory $sandbox).Count
        Write-Host ("  after 还原备份        : content={0}  backups={1} (archived first)" -f `
            $(if ($restoreOk) { 'ok' } else { 'FAIL' }), $count2)
        if (-not $restoreOk) { $ok = $false }
        Write-Host ("  restored time offset : {0} sec  {1}" -f $restoredOffset, $(if ($restoredOffset -eq 7200) { 'PASS' } else { 'FAIL' }))
        if ($restoredOffset -ne 7200) { $ok = $false }
        if ($count2 -ne ($count1 + 1)) { Write-Host '  FAIL: pre-restore archive missing'; $ok = $false }

        # 3. delete
        $removed = Remove-SaveBackup -BackupPath $made
        $count3 = (Get-BackupFiles -Directory $sandbox).Count
        $gone = -not (Test-Path -LiteralPath $made)
        $metadataGone = -not (Test-Path -LiteralPath (Get-BackupOffsetPath -BackupPath $made))
        Write-Host ("  after 删除备份        : {0}  removed={1}  gone={2}" -f `
            $count3, $(if ($removed) { 'ok' } else { 'FAIL' }), $(if ($gone) { 'ok' } else { 'FAIL' }))
        Write-Host ("  offset metadata removed: {0}" -f $(if ($metadataGone) { 'PASS' } else { 'FAIL' }))
        if ($count3 -ne ($count2 - 1) -or -not $gone -or -not $metadataGone) { $ok = $false }

        # A legacy backup has no offset metadata. Keep the current cumulative
        # value rather than guessing that the older backup represented time zero.
        $legacyBackup = Join-Path $sandbox 'saveGame.bin2.bak'
        [System.IO.File]::WriteAllText($offsetFixture, '12345', [System.Text.Encoding]::ASCII)
        [void](Restore-SaveBackup -BackupPath $legacyBackup -Directory $sandbox -OffsetFile $offsetFixture)
        $legacyOffsetOk = (Read-TimeOffset -Path $offsetFixture) -eq 12345
        Write-Host ("  legacy backup offset : {0}" -f $(if ($legacyOffsetOk) { 'preserved (PASS)' } else { 'changed (FAIL)' }))
        if (-not $legacyOffsetOk) { $ok = $false }

        # Invalid metadata is rejected before either live state is changed.
        $badOffsetBackup = Join-Path $sandbox 'saveGame.bin2.bak-invalid-offset'
        [System.IO.File]::WriteAllBytes($badOffsetBackup, [byte[]](21..30))
        [System.IO.File]::WriteAllText((Get-BackupOffsetPath -BackupPath $badOffsetBackup), 'not-a-number', [System.Text.Encoding]::ASCII)
        $beforeBadRestore = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($live))
        $badRefused = $false
        try { [void](Restore-SaveBackup -BackupPath $badOffsetBackup -Directory $sandbox -OffsetFile $offsetFixture) } catch { $badRefused = $true }
        $badRestoreUntouched = ([Convert]::ToBase64String([System.IO.File]::ReadAllBytes($live)) -eq $beforeBadRestore) -and
            ((Read-TimeOffset -Path $offsetFixture) -eq 12345)
        [void](Remove-SaveBackup -BackupPath $badOffsetBackup)
        Write-Host ("  invalid offset refused: {0}, untouched={1}" -f $(if ($badRefused) { 'PASS' } else { 'FAIL' }), $(if ($badRestoreUntouched) { 'PASS' } else { 'FAIL' }))
        if (-not $badRefused -or -not $badRestoreUntouched) { $ok = $false }

        # The live save must never be deletable through this path.
        $guarded = $false
        try { [void](Remove-SaveBackup -BackupPath $live) } catch { $guarded = $true }
        Write-Host ("  live save protected  : " + $(if ($guarded) { 'PASS' } else { 'FAIL' }))
        if (-not $guarded) { $ok = $false }

        # 4. bulk delete: the UI deletes every selected row, so several backups
        #    must go in one pass while the live save survives.
        Write-Host ''
        Write-Host '--- bulk delete (as the UI does) ---'
        for ($i = 1; $i -le 4; $i++) {
            [void](New-SaveBackup -Directory $sandbox -Label "bulk$i")
        }
        $beforeBulk = (Get-BackupFiles -Directory $sandbox).Count
        $toDelete = @(Get-BackupFiles -Directory $sandbox | Where-Object { $_.Name -like '*bulk*' })
        $deleted = 0
        foreach ($d in $toDelete) {
            try { [void](Remove-SaveBackup -BackupPath $d.FullName); $deleted++ } catch { }
        }
        $afterBulk = (Get-BackupFiles -Directory $sandbox).Count
        $bulkOk = ($toDelete.Count -eq 4) -and ($deleted -eq 4) -and ($afterBulk -eq ($beforeBulk - 4))
        Write-Host ("  created 4, deleted 4 : before={0} after={1} deleted={2}  {3}" -f `
            $beforeBulk, $afterBulk, $deleted, $(if ($bulkOk) { 'PASS' } else { 'FAIL' }))
        if (-not $bulkOk) { $ok = $false }

        # The live save must still be there after the bulk delete.
        $liveIntact = Test-Path -LiteralPath $live
        Write-Host ("  live save survived   : " + $(if ($liveIntact) { 'PASS' } else { 'FAIL' }))
        if (-not $liveIntact) { $ok = $false }

        Write-Host ''
        Write-Host '--- settings carry no in-GUI help text ---'
        # The "?" buttons were removed at the operator's request: all of that
        # explanation now lives in 使用说明.html, so a Tip field reappearing here
        # would be dead weight (and would mean the UI had grown a help affordance
        # nobody asked for).
        $tipFails = 0
        foreach ($key in $script:SettingDefs.Keys) {
            if ($script:SettingDefs[$key].ContainsKey('Tip')) {
                $tipFails++
                Write-Host ("  {0} still has a Tip  FAIL" -f $key)
            }
        }
        Write-Host ("  no setting defines Tip : " + $(if ($tipFails -eq 0) { 'PASS' } else { "FAIL ($tipFails)" }))
        if ($tipFails -ne 0) { $ok = $false }

        # The dropdown text must stay short, or it overflows the control.
        $longest = 0
        foreach ($key in $script:SettingDefs.Keys) {
            foreach ($c in $script:SettingDefs[$key].Choices) {
                if ($c.Text.Length -gt $longest) { $longest = $c.Text.Length }
            }
        }
        $labelOk = $longest -le 20
        Write-Host ("  longest choice text  : {0} chars  {1}" -f `
            $longest, $(if ($labelOk) { 'PASS' } else { 'FAIL (would overflow)' }))
        if (-not $labelOk) { $ok = $false }

        Write-Host ''
        Write-Host '--- currency read (real save) ---'
        $c = Get-Currency
        if ($c) { Write-Host ("  Gold={0}  Brains={1}" -f $c.Gold, $c.Brains) }
        else { Write-Host '  FAIL: save not readable'; $ok = $false }

        # Currency writing runs against a COPY of the real save inside the
        # sandbox, so the test proves the binary layout handling without touching
        # anything the user cares about.
        Write-Host ''
        Write-Host '--- currency write (on a copy) ---'
        $copy = Join-Path $sandbox 'saveGame.bin2'
        Copy-Item -LiteralPath $script:LiveSave -Destination $copy -Force
        $orig = Get-Currency -SavePath $copy

        $writtenBackup = Set-Currency -Gold 123456 -Brains 654321 -SavePath $copy -OffsetFile $offsetFixture
        $after = Get-Currency -SavePath $copy
        $writeOk = $after -and $after.Gold -eq 123456 -and $after.Brains -eq 654321
        Write-Host ("  {0} / {1} -> {2} / {3}  {4}" -f `
            $orig.Gold, $orig.Brains,
            $(if ($after) { $after.Gold } else { '?' }),
            $(if ($after) { $after.Brains } else { '?' }),
            $(if ($writeOk) { 'PASS' } else { 'FAIL' }))
        if (-not $writeOk) { $ok = $false }

        # The write must not change the file's size (equal-width in-place edit).
        $sizeSame = (Get-Item -LiteralPath $copy).Length -eq (Get-Item -LiteralPath $script:LiveSave).Length
        Write-Host ("  file size unchanged  : " + $(if ($sizeSame) { 'PASS' } else { 'FAIL' }))
        if (-not $sizeSame) { $ok = $false }

        # A backup must have been made alongside it.
        $bakExists = Test-Path -LiteralPath $writtenBackup
        Write-Host ("  backup written       : " + $(if ($bakExists) { 'PASS' } else { 'FAIL' }))
        if (-not $bakExists) { $ok = $false }
        $currencyBackupOffset = Read-TimeOffset -Path (Get-BackupOffsetPath -BackupPath $writtenBackup)
        $currencyBackupOffsetOk = $currencyBackupOffset -eq 12345
        Write-Host ("  currency backup offset: {0} sec  {1}" -f $currencyBackupOffset, $(if ($currencyBackupOffsetOk) { 'PASS' } else { 'FAIL' }))
        if (-not $currencyBackupOffsetOk) { $ok = $false }

        # Restoring that backup must bring the old values back.
        Copy-Item -LiteralPath $writtenBackup -Destination $copy -Force
        $restoredCurrency = Get-Currency -SavePath $copy
        $undoOk = $restoredCurrency -and $restoredCurrency.Gold -eq $orig.Gold -and
                  $restoredCurrency.Brains -eq $orig.Brains
        Write-Host ("  backup restores old  : " + $(if ($undoOk) { 'PASS' } else { 'FAIL' }))
        if (-not $undoOk) { $ok = $false }

        # A file that is not a version-14 save must be refused, not corrupted.
        $bogus = Join-Path $sandbox 'notasave.bin2'
        [System.IO.File]::WriteAllBytes($bogus, [byte[]](1..64))
        $refused = $false
        try { [void](Set-Currency -Gold 1 -Brains 1 -SavePath $bogus) } catch { $refused = $true }
        $untouched = (Get-Item -LiteralPath $bogus).Length -eq 64
        Write-Host ("  invalid file refused : {0}, untouched={1}" -f `
            $(if ($refused) { 'PASS' } else { 'FAIL' }), $(if ($untouched) { 'ok' } else { 'FAIL' }))
        if (-not $refused -or -not $untouched) { $ok = $false }

        Write-Host ''
        Write-Host '--- launching (paths only; no process started) ---'
        $lp = Get-LaunchPaths
        $hleOk = Test-Path -LiteralPath $lp.TouchHLE
        $ipaOk = Test-Path -LiteralPath $lp.Ipa
        Write-Host ("  touchHLE.exe found   : " + $(if ($hleOk) { 'PASS' } else { 'FAIL' }))
        Write-Host ("  game IPA found       : " + $(if ($ipaOk) { 'PASS' } else { 'FAIL' }))
        if (-not $hleOk -or -not $ipaOk) { $ok = $false }
        # The launcher must not pass --device-family on the command line, or it
        # would override the options file that the UI writes.
        $launcherSource = [System.IO.File]::ReadAllText($PSCommandPath)
        $noDeviceArg = $launcherSource -notmatch "Arguments\s*=.*--device-family"
        Write-Host ("  no --device-family arg: " + $(if ($noDeviceArg) { 'PASS' } else { 'FAIL' }))
        if (-not $noDeviceArg) { $ok = $false }

        # The real save must be byte-identical to when the selftest started.
        # (Also fails if the game itself wrote the save mid-test -- close the
        # game before running -SelfTest.)
        if ($null -ne $liveHashBefore) {
            $liveHashAfter = (Get-FileHash -LiteralPath $script:LiveSave -Algorithm SHA256).Hash
            $liveOk = $liveHashAfter -eq $liveHashBefore
            Write-Host ("  real save untouched  : " + $(if ($liveOk) { 'PASS' } else { 'FAIL (live save changed during selftest!)' }))
            if (-not $liveOk) { $ok = $false }
        }

        Write-Host ''
        Write-Host ("SELFTEST: " + $(if ($ok) { 'PASS' } else { 'FAIL' }))
        exit $(if ($ok) { 0 } else { 1 })
    } finally {
        if ($null -ne $optionsBackup) {
            [System.IO.File]::WriteAllText(
                $script:OptionsFile, $optionsBackup, (New-Object System.Text.UTF8Encoding($false)))
        }
        if (Test-Path -LiteralPath $sandbox) {
            Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

Add-Type -ReferencedAssemblies @(
    [System.Windows.Forms.TabControl].Assembly.Location,
    [System.Drawing.Color].Assembly.Location
) -TypeDefinition @'
using System;
using System.Drawing;
using System.Windows.Forms;

public sealed class PaletteTabControl : TabControl
{
    private Color stripColor = SystemColors.Control;
    private Color borderColor = SystemColors.ControlDark;
    private Color tabColor = SystemColors.Control;
    private Color selectedTabColor = SystemColors.Highlight;
    private Color tabTextColor = SystemColors.ControlText;
    private Color selectedTabTextColor = SystemColors.HighlightText;

    public Color StripColor
    {
        get { return stripColor; }
        set { stripColor = value; Invalidate(); }
    }

    public Color BorderColor
    {
        get { return borderColor; }
        set { borderColor = value; Invalidate(); }
    }

    public Color TabColor { get { return tabColor; } set { tabColor = value; Invalidate(); } }
    public Color SelectedTabColor { get { return selectedTabColor; } set { selectedTabColor = value; Invalidate(); } }
    public Color TabTextColor { get { return tabTextColor; } set { tabTextColor = value; Invalidate(); } }
    public Color SelectedTabTextColor { get { return selectedTabTextColor; } set { selectedTabTextColor = value; Invalidate(); } }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != 0x000F || !IsHandleCreated || TabCount == 0) return;

        int stripHeight = Math.Max(0, DisplayRectangle.Top);
        if (stripHeight == 0) return;

        using (var graphics = Graphics.FromHwnd(Handle))
        using (var brush = new SolidBrush(stripColor))
        using (var tabBrush = new SolidBrush(tabColor))
        using (var selectedBrush = new SolidBrush(selectedTabColor))
        using (var borderPen = new Pen(borderColor, 2.0f))
        {
            using (var uncovered = new Region(new Rectangle(0, 0, ClientSize.Width, stripHeight)))
            {
                for (int index = 0; index < TabCount; index++)
                    uncovered.Exclude(GetTabRect(index));
                graphics.FillRegion(brush, uncovered);
            }

            for (int index = 0; index < TabCount; index++)
            {
                Rectangle tab = GetTabRect(index);
                bool selected = index == SelectedIndex;
                graphics.FillRectangle(selected ? selectedBrush : tabBrush, tab);
                graphics.DrawRectangle(borderPen, tab.X, tab.Y, tab.Width - 1, tab.Height - 1);
                TextRenderer.DrawText(graphics, TabPages[index].Text.Trim(), Font, tab,
                    selected ? selectedTabTextColor : tabTextColor,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                    TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis);
            }

            Rectangle page = DisplayRectangle;
            page.Inflate(1, 1);
            graphics.DrawRectangle(borderPen, page);
            Rectangle frame = ClientRectangle;
            frame.Inflate(-1, -1);
            graphics.DrawRectangle(borderPen, frame);
        }
    }
}

public sealed class PaletteComboBox : ComboBox
{
    private Color arrowColor;
    private Color arrowBorderColor;
    private Color arrowGlyphColor;

    public PaletteComboBox()
    {
        arrowColor = SystemColors.Control;
        arrowBorderColor = SystemColors.ControlDark;
        arrowGlyphColor = SystemColors.ControlText;
    }

    protected override CreateParams CreateParams
    {
        get
        {
            CreateParams parameters = base.CreateParams;
            parameters.ExStyle &= ~0x00000200; // WS_EX_CLIENTEDGE
            parameters.Style &= ~0x00800000;   // WS_BORDER
            return parameters;
        }
    }

    public Color ArrowColor { get { return arrowColor; } set { arrowColor = value; Invalidate(); } }
    public Color ArrowBorderColor { get { return arrowBorderColor; } set { arrowBorderColor = value; Invalidate(); } }
    public Color ArrowGlyphColor { get { return arrowGlyphColor; } set { arrowGlyphColor = value; Invalidate(); } }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != 0x000F || !IsHandleCreated || ClientSize.Width == 0) return;

        int arrowWidth = Math.Min(SystemInformation.VerticalScrollBarWidth, ClientSize.Width);
        Rectangle arrow = new Rectangle(ClientSize.Width - arrowWidth, 0, arrowWidth, ClientSize.Height);
        using (var graphics = Graphics.FromHwnd(Handle))
        using (var background = new SolidBrush(ArrowColor))
        using (var border = new Pen(ArrowBorderColor))
        using (var glyph = new SolidBrush(ArrowGlyphColor))
        {
            // The themed combo arrow leaves a one-pixel white seam before its
            // client area; overlap that pixel so the palette owns the separator.
            graphics.FillRectangle(background, arrow.Left - 1, 0, arrow.Width + 1, arrow.Height);
            graphics.DrawLine(border, arrow.Left, 2, arrow.Left, arrow.Bottom - 3);
            int cx = arrow.Left + arrow.Width / 2;
            int cy = arrow.Top + arrow.Height / 2;
            graphics.FillPolygon(glyph, new[] {
                new Point(cx - 4, cy - 2), new Point(cx + 4, cy - 2), new Point(cx, cy + 3)
            });
            graphics.DrawRectangle(border, 0, 0, ClientSize.Width - 1, ClientSize.Height - 1);
        }
    }
}

public sealed class PaletteGroupBox : GroupBox
{
    private Color borderColor;

    public PaletteGroupBox() { borderColor = SystemColors.ControlDark; }

    public Color BorderColor { get { return borderColor; } set { borderColor = value; Invalidate(); } }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != 0x000F || !IsHandleCreated || Width < 8 || Height < 8) return;

        int y = Math.Max(5, Font.Height / 2);
        int gapStart = 8;
        int gapEnd = gapStart + (Text.Length == 0 ? 0 : TextRenderer.MeasureText(Text, Font).Width) + 8;
        using (var graphics = Graphics.FromHwnd(Handle))
        using (var border = new Pen(BorderColor, 2.0f))
        {
            graphics.DrawLine(border, 0, y, gapStart, y);
            graphics.DrawLine(border, gapEnd, y, Width - 1, y);
            graphics.DrawLine(border, 0, y, 0, Height - 1);
            graphics.DrawLine(border, Width - 1, y, Width - 1, Height - 1);
            graphics.DrawLine(border, 0, Height - 1, Width - 1, Height - 1);
        }
    }
}

public static class WindowChrome
{
    [System.Runtime.InteropServices.DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hwnd, IntPtr insertAfter, int x, int y,
        int width, int height, uint flags);

    public static int PackColor(Color color)
    {
        return color.R | (color.G << 8) | (color.B << 16);
    }

    public static void Apply(IntPtr hwnd, bool night, int caption, int text, int border)
    {
        int dark = night ? 1 : 0;
        int result = DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int));
        if (result != 0) DwmSetWindowAttribute(hwnd, 19, ref dark, sizeof(int));

        DwmSetWindowAttribute(hwnd, 35, ref caption, sizeof(int));
        DwmSetWindowAttribute(hwnd, 36, ref text, sizeof(int));
        DwmSetWindowAttribute(hwnd, 34, ref border, sizeof(int));
        SetWindowPos(hwnd, IntPtr.Zero, 0, 0, 0, 0, 0x0027);
    }
}
'@

$font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9.5)
$fontBold = New-Object System.Drawing.Font('Microsoft YaHei UI', 10.5, [System.Drawing.FontStyle]::Bold)
$fontTitle = New-Object System.Drawing.Font('Microsoft YaHei UI', 15, [System.Drawing.FontStyle]::Bold)
$fontSmall = New-Object System.Drawing.Font('Microsoft YaHei UI', 8.5)
if ($script:NightMode) {
    $ink = [System.Drawing.Color]::FromArgb(232, 237, 234)
    $grey = [System.Drawing.Color]::FromArgb(165, 179, 173)
    $red = [System.Drawing.Color]::FromArgb(224, 126, 116)
    $forest = [System.Drawing.Color]::FromArgb(76, 139, 111)
    $sage = [System.Drawing.Color]::FromArgb(126, 177, 146)
    $amber = [System.Drawing.Color]::FromArgb(214, 168, 99)
    $paper = [System.Drawing.Color]::FromArgb(29, 35, 38)
    $surface = [System.Drawing.Color]::FromArgb(38, 46, 48)
    $softGreen = [System.Drawing.Color]::FromArgb(48, 65, 56)
    $line = [System.Drawing.Color]::FromArgb(49, 59, 56)
} else {
    $ink = [System.Drawing.Color]::FromArgb(38, 52, 58)
    $grey = [System.Drawing.Color]::FromArgb(105, 122, 120)
    $red = [System.Drawing.Color]::FromArgb(184, 78, 74)
    $forest = [System.Drawing.Color]::FromArgb(45, 101, 87)
    $sage = [System.Drawing.Color]::FromArgb(111, 148, 127)
    $amber = [System.Drawing.Color]::FromArgb(214, 160, 82)
    $paper = [System.Drawing.Color]::FromArgb(243, 246, 244)
    $surface = [System.Drawing.Color]::White
    $softGreen = [System.Drawing.Color]::FromArgb(228, 236, 231)
    $line = [System.Drawing.Color]::FromArgb(220, 228, 223)
}

$script:PaletteComboDraw = {
    param($sender, $eventArgs)
    $label = if ($eventArgs.Index -ge 0) { [string]$sender.Items[$eventArgs.Index] } else { [string]$sender.Text }
    $selected = ($eventArgs.State -band [System.Windows.Forms.DrawItemState]::Selected) -ne 0
    $background = if ($selected) { $script:Forest } else { $script:Surface }
    $foreground = if ($selected) { [System.Drawing.Color]::White } else { $script:Ink }
    $fill = New-Object System.Drawing.SolidBrush($background)
    $textBrush = New-Object System.Drawing.SolidBrush($foreground)
    try {
        $eventArgs.Graphics.FillRectangle($fill, $eventArgs.Bounds)
        $size = $eventArgs.Graphics.MeasureString($label, $sender.Font)
        $x = $eventArgs.Bounds.Left + 4
        $y = $eventArgs.Bounds.Top + (($eventArgs.Bounds.Height - $size.Height) / 2)
        $eventArgs.Graphics.DrawString($label, $sender.Font, $textBrush, [single]$x, [single]$y)
    } finally { $fill.Dispose(); $textBrush.Dispose() }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Zombie Farm 游戏管理'
# Height is sized to the content (see the tab height below) rather than padded out,
# so there is no dead space at the bottom of either tab.
$form.ClientSize = New-Object System.Drawing.Size(960, 574)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = $font
$form.BackColor = $paper
$form.ForeColor = $ink

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Zombie Farm 游戏管理'
$title.Font = $fontTitle
$title.ForeColor = $ink
$title.Location = New-Object System.Drawing.Point(22, 12)
$title.AutoSize = $true
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = '设置写入 touchHLE_options.txt，只影响 Zombie Farm；改动立即保存'
$subtitle.Font = $fontSmall
$subtitle.ForeColor = $grey
$subtitle.Location = New-Object System.Drawing.Point(24, 44)
$subtitle.AutoSize = $true
$form.Controls.Add($subtitle)

$btnTheme = New-Object System.Windows.Forms.Button
$btnTheme.Location = New-Object System.Drawing.Point(900, 11)
$btnTheme.Size = New-Object System.Drawing.Size(38, 38)
$btnTheme.FlatStyle = 'Flat'
$btnTheme.FlatAppearance.BorderSize = 1
$btnTheme.UseVisualStyleBackColor = $false
$btnTheme.Font = New-Object System.Drawing.Font('Segoe MDL2 Assets', 13)
$btnTheme.AccessibleName = '日夜模式切换'
$form.Controls.Add($btnTheme)
$themeTip = New-Object System.Windows.Forms.ToolTip

# A restrained gold rule separates the app heading from the page navigation.
$headerRule = New-Object System.Windows.Forms.Panel
$headerRule.Location = New-Object System.Drawing.Point(22, 63)
$headerRule.Size = New-Object System.Drawing.Size(916, 2)
$headerRule.BackColor = $amber
$form.Controls.Add($headerRule)

$tabs = New-Object PaletteTabControl
$tabs.Location = New-Object System.Drawing.Point(20, 72)
# Height is set at the bottom of this file, once every tab's contents exist, so it
# always matches the taller tab. Hardcoding it meant the game tab (which grew when
# the IPA picker was added) ended up flush against the tab's bottom edge.
$tabs.Size = New-Object System.Drawing.Size(920, 100)
$tabs.Font = $font
$tabs.DrawMode = [System.Windows.Forms.TabDrawMode]::OwnerDrawFixed
$tabs.Appearance = [System.Windows.Forms.TabAppearance]::FlatButtons
$form.Controls.Add($tabs)

$tabGame = New-Object System.Windows.Forms.TabPage
$tabGame.Text = '  游戏  '
$tabGame.UseVisualStyleBackColor = $false
$tabGame.BackColor = $paper
$tabs.Controls.Add($tabGame)

$tabSettings = New-Object System.Windows.Forms.TabPage
$tabSettings.Text = '  设置  '
$tabSettings.UseVisualStyleBackColor = $false
$tabSettings.BackColor = $paper
$tabs.Controls.Add($tabSettings)

$tabSave = New-Object System.Windows.Forms.TabPage
$tabSave.Text = '  存档  '
$tabSave.UseVisualStyleBackColor = $false
$tabSave.BackColor = $paper
$tabs.Controls.Add($tabSave)

# --- game tab: IPA selection ------------------------------------------------
#
# Which IPA to launch. The folder holds three different bundle identifiers, and
# both touchHLE_options.txt and the sandbox save folder are keyed on that id, so
# switching IPA also switches which settings line applies and which saves are
# visible -- the label under the dropdown spells that out.

$grpIpa = New-Object PaletteGroupBox
$grpIpa.Text = '游戏版本 (IPA)'
$grpIpa.Location = New-Object System.Drawing.Point(14, 8)
$grpIpa.Size = New-Object System.Drawing.Size(892, 74)
$grpIpa.Font = $font
$tabGame.Controls.Add($grpIpa)

$cmbIpa = New-Object PaletteComboBox
$cmbIpa.Location = New-Object System.Drawing.Point(14, 26)
$cmbIpa.Size = New-Object System.Drawing.Size(778, 24)
$cmbIpa.DropDownStyle = 'DropDownList'
$cmbIpa.DrawMode = 'OwnerDrawFixed'
$cmbIpa.ItemHeight = 20
$cmbIpa.FlatStyle = 'Flat'
$cmbIpa.Add_DrawItem($script:PaletteComboDraw)
$cmbIpa.Font = $font
$grpIpa.Controls.Add($cmbIpa)

$btnIpaBrowse = New-Object System.Windows.Forms.Button
$btnIpaBrowse.Text = '浏览…'
$btnIpaBrowse.Location = New-Object System.Drawing.Point(800, 25)
$btnIpaBrowse.Size = New-Object System.Drawing.Size(76, 26)
$btnIpaBrowse.FlatStyle = 'Flat'
$grpIpa.Controls.Add($btnIpaBrowse)

$lblIpaInfo = New-Object System.Windows.Forms.Label
$lblIpaInfo.Text = ''
$lblIpaInfo.Location = New-Object System.Drawing.Point(14, 52)
$lblIpaInfo.Size = New-Object System.Drawing.Size(860, 18)
$lblIpaInfo.Font = $fontSmall
$lblIpaInfo.ForeColor = $grey
$grpIpa.Controls.Add($lblIpaInfo)

# --- game tab: launch buttons ----------------------------------------------

$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = '启动游戏'
$btnStart.Location = New-Object System.Drawing.Point(16, 92)
$btnStart.Size = New-Object System.Drawing.Size(430, 52)
$btnStart.Font = $fontBold
$btnStart.BackColor = $forest
$btnStart.ForeColor = [System.Drawing.Color]::White
$btnStart.FlatStyle = 'Flat'
$btnStart.FlatAppearance.BorderSize = 0
$tabGame.Controls.Add($btnStart)

$btnStartSkip = New-Object System.Windows.Forms.Button
$btnStartSkip.Text = '启动并跳过时间…'
$btnStartSkip.Location = New-Object System.Drawing.Point(456, 92)
$btnStartSkip.Size = New-Object System.Drawing.Size(430, 52)
$btnStartSkip.FlatStyle = 'Flat'
$btnStartSkip.BackColor = $softGreen
$btnStartSkip.ForeColor = $forest
$tabGame.Controls.Add($btnStartSkip)

# --- settings tab ---------------------------------------------------------

# Rows are laid out at a fixed pitch and the group box height is derived from the
# number of ROWS, so adding or removing a setting cannot leave a blank gap or clip
# the last row. Longer explanations live in 使用说明.html.
#
# A setting may share a row with another by naming the same `Row`; window_family
# and window_scale do, because the user asked for them side by side ("左边可以选
# ipad ... 右侧可以自定义 --scale-hack"). Sharing a row is why the height counts
# distinct Row names rather than SettingDefs entries.
$script:RowPitch = 40

$script:RowNames = @()
foreach ($key in $script:SettingDefs.Keys) {
    $def = $script:SettingDefs[$key]
    $row = if ($def.ContainsKey('Row')) { $def.Row } else { $key }
    if ($script:RowNames -notcontains $row) { $script:RowNames += $row }
}

$grpSettings = New-Object PaletteGroupBox
$grpSettings.Text = '设置'
$grpSettings.Location = New-Object System.Drawing.Point(147, 10)
$grpSettings.Height = ($script:RowNames.Count * $script:RowPitch) + 26
$grpSettings.Width = 626
$tabSettings.Controls.Add($grpSettings)

$script:Controls = @{}
# Per-setting numeric/text editor for the 自定义 entry, plus its label and unit,
# so Update-CustomEnabled can enable/disable the whole triple.
$script:CustomEditors = @{}
# Row name -> its Y offset. NOTE: the local read below must NOT be named `$rowY`,
# because PowerShell variable names are case-INSENSITIVE, so a plain `$rowY` at
# script scope IS `$script:RowY` - assigning the integer would destroy the
# hashtable on the very first iteration.
$script:RowOffsets = @{}
$y = 26
foreach ($key in $script:SettingDefs.Keys) {
    $def = $script:SettingDefs[$key]
    $row = if ($def.ContainsKey('Row')) { $def.Row } else { $key }
    if (-not $script:RowOffsets.ContainsKey($row)) {
        $script:RowOffsets[$row] = $y
        $y += $script:RowPitch
    }
    $rowY = $script:RowOffsets[$row]

    # An empty Label means this control shares the row's label with a neighbour.
    if ($def.Label) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = $def.Label
        $width = if ($def.ContainsKey('LabelWidth')) { $def.LabelWidth } else { 150 }
        $lbl.Location = New-Object System.Drawing.Point(14, ($rowY + 5))
        $lbl.Size = New-Object System.Drawing.Size($width, 22)
        $grpSettings.Controls.Add($lbl)
    }

    $comboX = if ($def.ContainsKey('ComboX')) { $def.ComboX } else { 170 }
    $comboW = if ($def.ContainsKey('ComboW')) { $def.ComboW } else { 200 }

    $combo = New-Object PaletteComboBox
    $combo.Location = New-Object System.Drawing.Point($comboX, $rowY)
    $combo.Size = New-Object System.Drawing.Size($comboW, 24)
    $combo.DropDownStyle = 'DropDownList'
    $combo.DrawMode = 'OwnerDrawFixed'
    $combo.ItemHeight = 20
    $combo.FlatStyle = 'Flat'
    $combo.Add_DrawItem($script:PaletteComboDraw)
    $combo.Tag = $key
    # Plain values only: long "value — explanation" strings overflowed the control.
    # The explanation lives in 使用说明.html (shipped beside the manager).
    foreach ($choice in $def.Choices) {
        [void]$combo.Items.Add($choice.Text)
    }
    $grpSettings.Controls.Add($combo)
    $script:Controls[$key] = $combo

    # A setting with AllowCustom gets an extra editor for its 自定义 entry, only
    # enabled while 自定义 is selected.
    if ($def.AllowCustom) {
        $kind = if ($def.ContainsKey('CustomKind')) { $def.CustomKind } else { 'int' }
        $editorX = if ($def.ContainsKey('CustomX')) { $def.CustomX } else { 496 }
        $editorW = if ($def.ContainsKey('CustomWidth')) { $def.CustomWidth } else { 80 }

        # An empty CustomLabel means the editor needs no label of its own (the
        # dropdown right before it already says 自定义).
        if ($def.CustomLabel) {
            $lblCustom = New-Object System.Windows.Forms.Label
            $lblCustom.Text = $def.CustomLabel
            $lblCustom.Location = New-Object System.Drawing.Point(($editorX - 76), ($rowY + 5))
            $lblCustom.Size = New-Object System.Drawing.Size(74, 22)
            $lblCustom.TextAlign = 'MiddleRight'
            $grpSettings.Controls.Add($lblCustom)
        } else {
            $lblCustom = $null
        }

        if ($kind -eq 'scale') {
            # --scale-hack is parsed by touchHLE itself, which accepts a fraction
            # ("7/4") as well as a decimal ("1.75"). A NumericUpDown cannot express
            # a fraction, and silently rewriting a hand-edited 13/8 into a rounded
            # decimal would change the window size behind the user's back - so the
            # scale entry is a text box validated against exactly the grammar
            # touchHLE accepts (Test-CustomSpelling).
            $editor = New-Object System.Windows.Forms.TextBox
            $editor.TextAlign = 'Center'
            # Start from the preset the user is leaving, so selecting 自定义 does
            # not blank the value and leave the setting in limbo. Load-SettingsIntoUi
            # overwrites this with the stored value when there is one.
            $editor.Text = if ($def.ContainsKey('CustomInitial')) { [string]$def.CustomInitial } else { [string]$def.Default }
        } else {
            $editor = New-Object System.Windows.Forms.TextBox
            # DecimalPlaces must be set BEFORE Minimum/Maximum: the bounds are
            # coerced to the current precision when assigned, so setting 1.01 as a
            # minimum while DecimalPlaces is still 0 would silently store 1.
            $decimals = if ($def.ContainsKey('CustomDecimals')) { [int]$def.CustomDecimals } else { 0 }
            $step = if ($def.ContainsKey('CustomStep')) { [decimal]$def.CustomStep } else { [decimal]1 }
            # Start at a sensible value rather than at Minimum: selecting 自定义
            # would otherwise immediately mean 1 fps (or a 1.01 zoom step), and
            # the user would have to correct it before the setting was usable.
            $initial = if ($def.ContainsKey('CustomInitial')) { [decimal]$def.CustomInitial } else { [decimal]$def.CustomMin }
            $editor.TextAlign = 'Center'
            $editor.MaxLength = 12
            $editor.Text = [string][Math]::Min([Math]::Max($initial, [decimal]$def.CustomMin), [decimal]$def.CustomMax)
        }
        $editor.Location = New-Object System.Drawing.Point($editorX, $rowY)
        $editor.Size = New-Object System.Drawing.Size($editorW, 24)
        $editor.Tag = $key
        $grpSettings.Controls.Add($editor)

        $lblUnit = $null
        if ($def.ContainsKey('CustomSuffix') -and $def.CustomSuffix) {
            $lblUnit = New-Object System.Windows.Forms.Label
            $lblUnit.Text = $def.CustomSuffix
            $lblUnit.Location = New-Object System.Drawing.Point(($editorX + $editorW + 4), ($rowY + 5))
            $lblUnit.Size = New-Object System.Drawing.Size(24, 22)
            $grpSettings.Controls.Add($lblUnit)
        }

        $script:CustomEditors[$key] = @{
            Kind   = $kind
            Editor = $editor
            Label  = $lblCustom
            Unit   = $lblUnit
        }
    }

    # The window row ends with a live readout of the size the family+scale pair
    # actually produces, so the two dropdowns still read as one decision. With the
    # "?" buttons gone there is room for a wider readout, so a 4-digit size like
    # 1792 × 1344 is never clipped.
    if ($key -eq 'window_scale') {
        $script:LblWindowSize = New-Object System.Windows.Forms.Label
        $script:LblWindowSize.Text = ''
        $script:LblWindowSize.Location = New-Object System.Drawing.Point(452, ($rowY + 5))
        $script:LblWindowSize.Size = New-Object System.Drawing.Size(164, 22)
        $script:LblWindowSize.Font = $fontSmall
        $script:LblWindowSize.ForeColor = $sage
        $grpSettings.Controls.Add($script:LblWindowSize)
    }
}

# --- game tab: currency ----------------------------------------------------

$grpCurrency = New-Object PaletteGroupBox
$grpCurrency.Text = '金币与脑子'
$grpCurrency.Location = New-Object System.Drawing.Point(14, 158)
$grpCurrency.Size = New-Object System.Drawing.Size(892, 112)
$tabGame.Controls.Add($grpCurrency)

$lblGold = New-Object System.Windows.Forms.Label
$lblGold.Text = '金币'
$lblGold.Location = New-Object System.Drawing.Point(20, 34)
$lblGold.Size = New-Object System.Drawing.Size(50, 22)
$grpCurrency.Controls.Add($lblGold)

$numGold = New-Object System.Windows.Forms.TextBox
$numGold.Location = New-Object System.Drawing.Point(75, 31)
$numGold.Size = New-Object System.Drawing.Size(240, 24)
$numGold.MaxLength = 10
$numGold.TextAlign = 'Center'
$numGold.Text = '0'
$grpCurrency.Controls.Add($numGold)

$lblBrains = New-Object System.Windows.Forms.Label
$lblBrains.Text = '脑子'
$lblBrains.Location = New-Object System.Drawing.Point(350, 34)
$lblBrains.Size = New-Object System.Drawing.Size(50, 22)
$grpCurrency.Controls.Add($lblBrains)

$numBrains = New-Object System.Windows.Forms.TextBox
$numBrains.Location = New-Object System.Drawing.Point(405, 31)
$numBrains.Size = New-Object System.Drawing.Size(240, 24)
$numBrains.MaxLength = 10
$numBrains.TextAlign = 'Center'
$numBrains.Text = '0'
$grpCurrency.Controls.Add($numBrains)

$btnApplyCurrency = New-Object System.Windows.Forms.Button
$btnApplyCurrency.Text = '写入存档'
$btnApplyCurrency.Location = New-Object System.Drawing.Point(665, 28)
$btnApplyCurrency.Size = New-Object System.Drawing.Size(210, 30)
$btnApplyCurrency.FlatStyle = 'Flat'
$grpCurrency.Controls.Add($btnApplyCurrency)

$lblCurrencyState = New-Object System.Windows.Forms.Label
$lblCurrencyState.Text = ''
$lblCurrencyState.Location = New-Object System.Drawing.Point(20, 69)
$lblCurrencyState.Size = New-Object System.Drawing.Size(850, 24)
$lblCurrencyState.Font = $fontSmall
$lblCurrencyState.ForeColor = $grey
$grpCurrency.Controls.Add($lblCurrencyState)

# --- save tab --------------------------------------------------------------

$lblSaveInfo = New-Object System.Windows.Forms.Label
$lblSaveInfo.Text = ''
$lblSaveInfo.Location = New-Object System.Drawing.Point(14, 14)
$lblSaveInfo.Size = New-Object System.Drawing.Size(892, 22)
$lblSaveInfo.Font = $fontSmall
$lblSaveInfo.ForeColor = $grey
$tabSave.Controls.Add($lblSaveInfo)

$btnBackup = New-Object System.Windows.Forms.Button
$btnBackup.Text = '新增备份'
$btnBackup.Location = New-Object System.Drawing.Point(14, 42)
$btnBackup.Size = New-Object System.Drawing.Size(180, 36)
$btnBackup.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnBackup)

$btnRestore = New-Object System.Windows.Forms.Button
$btnRestore.Text = '还原所选备份'
$btnRestore.Location = New-Object System.Drawing.Point(238, 42)
$btnRestore.Size = New-Object System.Drawing.Size(210, 36)
$btnRestore.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnRestore)

$btnDelete = New-Object System.Windows.Forms.Button
$btnDelete.Text = '删除所选'
$btnDelete.Location = New-Object System.Drawing.Point(462, 42)
$btnDelete.Size = New-Object System.Drawing.Size(210, 36)
$btnDelete.FlatStyle = 'Flat'
$btnDelete.ForeColor = $forest
$tabSave.Controls.Add($btnDelete)

$btnRefresh = New-Object System.Windows.Forms.Button
$btnRefresh.Text = '刷新'
$btnRefresh.Location = New-Object System.Drawing.Point(686, 42)
$btnRefresh.Size = New-Object System.Drawing.Size(210, 36)
$btnRefresh.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnRefresh)

$listSaves = New-Object System.Windows.Forms.ListView
$listSaves.Location = New-Object System.Drawing.Point(14, 90)
$listSaves.Size = New-Object System.Drawing.Size(892, 272)
$listSaves.View = 'Details'
$listSaves.FullRowSelect = $true
# Multi-select so several backups can be deleted at once. Restore stays
# single-selection: restoring two saves at the same time is meaningless.
$listSaves.MultiSelect = $true
$listSaves.HideSelection = $false
$listSaves.GridLines = $false
$listSaves.OwnerDraw = $true
$listSaves.BorderStyle = 'None'
$listSaves.Font = $fontSmall
[void]$listSaves.Columns.Add('类型', 100)
[void]$listSaves.Columns.Add('备份文件', 560)
[void]$listSaves.Columns.Add('大小', 80, 'Right')
[void]$listSaves.Columns.Add('时间', 100)
$resizeSaveColumns = {
    param($sender, $eventArgs)
    $fixedWidth = $sender.Columns[0].Width + $sender.Columns[1].Width + $sender.Columns[2].Width
    $sender.Columns[3].Width = [Math]::Max(100, ($sender.ClientSize.Width - $fixedWidth))
}
$listSaves.Add_Resize($resizeSaveColumns)
$resizeSaveColumns.Invoke($listSaves, [EventArgs]::Empty)
$listSaves.Add_DrawColumnHeader({
    param($sender, $eventArgs)
    $background = New-Object System.Drawing.SolidBrush($script:Surface)
    $linePen = New-Object System.Drawing.Pen($script:Line)
    try {
        $eventArgs.Graphics.FillRectangle($background, $eventArgs.Bounds)
        $flags = [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
            [System.Windows.Forms.TextFormatFlags]::EndEllipsis -bor
            [System.Windows.Forms.TextFormatFlags]::NoPrefix
        switch ($eventArgs.Header.TextAlign) {
            'Right'  { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::Right }
            'Center' { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::HorizontalCenter }
            default  { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::Left }
        }
        $bounds = $eventArgs.Bounds
        $bounds.Inflate(-6, 0)
        [System.Windows.Forms.TextRenderer]::DrawText(
            $eventArgs.Graphics, $eventArgs.Header.Text, $eventArgs.Font,
            $bounds, $script:Ink, $flags)
        $eventArgs.Graphics.DrawLine($linePen, $eventArgs.Bounds.Left,
            $eventArgs.Bounds.Bottom - 1, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Bottom - 1)
        $eventArgs.Graphics.DrawLine($linePen, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Top, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Bottom - 1)
    } finally {
        $background.Dispose(); $linePen.Dispose()
    }
})
$listSaves.Add_DrawItem({
    param($sender, $eventArgs)
    if ($sender.View -ne [System.Windows.Forms.View]::Details) { $eventArgs.DrawDefault() }
})
$listSaves.Add_DrawSubItem({
    param($sender, $eventArgs)
    $selected = ($eventArgs.ItemState -band [System.Windows.Forms.ListViewItemStates]::Selected) -ne 0
    $background = if ($selected) { $script:SoftGreen } else { $script:Surface }
    $foreground = if ($selected) { $script:Ink } else { $eventArgs.Item.ForeColor }
    if ($foreground.IsEmpty -or $foreground -eq [System.Drawing.Color]::Empty) {
        $foreground = $script:Ink
    }
    $fill = New-Object System.Drawing.SolidBrush($background)
    $linePen = New-Object System.Drawing.Pen($script:Line)
    try {
        $eventArgs.Graphics.FillRectangle($fill, $eventArgs.Bounds)
        $flags = [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
            [System.Windows.Forms.TextFormatFlags]::EndEllipsis -bor
            [System.Windows.Forms.TextFormatFlags]::NoPrefix
        switch ($eventArgs.Header.TextAlign) {
            'Right'  { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::Right }
            'Center' { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::HorizontalCenter }
            default  { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::Left }
        }
        $bounds = $eventArgs.Bounds
        $bounds.Inflate(-6, 0)
        [System.Windows.Forms.TextRenderer]::DrawText(
            $eventArgs.Graphics, $eventArgs.SubItem.Text, $eventArgs.SubItem.Font,
            $bounds, $foreground, $flags)
        $eventArgs.Graphics.DrawLine($linePen, $eventArgs.Bounds.Left,
            $eventArgs.Bounds.Bottom - 1, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Bottom - 1)
        $eventArgs.Graphics.DrawLine($linePen, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Top, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Bottom - 1)
    } finally { $fill.Dispose(); $linePen.Dispose() }
})
$tabSave.Controls.Add($listSaves)

# Select-all / invert helpers: clicking through dozens of rows one at a time to
# delete them is exactly the chore this tab should remove.
$btnSelectAll = New-Object System.Windows.Forms.Button
$btnSelectAll.Text = '全选备份'
$btnSelectAll.Location = New-Object System.Drawing.Point(14, 368)
$btnSelectAll.Size = New-Object System.Drawing.Size(120, 28)
$btnSelectAll.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnSelectAll)

$btnSelectNone = New-Object System.Windows.Forms.Button
$btnSelectNone.Text = '取消选择'
$btnSelectNone.Location = New-Object System.Drawing.Point(142, 368)
$btnSelectNone.Size = New-Object System.Drawing.Size(120, 28)
$btnSelectNone.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnSelectNone)

$btnSelectInvert = New-Object System.Windows.Forms.Button
$btnSelectInvert.Text = '反选'
$btnSelectInvert.Location = New-Object System.Drawing.Point(270, 368)
$btnSelectInvert.Size = New-Object System.Drawing.Size(120, 28)
$btnSelectInvert.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnSelectInvert)

$lblSaveHint = New-Object System.Windows.Forms.Label
$lblSaveHint.Text = ''
$lblSaveHint.Location = New-Object System.Drawing.Point(400, 374)
$lblSaveHint.Size = New-Object System.Drawing.Size(500, 20)
$lblSaveHint.Font = $fontSmall
$lblSaveHint.ForeColor = $grey
$tabSave.Controls.Add($lblSaveHint)

# --- status ----------------------------------------------------------------

$status = New-Object System.Windows.Forms.Label
$status.Location = New-Object System.Drawing.Point(24, ($tabs.Top + $tabs.Height + 6))
$status.Size = New-Object System.Drawing.Size(916, 26)
$status.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 60)
$form.Controls.Add($status)

# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------

function Update-Status {
    param([string]$Message, [string]$Kind = 'info')

    $status.Text = $Message
    switch ($Kind) {
        'ok'   { $status.ForeColor = $sage }
        'err'  { $status.ForeColor = $red }
        'busy' { $status.ForeColor = $amber }
        default { $status.ForeColor = $script:Grey }
    }
    $status.Refresh()
}

# Read the text currently in a custom editor, whatever kind it is.
function Get-CustomEditorText {
    param([string]$Key)

    $entry = $script:CustomEditors[$Key]
    if (-not $entry) { return '' }
    return $entry.Editor.Text.Trim()
}

# Select the 自定义 entry of `key`'s dropdown, if it has one.
function Select-CustomChoice {
    param([string]$Key)

    $choices = $script:SettingDefs[$Key].Choices
    for ($i = 0; $i -lt $choices.Count; $i++) {
        if ($choices[$i].Value -eq 'custom') {
            $script:Controls[$Key].SelectedIndex = $i
            return
        }
    }
}

# Enable each custom editor only while its own dropdown sits on 自定义.
function Update-CustomEnabled {
    foreach ($key in $script:CustomEditors.Keys) {
        $customIndex = -1
        $choices = $script:SettingDefs[$key].Choices
        for ($i = 0; $i -lt $choices.Count; $i++) {
            if ($choices[$i].Value -eq 'custom') { $customIndex = $i; break }
        }
        $on = ($script:Controls[$key].SelectedIndex -eq $customIndex)
        $entry = $script:CustomEditors[$key]
        $entry.Editor.Enabled = $on
        if ($entry.Label) { $entry.Label.Enabled = $on }
        if ($entry.Unit) { $entry.Unit.Enabled = $on }
    }
}

# The same thing, read out of the live controls.
function Get-WindowSizeText {
    $family = [string]$script:SettingDefs['window_family'].Default
    $scale = [string]$script:SettingDefs['window_scale'].Default

    if ($script:Controls.ContainsKey('window_family')) {
        $c = $script:Controls['window_family']
        if ($c.SelectedIndex -ge 0) {
            $family = $script:SettingDefs['window_family'].Choices[$c.SelectedIndex].Value
        }
    }
    if ($script:Controls.ContainsKey('window_scale')) {
        $c = $script:Controls['window_scale']
        if ($c.SelectedIndex -ge 0) {
            $scale = $script:SettingDefs['window_scale'].Choices[$c.SelectedIndex].Value
        }
        if ($scale -eq 'custom') { $scale = Get-CustomEditorText -Key 'window_scale' }
    }

    return Get-WindowSizeForScale -Family $family -Scale $scale
}

function Update-WindowSizeLabel {
    if (-not $script:LblWindowSize) { return }

    $text = Get-WindowSizeText
    $script:LblWindowSize.Text = "窗口 $text"

    # Turn the readout red when the window would not fit the screen, since this
    # is the one place the user can see that before launching.
    $fits = $true
    if ($text -match '^窗口 (\d+) × (\d+)$') {
        $wa = [System.Windows.Forms.Screen]::FromControl($form).WorkingArea
        $fits = ([int]$Matches[1] -le $wa.Width) -and ([int]$Matches[2] -le $wa.Height)
    }
    $script:LblWindowSize.ForeColor = if ($fits) { $sage } else { $amber }
}

# Periodic resync for state that SelectedIndexChanged cannot be trusted to report.
#
# WinForms raises SelectedIndexChanged when the user picks an item, but NOT when
# the selection is changed by other means (the CB_SETCURSEL message, or a
# programmatic assignment that bypasses the event). Three things depend on that:
#
#   * the custom editors' enabled state (their dropdowns)
#   * the window-size readout (both window dropdowns)
#   * which app id / save folder is in force (IPA dropdown)
#
# A cheap periodic check removes the whole class of bug, and makes the UI testable
# by driving the controls with messages instead of synthetic mouse input.
$script:UiTimer = New-Object System.Windows.Forms.Timer
$script:UiTimer.Interval = 250
$script:UiTimer.Add_Tick({
    try {
        if (-not $script:UiReady) { return }

        # 1. custom editors' enabled state
        foreach ($key in $script:CustomEditors.Keys) {
            $customIndex = -1
            $choices = $script:SettingDefs[$key].Choices
            for ($i = 0; $i -lt $choices.Count; $i++) {
                if ($choices[$i].Value -eq 'custom') { $customIndex = $i; break }
            }
            $should = ($script:Controls[$key].SelectedIndex -eq $customIndex)
            if ($script:CustomEditors[$key].Editor.Enabled -ne $should) { Update-CustomEnabled }
        }

        # 2. window-size readout
        Update-WindowSizeLabel

        # 3. IPA selection: if the dropdown no longer matches the id in force,
        #    apply it. This is what makes switching work regardless of how the
        #    selection was changed.
        $sel = $cmbIpa.SelectedIndex
        if ($sel -ge 0 -and $sel -lt $script:IpaEntries.Count) {
            $entry = $script:IpaEntries[$sel]
            if ($entry.Path -ne $script:CurrentIpa.Path) {
                Apply-IpaSelection -IpaInfo $entry -Persist
            }
        }
    } catch {
        # Never let a resync failure take down the UI loop.
    }
})
$script:UiTimer.Start()

function Load-SettingsIntoUi {
    $settings = Get-CurrentSettings
    foreach ($key in $script:SettingDefs.Keys) {
        $def = $script:SettingDefs[$key]
        $value = [string]$settings[$key]

        $index = -1
        for ($i = 0; $i -lt $def.Choices.Count; $i++) {
            if ($def.Choices[$i].Value -eq $value) { $index = $i; break }
        }

        if ($index -lt 0 -and $def.AllowCustom) {
            # A custom value is stored as its number; show it in the editor and
            # select the 自定义 entry.
            $entry = $script:CustomEditors[$key]
            if ($entry) {
                $entry.Editor.Text = $value
            }
            for ($i = 0; $i -lt $def.Choices.Count; $i++) {
                if ($def.Choices[$i].Value -eq 'custom') { $index = $i; break }
            }
        }
        if ($index -lt 0) { $index = 0 }

        $script:Controls[$key].SelectedIndex = $index
    }
    Update-CustomEnabled
    Update-WindowSizeLabel
}

function Read-SettingsFromUi {
    $settings = [ordered]@{}
    foreach ($key in $script:SettingDefs.Keys) {
        $combo = $script:Controls[$key]
        $def = $script:SettingDefs[$key]
        $value = $def.Choices[$combo.SelectedIndex].Value

        if ($value -eq 'custom') {
            $value = Get-CustomEditorText -Key $key
        }
        $settings[$key] = $value
    }
    return $settings
}

function Save-SettingsFromUi {
    Save-Settings -Settings (Read-SettingsFromUi)
}

function Refresh-Currency {
    $c = Get-Currency
    if ($c) {
        $numGold.Text = [string][Math]::Min([int64]$c.Gold, [int64]2147483647)
        $numBrains.Text = [string][Math]::Min([int64]$c.Brains, [int64]2147483647)
        $lblCurrencyState.Text = "当前存档：金币 $($c.Gold)　脑子 $($c.Brains)"
        $lblCurrencyState.ForeColor = $grey
        $btnApplyCurrency.Enabled = $true
    } else {
        $lblCurrencyState.Text = '读不到存档（文件不存在或格式不符）'
        $lblCurrencyState.ForeColor = $red
        $btnApplyCurrency.Enabled = $false
    }
}

function Update-SaveTab {
    $listSaves.BeginUpdate()
    $listSaves.Items.Clear()

    $hadLive = Test-Path -LiteralPath $script:LiveSave
    if (-not $hadLive) {
        $lblSaveInfo.Text = '找不到当前存档。'
        $lblSaveInfo.ForeColor = $red
    } else {
        $live = Get-Item -LiteralPath $script:LiveSave
        $lblSaveInfo.Text = ("当前存档：saveGame.bin2　{0} 字节　{1}" -f `
            $live.Length, $live.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))
        $lblSaveInfo.ForeColor = $grey
    }

    # The live save is listed first and marked, because "which save is actually in
    # use?" is the question this tab has to answer at a glance. It is not a
    # backup: restoring and deleting are refused for it.
    if ($hadLive) {
        $live = Get-Item -LiteralPath $script:LiveSave
        $item = New-Object System.Windows.Forms.ListViewItem('正在使用')
        [void]$item.SubItems.Add($live.Name)
        [void]$item.SubItems.Add([string]$live.Length)
        [void]$item.SubItems.Add($live.LastWriteTime.ToString('MM-dd HH:mm'))
        $item.Tag = $live.FullName
        $item.ForeColor = $script:Sage
        $item.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 8.5, [System.Drawing.FontStyle]::Bold)
        [void]$listSaves.Items.Add($item)
    }

    $files = Get-BackupFiles
    foreach ($f in $files) {
        $kind = Get-BackupKind -File $f
        $item = New-Object System.Windows.Forms.ListViewItem($kind)
        [void]$item.SubItems.Add($f.Name)
        [void]$item.SubItems.Add([string]$f.Length)
        [void]$item.SubItems.Add($f.LastWriteTime.ToString('MM-dd HH:mm'))
        $item.Tag = $f.FullName
        [void]$listSaves.Items.Add($item)
    }
    $listSaves.EndUpdate()

    $size = 0
    foreach ($f in $files) { $size += $f.Length }
    $lblSaveHint.Text = ("共 {0} 个备份，{1:N1} KB" -f $files.Count, ($size / 1KB))
    Update-SelectionCount
}

# Selection feedback for the bulk buttons.
function Update-SelectionCount {
    $n = $listSaves.SelectedItems.Count
    $total = $listSaves.Items.Count
    if ($total -eq 0) { return }
    $lblSaveHint.Text = "已选 $n / $total 个备份"
}

# The live save is not a backup: refuse to restore or delete it through the UI.
function Test-IsLiveSave {
    param([string]$Path)
    return $Path -eq $script:LiveSave
}

# Restore operates on exactly one row. Multi-select exists for deleting, so take
# the first selection and say so if several rows happen to be selected.
function Get-SelectedBackup {
    if ($listSaves.SelectedItems.Count -eq 0) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '请先在列表里选择一个备份。', '存档管理', 'OK', 'Information')
        return $null
    }
    if ($listSaves.SelectedItems.Count -gt 1) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '还原一次只能选一个备份。请只选中要还原的那一个。', '存档管理', 'OK', 'Information')
        return $null
    }
    return [string]$listSaves.SelectedItems[0].Tag
}

# Every selected row that is a real backup (never the live save).
function Get-SelectedBackups {
    $paths = @()
    foreach ($item in $listSaves.SelectedItems) {
        $p = [string]$item.Tag
        if (Test-IsLiveSave -Path $p) { continue }
        $paths += $p
    }
    return $paths
}

# Human-readable name for a setting, for the status line. A setting that shares a
# row (window_scale) has an empty Label of its own, so it falls back to its own
# name rather than reporting a blank.
function Get-SettingTitle {
    param([string]$Key)

    $def = $script:SettingDefs[$Key]
    if ($def.Label) { return $def.Label }
    switch ($Key) {
        'window_scale' { return '放大倍数' }
        'window_family' { return '窗口大小 / 分辨率' }
        default { return $Key }
    }
}

# Settings are persisted the moment they change: there is no OK/Apply button, so
# closing the window can never silently discard an edit.
$onSettingChanged = {
    param($sender, $eventArgs)

    if ($sender.SelectedIndex -lt 0) { return }
    if (-not $script:UiReady) { return }

    $key = [string]$sender.Tag
    try {
        Update-CustomEnabled
        Update-WindowSizeLabel
        Save-SettingsFromUi
        $def = $script:SettingDefs[$key]
        $value = $def.Choices[$sender.SelectedIndex].Value
        $shown = $def.Choices[$sender.SelectedIndex].Text
        if ($value -eq 'custom') {
            $shown = (Get-CustomEditorText -Key $key)
            if ($def.ContainsKey('CustomSuffix') -and $def.CustomSuffix) {
                $shown = "$shown $($def.CustomSuffix)"
            }
        }
        Update-Status ("已保存：{0} = {1}" -f (Get-SettingTitle -Key $key), $shown) 'ok'
    } catch {
        Update-Status ("保存失败：{0}" -f $_.Exception.Message) 'err'
    }
}

# A custom editor is part of its setting's value, so any edit to it must be saved
# too - not just a dropdown change.
#
# For the text-based scale editor the value is only written once it is complete
# and valid: an intermediate "1." or "7/" is not a scale touchHLE could parse, and
# persisting it would leave the options file in a state the game refuses to start
# from. TextBox gives no "editing finished" event worth relying on (Leave fires
# on focus change only), so validation happens here on every keystroke and the
# file is simply left alone until the text is valid.
$onCustomEditorChanged = {
    param($sender, $eventArgs)

    if (-not $script:UiReady) { return }

    $key = [string]$sender.Tag
    $entry = $script:CustomEditors[$key]
    if (-not $entry -or -not $entry.Editor.Enabled) { return }

    $text = Get-CustomEditorText -Key $key
    if (-not (Test-SettingValue -Key $key -Value $text)) {
        # Not (yet) a value touchHLE accepts: say so and keep the file as it was.
        # (Plain ASCII quotes: PowerShell 5.1 treats the curly “ ” as string
        # delimiters even inside a double-quoted string, which is a parse error.)
        Update-Status ("{0} 的值 '{1}' 无效，尚未保存。" -f (Get-SettingTitle -Key $key), $text) 'busy'
        return
    }

    try {
        Update-WindowSizeLabel
        Save-SettingsFromUi
        $shown = $text
        if ($script:SettingDefs[$key].ContainsKey('CustomSuffix') -and $script:SettingDefs[$key].CustomSuffix) {
            $shown = "$text $($script:SettingDefs[$key].CustomSuffix)"
        }
        Update-Status ("已保存：{0} = {1}" -f (Get-SettingTitle -Key $key), $shown) 'ok'
    } catch {
        Update-Status ("保存失败：{0}" -f $_.Exception.Message) 'err'
    }
}

foreach ($key in $script:SettingDefs.Keys) {
    $script:Controls[$key].Add_SelectedIndexChanged($onSettingChanged)
}
foreach ($key in $script:CustomEditors.Keys) {
    $entry = $script:CustomEditors[$key]
    # Intermediate numeric text is validated before it is written.
    $entry.Editor.Add_TextChanged($onCustomEditorChanged)
}

# --- launching -------------------------------------------------------------
#
# Self-contained: this does NOT call StartZombieFarmNextHour.ps1. The launcher
# logic (IPA path, cumulative time offset, the -Quiet no-console trick) is
# reproduced here so the manager is a single file with no helper-script
# dependency. The steps are kept identical to the original on purpose:
#
#   1. read the cumulative offset from touchHLE_time_offset_seconds.txt
#   2. add this run's increment (skipped when the user chose not to skip)
#   3. write the offset file back
#   4. export TOUCHHLE_TIME_OFFSET_SECONDS
#   5. write zfr_last_launch.txt with the IPA fingerprint
#   6. start touchHLE.exe with CreateNoWindow so no console is allocated
#
# touchHLE.exe is a CONSOLE-subsystem program, so letting it inherit a console
# would pop up the very black window this UI exists to avoid.
#
# Get-LaunchPaths lives near the top of the file, with the other helpers.

# Start the game and block until it exits.
#
#   -SkipSeconds 0 means "do not advance the clock", otherwise the cumulative
#   offset is increased by that many seconds.
function Start-GameProcess {
    param(
        [Parameter(Mandatory = $true)][int64]$SkipSeconds,
        [Parameter(Mandatory = $true)][string]$BusyMessage
    )

    $paths = Get-LaunchPaths

    if (-not (Test-Path -LiteralPath $paths.TouchHLE)) {
        throw "找不到 touchHLE.exe：$($paths.TouchHLE)"
    }
    if (-not (Test-Path -LiteralPath $paths.Ipa)) {
        throw "找不到游戏 IPA：$($paths.Ipa)"
    }

    # Cumulative offset bookkeeping, same as the command-line launcher.
    [int64]$offset = 0
    if (Test-Path -LiteralPath $paths.OffsetFile) {
        $saved = (Get-Content -LiteralPath $paths.OffsetFile -Raw).Trim()
        if ($saved -and -not [int64]::TryParse($saved, [ref]$offset)) {
            throw "时间偏移文件内容无效：$($paths.OffsetFile)"
        }
    }
    if ($offset -lt 0 -or $SkipSeconds -gt ([int64]::MaxValue - $offset)) {
        throw '累计时间偏移会超出 Int64 范围。'
    }
    if ($SkipSeconds -gt 0) {
        $offset += $SkipSeconds
        [System.IO.File]::WriteAllText($paths.OffsetFile, [string]$offset)
    }

    # Diagnostic fingerprint: which IPA build actually ran.
    @(
        "ipa = $(Split-Path -Leaf $paths.Ipa)"
        "sha256 = $((Get-FileHash -LiteralPath $paths.Ipa -Algorithm SHA256).Hash)"
        "launched = $(Get-Date -Format o)"
    ) | Set-Content -LiteralPath $paths.Fingerprint -Encoding utf8

    # The child inherits the parent's environment, so setting it here reaches
    # touchHLE. --device-family and the rest come from touchHLE_options.txt, which
    # this UI writes; passing them on the command line would override that file.
    $env:TOUCHHLE_TIME_OFFSET_SECONDS = [string]$offset

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $paths.TouchHLE
    # Quotes matter: the IPA file name contains spaces.
    $psi.Arguments = '"' + $paths.Ipa + '" --landscape-right'
    # MUST be touchHLE's own folder. src/paths.rs resolves resources against the
    # current directory (Path::new(".") on Windows), not the executable location,
    # so starting this from anywhere else panics with
    #   Unexpected I/O failure ... "touchHLE_dylibs/libz.1.2.3.dylib"
    $psi.WorkingDirectory = $paths.WorkingDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    Update-Status $BusyMessage 'busy'
    $form.Hide()

    # The log belongs beside touchHLE's other state, not in the parent folder.
    $logFile = Join-Path $script:HleDir 'zfr_last_run.log'
    $proc = [System.Diagnostics.Process]::Start($psi)
    # Drain both pipes concurrently; reading them one after the other can deadlock
    # if the child fills the second pipe's buffer while we block on the first.
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()

    $proc.WaitForExit()
    $out = ''; $err = ''
    try { $out = $outTask.Result } catch { }
    try { $err = $errTask.Result } catch { }

    if ($out -or $err) {
        $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $text = "[$stamp] exit=$($proc.ExitCode)`r`n$out`r`n$err`r`n"
        Add-Content -LiteralPath $logFile -Value $text -Encoding UTF8
    }

    $form.Show()
    $form.Activate()
    Refresh-Currency
    Update-SaveTab

    if ($proc.ExitCode -eq 0) {
        Update-Status '游戏已退出。' 'info'
    } else {
        Update-Status ("游戏退出，代码 {0}（详见 zfr_last_run.log）" -f $proc.ExitCode) 'err'
    }
}

$btnStart.Add_Click({
    if (Test-GameRunning) { Update-Status '游戏已经在运行了。' 'busy'; return }
    try {
        Start-GameProcess -SkipSeconds 0 -BusyMessage '正在启动…'
    } catch {
        $form.Show()
        Update-Status ("启动失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message, '启动失败', 'OK', 'Error')
    }
})

$btnStartSkip.Add_Click({
    if (Test-GameRunning) { Update-Status '游戏已经在运行了。' 'busy'; return }

    # Collect hours/minutes in two numeric boxes (no HH:MM string to type), in a
    # modal dialog rather than console input, so the UI never hands control back
    # to a terminal. Pre-fill from last time (Read-SkipMemory), default 6h00m.
    $mem = Read-SkipMemory
    $defH = if ($mem) { $mem.Hours } else { 6 }
    $defM = if ($mem) { $mem.Minutes } else { 0 }

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = '跳过时间'
    $dlg.ClientSize = New-Object System.Drawing.Size(344, 150)
    $dlg.StartPosition = 'CenterParent'
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    $dlg.Font = $font
    $dlg.BackColor = $script:Paper
    $dlg.ForeColor = $script:Ink

    $l1 = New-Object System.Windows.Forms.Label
    $l1.Text = '快进多久？（只填数字）'
    $l1.Location = New-Object System.Drawing.Point(18, 16)
    $l1.AutoSize = $true
    $l1.ForeColor = $script:Ink
    $dlg.Controls.Add($l1)

    $numH = New-Object System.Windows.Forms.TextBox
    $numH.Location = New-Object System.Drawing.Point(20, 46)
    $numH.Size = New-Object System.Drawing.Size(96, 24)
    $numH.MaxLength = 4
    $numH.Text = [string][Math]::Min($defH, 9999)
    $numH.TextAlign = 'Center'
    $numH.BackColor = $script:Surface
    $numH.ForeColor = $script:Ink
    $dlg.Controls.Add($numH)
    $numH.Add_KeyPress({ if (-not [char]::IsControl($_.KeyChar) -and -not [char]::IsDigit($_.KeyChar)) { $_.Handled = $true } })

    $lH = New-Object System.Windows.Forms.Label
    $lH.Text = '小时'
    $lH.Location = New-Object System.Drawing.Point(122, 49)
    $lH.AutoSize = $true
    $lH.ForeColor = $script:Ink
    $dlg.Controls.Add($lH)

    $numM = New-Object System.Windows.Forms.TextBox
    $numM.Location = New-Object System.Drawing.Point(180, 46)
    $numM.Size = New-Object System.Drawing.Size(80, 24)
    $numM.MaxLength = 2
    $numM.Text = [string]$defM
    $numM.TextAlign = 'Center'
    $numM.BackColor = $script:Surface
    $numM.ForeColor = $script:Ink
    $dlg.Controls.Add($numM)
    $numM.Add_KeyPress({ if (-not [char]::IsControl($_.KeyChar) -and -not [char]::IsDigit($_.KeyChar)) { $_.Handled = $true } })

    $lM = New-Object System.Windows.Forms.Label
    $lM.Text = '分钟'
    $lM.Location = New-Object System.Drawing.Point(266, 49)
    $lM.AutoSize = $true
    $lM.ForeColor = $script:Ink
    $dlg.Controls.Add($lM)

    $okBtn = New-Object System.Windows.Forms.Button
    $okBtn.Text = '开始'
    $okBtn.Location = New-Object System.Drawing.Point(142, 100)
    $okBtn.Size = New-Object System.Drawing.Size(86, 30)
    $okBtn.DialogResult = 'OK'
    $okBtn.FlatStyle = 'Flat'
    $okBtn.BackColor = $script:Forest
    $okBtn.ForeColor = [System.Drawing.Color]::White
    $okBtn.FlatAppearance.BorderSize = 0
    $dlg.Controls.Add($okBtn)

    $cancelBtn = New-Object System.Windows.Forms.Button
    $cancelBtn.Text = '取消'
    $cancelBtn.Location = New-Object System.Drawing.Point(238, 100)
    $cancelBtn.Size = New-Object System.Drawing.Size(86, 30)
    $cancelBtn.DialogResult = 'Cancel'
    $cancelBtn.FlatStyle = 'Flat'
    $cancelBtn.BackColor = $script:SoftGreen
    $cancelBtn.ForeColor = $script:Forest
    $cancelBtn.FlatAppearance.BorderSize = 0
    $dlg.Controls.Add($cancelBtn)

    $dlg.AcceptButton = $okBtn
    $dlg.CancelButton = $cancelBtn

    $result = $dlg.ShowDialog($form)
    $hoursText = $numH.Text.Trim()
    $minutesText = $numM.Text.Trim()
    $dlg.Dispose()
    if ($result -ne 'OK') { return }

    if ($hoursText -notmatch '^[0-9]{1,4}$' -or $minutesText -notmatch '^[0-9]{1,2}$') {
        [void][System.Windows.Forms.MessageBox]::Show('请输入有效的小时和分钟。', '跳过时间', 'OK', 'Warning')
        return
    }
    $hours = [int]$hoursText
    $minutes = [int]$minutesText
    if ($minutes -gt 59) {
        [void][System.Windows.Forms.MessageBox]::Show('分钟必须在 0～59 之间。', '跳过时间', 'OK', 'Warning')
        return
    }

    if ($hours -le 0 -and $minutes -le 0) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '总时间要大于零。', '跳过时间', 'OK', 'Warning')
        return
    }

    try {
        Save-SkipMemory -Hours $hours -Minutes $minutes
        $skipSeconds = ([int64]$hours * 3600) + ([int64]$minutes * 60)
        Start-GameProcess -SkipSeconds $skipSeconds `
            -BusyMessage ("正在启动（快进 {0} 小时 {1} 分）…" -f $hours, $minutes)
    } catch {
        $form.Show()
        Update-Status ("启动失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message, '启动失败', 'OK', 'Error')
    }
})

# --- save management -------------------------------------------------------

$btnBackup.Add_Click({
    if (Test-GameRunning) {
        Update-Status '游戏正在运行，请先关闭游戏再备份存档。' 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            '游戏正在运行。存档只在正常退出时写入，现在备份可能拿到不完整的状态。请先关闭游戏。',
            '无法备份', 'OK', 'Warning')
        return
    }
    try {
        $made = New-SaveBackup -Label 'manual'
        Update-SaveTab
        Update-Status ("已备份：{0}" -f [System.IO.Path]::GetFileName($made)) 'ok'
    } catch {
        Update-Status ("备份失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '备份失败', 'OK', 'Error')
    }
})

$btnRestore.Add_Click({
    $path = Get-SelectedBackup
    if (-not $path) { return }

    # The live save is shown in the list for reference but cannot be "restored"
    # onto itself.
    if (Test-IsLiveSave -Path $path) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '这是正在使用的存档本身，不是备份。请选择一条备份来还原。',
            '存档管理', 'OK', 'Information')
        return
    }
    if (Test-GameRunning) {
        Update-Status '游戏正在运行，请先关闭游戏再还原存档。' 'err'
        return
    }

    $name = [System.IO.Path]::GetFileName($path)
    $size = (Get-Item -LiteralPath $path).Length
    $answer = [System.Windows.Forms.MessageBox]::Show(
        ("要用这个备份覆盖当前存档吗？`n`n{0}`n{1} 字节`n`n当前存档会先自动另存为一份，所以可以反悔。" -f $name, $size),
        '还原备份', 'YesNo', 'Question')
    if ($answer -ne 'Yes') { return }

    try {
        [void](Restore-SaveBackup -BackupPath $path)
        Update-SaveTab
        Refresh-Currency
        Update-Status ("已还原：{0}" -f $name) 'ok'
    } catch {
        Update-Status ("还原失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '还原失败', 'OK', 'Error')
    }
})

$btnDelete.Add_Click({
    $paths = Get-SelectedBackups
    if ($paths.Count -eq 0) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '请先在列表里选择要删除的备份。', '存档管理', 'OK', 'Information')
        return
    }

    if ($paths.Count -eq 1) {
        $name = [System.IO.Path]::GetFileName($paths[0])
        $question = "确定删除这个备份吗？删掉就找不回来了。`n`n$name"
    } else {
        # Show a few names so a mis-click on "select all" is obvious before it is
        # too late, rather than just asking "delete 31 items?".
        $preview = ($paths | Select-Object -First 5 | ForEach-Object { [System.IO.Path]::GetFileName($_) }) -join "`n"
        if ($paths.Count -gt 5) { $preview += "`n… 等共 $($paths.Count) 个" }
        $question = "确定删除这 $($paths.Count) 个备份吗？删掉就找不回来了。`n`n$preview"
    }

    $answer = [System.Windows.Forms.MessageBox]::Show(
        $question, '删除备份', 'YesNo', 'Warning')
    if ($answer -ne 'Yes') { return }

    $done = 0
    $failed = @()
    foreach ($p in $paths) {
        try {
            [void](Remove-SaveBackup -BackupPath $p)
            $done++
        } catch {
            $failed += ("{0}: {1}" -f [System.IO.Path]::GetFileName($p), $_.Exception.Message)
        }
    }

    Update-SaveTab
    if ($failed.Count -eq 0) {
        Update-Status ("已删除 {0} 个备份。" -f $done) 'ok'
    } else {
        Update-Status ("已删除 {0} 个，{1} 个失败。" -f $done, $failed.Count) 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            ("以下备份删除失败：`n`n" + ($failed -join "`n")), '部分失败', 'OK', 'Warning')
    }
})

$btnRefresh.Add_Click({
    Update-SaveTab
    Refresh-Currency
    Update-Status '已刷新。' 'info'
})

$btnSelectAll.Add_Click({
    foreach ($item in $listSaves.Items) { $item.Selected = $true }
    Update-SelectionCount
})

$btnSelectNone.Add_Click({
    foreach ($item in $listSaves.Items) { $item.Selected = $false }
    Update-SelectionCount
})

$btnSelectInvert.Add_Click({
    foreach ($item in $listSaves.Items) { $item.Selected = -not $item.Selected }
    Update-SelectionCount
})

$listSaves.Add_ItemSelectionChanged({
    Update-SelectionCount
})

$listSaves.Add_DoubleClick({
    if ($listSaves.SelectedItems.Count -gt 0) { $btnRestore.PerformClick() }
})

# --- currency --------------------------------------------------------------

$btnApplyCurrency.Add_Click({
    if (Test-GameRunning) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '游戏正在运行。存档只在正常退出时写入，现在修改会被覆盖。请先关闭游戏。',
            '无法修改', 'OK', 'Warning')
        Update-Status '游戏正在运行，请先关闭游戏再改存档。' 'err'
        return
    }

    $goldText = $numGold.Text.Trim()
    $brainsText = $numBrains.Text.Trim()
    if ($goldText -notmatch '^[0-9]{1,10}$' -or $brainsText -notmatch '^[0-9]{1,10}$') {
        Update-Status '金币和脑子必须是 0～2147483647 的整数。' 'err'
        return
    }
    $gold64 = [int64]$goldText
    $brains64 = [int64]$brainsText
    if ($gold64 -gt 2147483647 -or $brains64 -gt 2147483647) {
        Update-Status '金币和脑子不能超过 2147483647。' 'err'
        return
    }
    $gold = [int]$gold64
    $brains = [int]$brains64

    $answer = [System.Windows.Forms.MessageBox]::Show(
        ("将把存档改为：`n`n金币 $gold`n脑子 $brains`n`n原存档会自动备份。继续吗？"),
        '确认修改', 'YesNo', 'Question')
    if ($answer -ne 'Yes') { return }

    try {
        # Self-contained writer; no helper script involved.
        $backupPath = Set-Currency -Gold $gold -Brains $brains
        Update-Status ("存档已更新，备份：{0}" -f [System.IO.Path]::GetFileName($backupPath)) 'ok'
        Refresh-Currency
        Update-SaveTab
    } catch {
        Update-Status ("写入失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message, '写入失败', 'OK', 'Error')
    }
})

# --- IPA selection behaviour -----------------------------------------------

# Fill the dropdown from zombie_farm_ipa\, remembering the detected bundle id for the
# entry currently chosen so the settings/save paths can be re-pointed.
$script:IpaEntries = @()

function Update-IpaInfoLabel {
    if ($null -eq $script:CurrentIpa) {
        $lblIpaInfo.Text = '未选择任何 IPA。'
        $lblIpaInfo.ForeColor = $red
        return
    }
    $info = $script:CurrentIpa
    if ($info.Error) {
        $lblIpaInfo.Text = "⚠ $($info.Error)　app id 仍按默认值使用"
        $lblIpaInfo.ForeColor = $red
        return
    }
    $sizeMb = [Math]::Round($info.Size / 1MB, 1)
    $lblIpaInfo.Text = ("app id: {0}　可执行文件: {1}　{2} MB" -f `
        $script:AppId, $info.Executable, $sizeMb)
    $lblIpaInfo.ForeColor = $grey
}

# Point every app-id-dependent path at the chosen IPA and refresh the views that
# depend on it (the saves and settings both live under the app id).
function Apply-IpaSelection {
    param(
        [Parameter(Mandatory = $true)]$IpaInfo,
        [switch]$Persist
    )

    Set-CurrentIpa -IpaInfo $IpaInfo
    if ($Persist) { Save-IpaSelection -Path $IpaInfo.Path }

    Update-IpaInfoLabel
    if ($script:UiReady) {
        Refresh-Currency
        Update-SaveTab
    }
}

function Initialize-IpaList {
    $script:IpaEntries = @()
    $script:IpaInfoCache = @{}

    $idCounts = @{}
    foreach ($f in (Get-IpaList)) {
        $info = Read-IpaInfo -Path $f.FullName
        $script:IpaInfoCache[$f.FullName] = $info
        $script:IpaEntries += $info
        $id = if ($info.AppId) { $info.AppId } else { '<未知>' }
        if (-not $idCounts.ContainsKey($id)) { $idCounts[$id] = 0 }
        $idCounts[$id]++
    }

    foreach ($info in $script:IpaEntries) {
        $id = if ($info.AppId) { $info.AppId } else { '<未知>' }
        # The dropdown is narrow, so only spell out the id where it is the odd one
        # out. With 29 files sharing one id, repeating it 29 times is noise, and
        # the minority id is exactly the case that changes saves and settings.
        $suffix = ''
        if ($idCounts[$id] -le 2) { $suffix = "　[$id]" }
        [void]$cmbIpa.Items.Add($info.Name + $suffix)
    }

    if ($script:IpaEntries.Count -eq 0) {
        $lblIpaInfo.Text = "在 $($script:IpaDir) 里找不到任何 .ipa 文件。"
        $lblIpaInfo.ForeColor = $red
        return
    }

    # Preselect the remembered/default IPA.
    $wanted = Get-DefaultIpaPath
    $index = 0
    for ($i = 0; $i -lt $script:IpaEntries.Count; $i++) {
        if ($script:IpaEntries[$i].Path -eq $wanted) { $index = $i; break }
    }
    $cmbIpa.SelectedIndex = $index      # fires the handler below
}

$cmbIpa.Add_SelectedIndexChanged({
    if ($cmbIpa.SelectedIndex -lt 0) { return }
    if ($cmbIpa.SelectedIndex -ge $script:IpaEntries.Count) { return }

    $info = $script:IpaEntries[$cmbIpa.SelectedIndex]

    # Only re-point things (and repopulate lists) once the UI is live; during
    # construction this fires before the save tab exists.
    if (-not $script:UiReady) {
        Set-CurrentIpa -IpaInfo $info
        Update-IpaInfoLabel
        return
    }

    try {
        Apply-IpaSelection -IpaInfo $info -Persist
        Update-Status ("已选择：{0}" -f $info.Name) 'ok'
    } catch {
        Update-Status ("切换 IPA 失败：{0}" -f $_.Exception.Message) 'err'
    }
})

$btnIpaBrowse.Add_Click({
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = '选择游戏 IPA'
    $dlg.Filter = 'iOS 应用包 (*.ipa)|*.ipa|所有文件 (*.*)|*.*'
    $dlg.InitialDirectory = $script:IpaDir
    if ($dlg.ShowDialog($form) -ne 'OK') { $dlg.Dispose(); return }

    $chosen = $dlg.FileName
    $dlg.Dispose()

    $info = Read-IpaInfo -Path $chosen
    if ($info.Error) {
        [void][System.Windows.Forms.MessageBox]::Show(
            ("这个文件读不出 app id：`n`n{0}`n`n仍然可以使用，但设置与存档会按默认 app id 处理。" -f $info.Error),
            '提示', 'OK', 'Warning')
    }

    # If it came from the managed folder it is already in the list; otherwise add
    # it so the choice is visible and switchable.
    $index = -1
    for ($i = 0; $i -lt $script:IpaEntries.Count; $i++) {
        if ($script:IpaEntries[$i].Path -eq $chosen) { $index = $i; break }
    }
    if ($index -lt 0) {
        $label = '{0}　[{1}]' -f $info.Name, $(if ($info.AppId) { $info.AppId } else { '未知 id' })
        [void]$cmbIpa.Items.Add($label)
        $script:IpaEntries += $info
        $index = $script:IpaEntries.Count - 1
    }

    $cmbIpa.SelectedIndex = $index
})

# --- startup / shutdown ----------------------------------------------------

$form.Add_Shown({
    $script:UiReady = $false       # suppress saves while the lists initialise
    Initialize-IpaList
    Load-SettingsIntoUi
    Refresh-Currency
    Update-SaveTab
    $script:UiReady = $true
    Update-Status '就绪。改动会立即保存。' 'info'
    Set-ManagerPalette -Night $script:NightMode
})

$form.Add_FormClosing({
    if (Test-GameRunning) {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            '游戏还在运行。关闭这个管理窗口不会关闭游戏，确定关闭吗？',
            '确认', 'YesNo', 'Question')
        if ($answer -ne 'Yes') { $_.Cancel = $true }
    }
})

function Set-ManagerPalette {
    param([bool]$Night)

    if ($Night) {
        $script:Ink = [System.Drawing.Color]::FromArgb(232, 237, 234)
        $script:Grey = [System.Drawing.Color]::FromArgb(165, 179, 173)
        $script:Red = [System.Drawing.Color]::FromArgb(224, 126, 116)
        $script:Forest = [System.Drawing.Color]::FromArgb(76, 139, 111)
        $script:Sage = [System.Drawing.Color]::FromArgb(126, 177, 146)
        $script:Amber = [System.Drawing.Color]::FromArgb(214, 168, 99)
        $script:Paper = [System.Drawing.Color]::FromArgb(29, 35, 38)
        $script:Surface = [System.Drawing.Color]::FromArgb(38, 46, 48)
        $script:SoftGreen = [System.Drawing.Color]::FromArgb(48, 65, 56)
        $script:Line = [System.Drawing.Color]::FromArgb(49, 59, 56)
        $hover = [System.Drawing.Color]::FromArgb(88, 151, 122)
        $pressed = [System.Drawing.Color]::FromArgb(61, 119, 96)
    } else {
        $script:Ink = [System.Drawing.Color]::FromArgb(38, 52, 58)
        $script:Grey = [System.Drawing.Color]::FromArgb(105, 122, 120)
        $script:Red = [System.Drawing.Color]::FromArgb(184, 78, 74)
        $script:Forest = [System.Drawing.Color]::FromArgb(45, 101, 87)
        $script:Sage = [System.Drawing.Color]::FromArgb(111, 148, 127)
        $script:Amber = [System.Drawing.Color]::FromArgb(214, 160, 82)
        $script:Paper = [System.Drawing.Color]::FromArgb(243, 246, 244)
        $script:Surface = [System.Drawing.Color]::White
        $script:SoftGreen = [System.Drawing.Color]::FromArgb(228, 236, 231)
        $script:Line = [System.Drawing.Color]::FromArgb(220, 228, 223)
        $hover = [System.Drawing.Color]::FromArgb(36, 83, 71)
        $pressed = [System.Drawing.Color]::FromArgb(39, 89, 75)
    }

    function Set-ControlColors($control) {
        if ($control -is [System.Windows.Forms.Label]) { $control.ForeColor = $script:Ink }
        elseif ($control -is [PaletteGroupBox]) {
            $control.BorderColor = $script:Line
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Paper
        }
        elseif ($control -is [System.Windows.Forms.TabPage]) {
            $control.UseVisualStyleBackColor = $false
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Paper
        }
        elseif ($control -is [System.Windows.Forms.TabControl]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Paper
        }
        elseif ($control -is [PaletteComboBox]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Surface
            $control.ArrowColor = $script:Surface
            $control.ArrowBorderColor = $script:Line
            $control.ArrowGlyphColor = $script:Grey
        }
        elseif ($control -is [System.Windows.Forms.TextBox]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Surface
            $control.BorderStyle = [System.Windows.Forms.BorderStyle]::None
        }
        elseif ($control -is [System.Windows.Forms.NumericUpDown] -or
                $control -is [System.Windows.Forms.ListView]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Surface
        }
        elseif ($control -is [System.Windows.Forms.CheckBox]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Paper
        }
        foreach ($child in $control.Controls) { Set-ControlColors $child }
    }

    $form.BackColor = $script:Paper; $form.ForeColor = $script:Ink
    foreach ($control in $form.Controls) { Set-ControlColors $control }
    $tabs.StripColor = $script:Paper
    $tabs.BorderColor = $script:Line
    $tabs.TabColor = $script:Surface
    $tabs.SelectedTabColor = $script:Forest
    $tabs.TabTextColor = if ($Night) { $script:Grey } else { $script:Ink }
    $tabs.SelectedTabTextColor = [System.Drawing.Color]::White
    $title.ForeColor = $script:Ink
    $subtitle.ForeColor = $script:Grey
    $btnTheme.Text = if ($Night) { [char]0xE708 } else { [char]0xE706 }
    $btnTheme.BackColor = $script:Surface
    $btnTheme.ForeColor = $script:Forest
    $btnTheme.FlatAppearance.BorderColor = $script:Line
    $themeTip.SetToolTip($btnTheme, $(if ($Night) { '切换到日间模式' } else { '切换到夜间模式' }))
    $headerRule.BackColor = $script:Amber
    $lblIpaInfo.ForeColor = $script:Grey
    $lblCurrencyState.ForeColor = $script:Grey
    $lblSaveInfo.ForeColor = $script:Grey
    $lblSaveHint.ForeColor = $script:Grey
    $status.ForeColor = $script:Grey

    foreach ($button in @(
        $btnIpaBrowse, $btnStartSkip, $btnApplyCurrency, $btnBackup, $btnRestore,
        $btnRefresh, $btnSelectAll, $btnSelectNone, $btnSelectInvert, $btnDelete
    )) {
        $button.BackColor = $script:SoftGreen
        $button.ForeColor = if ($Night) { $script:Sage } else { $script:Forest }
        $button.FlatStyle = 'Flat'
        $button.FlatAppearance.BorderColor = $script:Line
    }
    $btnStart.BackColor = $script:Forest
    $btnStart.ForeColor = [System.Drawing.Color]::White
    $btnStart.FlatAppearance.MouseOverBackColor = $hover
    $btnStart.FlatAppearance.MouseDownBackColor = $pressed
    if ($script:LblWindowSize) { $script:LblWindowSize.ForeColor = $script:Sage }
    if ($form.IsHandleCreated) {
        $captionColor = if ($Night) { [WindowChrome]::PackColor($script:Paper) } else { -1 }
        $captionTextColor = if ($Night) { [WindowChrome]::PackColor($script:Ink) } else { -1 }
        $captionBorderColor = if ($Night) { [WindowChrome]::PackColor($script:Line) } else { -1 }
        [WindowChrome]::Apply(
            $form.Handle, $Night, [int]$captionColor,
            [int]$captionTextColor, [int]$captionBorderColor)
    }
    $tabs.Invalidate()
}

$tabs.Add_DrawItem({
    param($sender, $eventArgs)
    $selected = $eventArgs.Index -eq $sender.SelectedIndex
    $background = if ($selected) { $script:Forest } else { $script:Surface }
    $foreground = if ($selected) { [System.Drawing.Color]::White } elseif ($script:NightMode) { $script:Grey } else { $script:Ink }
    $fill = New-Object System.Drawing.SolidBrush($background)
    $textBrush = New-Object System.Drawing.SolidBrush($foreground)
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    try {
        $eventArgs.Graphics.FillRectangle($fill, $eventArgs.Bounds)
        $bounds = $eventArgs.Bounds
        $text = $sender.TabPages[$eventArgs.Index].Text.Trim()
        $size = $eventArgs.Graphics.MeasureString($text, $sender.Font)
        $x = $bounds.Left + (($bounds.Width - $size.Width) / 2)
        $y = $bounds.Top + (($bounds.Height - $size.Height) / 2)
        $eventArgs.Graphics.DrawString($text, $sender.Font, $textBrush, [single]$x, [single]$y)
    } finally {
        $fill.Dispose(); $textBrush.Dispose(); $format.Dispose()
    }
})

Set-ManagerPalette -Night $script:NightMode
$btnTheme.Add_Click({
    $script:NightMode = -not $script:NightMode
    [System.IO.File]::WriteAllText(
        $script:NightModeFile,
        $(if ($script:NightMode) { '1' } else { '0' }),
        [System.Text.Encoding]::ASCII)
    Set-ManagerPalette -Night $script:NightMode
})

# --- size the window to its content ----------------------------------------
#
# Done here, after every control exists, so the numbers are measured rather than
# guessed. Two things this fixes, both of which happened:
#
#   * the game tab grew when the IPA picker was added, leaving 金币与脑子 flush
#     against the tab's bottom edge
#   * the window had a large blank area below the tabs when a tab was shortened
#
# The tab's usable height is its total height minus the row of tab headers, which
# is what the "+tabHeaderAllowance" accounts for. The window follows the selected
# page so compact pages do not inherit a blank area from the save list.

$tabHeaderAllowance = 26
$bottomMargin = 18

$gameNeeded = [Math]::Max(
    ($grpCurrency.Top + $grpCurrency.Height),
    ($btnStartSkip.Top + $btnStartSkip.Height))
$settingsNeeded = $grpSettings.Top + $grpSettings.Height
$saveNeeded = $lblSaveHint.Top + $lblSaveHint.Height

$script:GameContentHeight = $gameNeeded + $bottomMargin
$script:SettingsContentHeight = $settingsNeeded + $bottomMargin
$script:SaveContentHeight = $saveNeeded + $bottomMargin
$contentHeight = [Math]::Max(
    [Math]::Max($script:GameContentHeight, $script:SettingsContentHeight),
    $script:SaveContentHeight)

# Give any leftover height to the save list, so the shorter tab fills the space
# instead of showing a gap. The list is the only element there that benefits from
# being taller.
$slack = $contentHeight - $script:SaveContentHeight
if ($slack -gt 0) {
    $listSaves.Height = $listSaves.Height + $slack
    $btnSelectAll.Top = $btnSelectAll.Top + $slack
    $btnSelectNone.Top = $btnSelectNone.Top + $slack
    $btnSelectInvert.Top = $btnSelectInvert.Top + $slack
    $lblSaveHint.Top = $lblSaveHint.Top + $slack
    $script:SaveContentHeight += $slack
}

function Update-WindowForSelectedTab {
    if ($tabs.SelectedIndex -eq 2) { $pageHeight = $script:SaveContentHeight }
    elseif ($tabs.SelectedIndex -eq 1) { $pageHeight = $script:SettingsContentHeight }
    else { $pageHeight = $script:GameContentHeight }
    $tabs.Height = $pageHeight + $tabHeaderAllowance
    $status.Top = $tabs.Top + $tabs.Height + 6
    $form.ClientSize = [System.Drawing.Size]::new(
        $form.ClientSize.Width,
        [int]($status.Top + $status.Height + 10))
}

$tabs.Add_SelectedIndexChanged({ Update-WindowForSelectedTab })
Update-WindowForSelectedTab

[void]$form.ShowDialog()
$form.Dispose()
