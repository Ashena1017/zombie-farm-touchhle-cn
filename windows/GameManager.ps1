# Zombie Farm 游戏管理 — shared storage, settings and launch entry point.
#
# Scope: Zombie Farm / ZFR only, which is the single app this project runs.
# Settings live in touchHLE_options.txt on the app's own line -- touchHLE's native
# per-app mechanism -- so they also apply when touchHLE is started some other way,
# and there is one place to look when something seems wrong.
#
# The Tauri host in windows/launcher uses -CoreOnly through ManagerWorker.ps1.
# Direct invocation still opens the WinForms compatibility UI.
#
#   .\GameManager.ps1                 show the window
#   .\GameManager.ps1 -SelfTest       verify settings + save management, no UI
#   .\GameManager.ps1 -Set k=v,...    write settings headlessly
#   .\GameManager.ps1 -ShowSettings   print the stored settings
#
# This file MUST be saved as UTF-8 *with a BOM*: Windows PowerShell 5.1 decodes a
# BOM-less script using the console ANSI code page, which turns Chinese text into
# byte sequences that can contain a quote character and produce bogus parse
# errors. Run scripts\_ensure_bom.ps1 after editing.

param(
    [switch]$SelfTest,
    [string[]]$Set,
    [switch]$ShowSettings,
    [switch]$CoreOnly
)

$ErrorActionPreference = 'Stop'

$script:ManagerPath = $PSCommandPath
$repositoryPaths = Join-Path $PSScriptRoot 'RepositoryPaths.ps1'
if (Test-Path -LiteralPath $repositoryPaths -PathType Leaf) {
    $paths = & $repositoryPaths
    $script:RuntimeRoot = $paths.Runtime
    $script:HleDir = $paths.Emulator
    $script:IpaDir = $paths.Ipa
    # The emulator inherits this process's search path for the VC++ runtime DLLs.
    $env:PATH = "$PSScriptRoot;$env:PATH"
} else {
    $script:RuntimeRoot = $PSScriptRoot
    $script:IpaDir = Join-Path $PSScriptRoot 'zombie_farm_ipa'
    $script:HleDir = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'touchHLE\touchHLE.exe')) {
        Join-Path $PSScriptRoot 'touchHLE'
    } else {
        $PSScriptRoot
    }
}

# touchHLE resolves resources against its current directory. Start-GameProcess
# launches it with HleDir as its working directory.
$script:OptionsFile = Join-Path $script:HleDir 'touchHLE_options.txt'
$script:BundledIpaName = '内置中文版·v32fix·开源免费.ipa'
$script:SupersededIpaNames = @(
    'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa',
    'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa',
    'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v30fix-notice.ipa',
    '内置中文版·v31fix·开源免费.ipa'
)
# Records which IPA the user picked, so the choice survives a restart. Kept at the
# top level, since it describes the manager's state rather than touchHLE's.
$script:SelectionFile = Join-Path $script:RuntimeRoot 'launcher_selected_ipa.txt'
# Remembers the last "skip ahead" duration (hours/minutes) typed into the
# 启动并跳过时间 dialog, so the next launch pre-fills it. Same reasoning as
# SelectionFile: manager state, top level, tiny plain-text file.
$script:SkipMemoryFile = Join-Path $script:RuntimeRoot 'launcher_skip_memory.txt'

# Free / open-source statement.
#
# The project is given away; copies of it do turn up for sale on marketplaces.
# A buyer can only be protected by knowing, from inside the software itself,
# that this is a free download and where the original lives. So the statement
# is shown on EVERY launch -- a seller who runs the manager once before handing
# the folder over must not be able to make it disappear for the buyer -- and it
# stays visible afterwards as a footer link.
#
# The marker file is no longer a gate. It only records that this install has
# been started once, so the first launch can still say "welcome"; the version
# number in it is informational (support reports, and telling old markers from
# new ones).
# ZFR_MANAGER_NO_NOTICE=1 suppresses the dialog for automation
# (see _analysis\_notice_probe.ps1), which otherwise runs against a fresh copy.
$script:ProjectUrl = 'https://github.com/Ashena1017/zombie-farm-touchhle-cn'
$script:QqGroup = '1185712984'
$script:NoticeVersion = '2'
$script:NoticeFile = Join-Path $script:RuntimeRoot 'launcher_notice_seen.txt'

# Fingerprints of the official build.
#
# These are NOT a security boundary -- this file is plain text and anybody can
# edit it. They exist so that a replaced or patched program is *visible*: the
# manager says so in red on the 文件校验 page and again every time it starts,
# and the player can compare against the numbers published with the release.
#
# The packager checks these pins and the IPA name against release.json. The
# installed manager can still check the official files if that manifest changes.
$script:PinnedExeSha256 = '8C96BDB70D50381851BED84437CC2D568C6F7DA906E7C3D449B91542DB9C1F37'
$script:PinnedIpaSha256 = 'FFBD9D7C7E73A0C5AAB0CA3CD252D28E55272AC5F665AB3B4ECB6E2006C3FFEA'

# Filled in by Invoke-IntegrityCheck; empty until the manager has hashed once.
$script:IntegrityRows = @()

# NOTE: this manager is self-contained. It does NOT call
# StartZombieFarmNextHour.ps1 or SetZombieFarmCurrency.ps1 -- the launching and
# currency-writing logic is implemented in this file. Those two scripts still
# exist for command-line and analysis use, but nothing here depends on them.

# The app identifier and save folder depend on WHICH IPA is selected: the
# zombie_farm_ipa folder holds three different bundle ids, and both
# touchHLE_options.txt and the sandbox directory are keyed on that id. So they are
# resolved at startup by Read-IpaInfo / Initialize-IpaList rather than hardcoded.
$script:CurrentIpa = $null                          # set once the IPA is read
$script:AppId = $null
$script:SaveDir = ''
$script:LiveSave = ''

# Everything matching "<BackupPrefix>*" is treated as a backup, except the
# per-backup .zf-offset companion file. The reference save that RestoreTestSave.ps1
# uses (saveGame.bin2.bak) remains an ordinary, legacy backup.
$script:BackupPrefix = 'saveGame.bin2.bak'
$script:BackupOffsetSuffix = '.zf-offset'

# Runtime state of a launched game, so "is it running?" has an exact answer.
#
# A name-wide Get-Process scan answers a different question ("is any process
# called touchHLE alive?"), and it lies in the cases players actually hit: a
# crash can leave the emulator resident with no window, and a leftover record
# must never wedge the save operations. So the manager records what it started
# (pid, start time, exe path) and re-verifies all three on every check.
$script:RunStateFile = Join-Path $script:HleDir 'zfr_running.json'
# Append-only breadcrumb trail: launches, exits, guards, watchdog decisions.
# When a player reports "it says the game is running but nothing is", this file
# says what the manager actually saw.
$script:ManagerLog = Join-Path $script:HleDir 'zfr_manager.log'
$script:ManagerLogReady = $false

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
            # touchHLE selects the first top-level .app component in ZIP order.
            $entry = $null
            foreach ($item in $zip.Entries) {
                if ($item.FullName -cmatch '^(Payload/[^/]+\.app)/') {
                    $entry = $zip.GetEntry($Matches[1] + '/Info.plist')
                    break
                }
            }
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
                $xml = New-Object System.Xml.XmlDocument
                $xml.XmlResolver = $null
                $ms.Position = 0
                $xml.Load($ms)
                $plist = @{}
                foreach ($key in $xml.SelectNodes('/plist/dict/key')) {
                    $value = $key.SelectSingleNode('following-sibling::*[1]')
                    if ($value.LocalName -in @('string', 'integer')) { $plist[$key.InnerText] = $value.InnerText }
                }
            }
            $result.AppId = $plist['CFBundleIdentifier']
            $result.Executable = $plist['CFBundleExecutable']
            $result.Version = $plist['CFBundleShortVersionString']
            if (-not $result.Version) { $result.Version = $plist['CFBundleVersion'] }
            if (-not $result.AppId) { $result.Error = 'Info.plist 里没有 CFBundleIdentifier' }
        } finally { $zip.Dispose() }
    } catch {
        $result.Error = $_.Exception.Message
    }
    if ($result.AppId -and $result.AppId -notmatch '^[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*$') {
        $result.Error = 'IPA 的应用标识无效。'
        $result.AppId = $null
    }
    return $result
}

# Try each default options line in turn until one applies.
#
# touchHLE matches the identifier exactly, and only one line is honoured per app,
# so the settings must move to whichever id the chosen IPA actually has.
function Set-CurrentIpa {
    param([Parameter(Mandatory = $true)][AllowNull()]$IpaInfo)

    $script:CurrentIpa = $IpaInfo
    $script:AppId = $IpaInfo.AppId
    if (-not $script:AppId) {
        $script:SaveDir = ''
        $script:LiveSave = ''
        return
    }

    $script:SaveDir = Join-Path $script:HleDir ('touchHLE_sandbox\{0}\Documents' -f $script:AppId)
    $script:LiveSave = Join-Path $script:SaveDir 'saveGame.bin2'
}

function Get-PinnedIpaPath {
    $path = Join-Path $script:IpaDir $script:BundledIpaName
    if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
    return $null
}

function Get-IpaList {
    if (-not (Test-Path -LiteralPath $script:IpaDir)) { return @() }
    return @(Get-ChildItem -LiteralPath $script:IpaDir -Filter '*.ipa' -File | Sort-Object Name)
}

# The remembered choice, or the built-in default if that file is missing or names
# an IPA that no longer exists.
function Get-DefaultIpaPath {
    $pinned = Get-PinnedIpaPath
    if (Test-Path -LiteralPath $script:SelectionFile) {
        $saved = ([System.IO.File]::ReadAllText($script:SelectionFile)).Trim()
        if ($saved) {
            # Older managers remembered the release default as a bare filename.
            if ($pinned -and $script:SupersededIpaNames -contains $saved) { return $pinned }
            $candidate = if ([System.IO.Path]::IsPathRooted($saved)) {
                $saved
            } else {
                Join-Path $script:IpaDir $saved
            }
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return [System.IO.Path]::GetFullPath($candidate)
            }
        }
    }
    if ($pinned) { return $pinned }
    $any = Get-IpaList | Select-Object -First 1
    if ($any) { return $any.FullName }
    return $null
}

function Save-IpaSelection {
    param([Parameter(Mandatory = $true)][string]$Path)
    $saved = [System.IO.Path]::GetFullPath($Path)
    if ([System.IO.Path]::GetDirectoryName($saved) -eq $script:IpaDir) {
        $saved = [System.IO.Path]::GetFileName($saved)
        # Distinguish an explicit choice of an old IPA from a pre-upgrade default.
        if ($script:SupersededIpaNames -contains $saved) { $saved = '.\' + $saved }
    }
    [System.IO.File]::WriteAllText(
        $script:SelectionFile, $saved,
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
        CustomMax   = 6.0
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

function ConvertTo-Number {
    param([string]$Value, [switch]$AsScale)

    if (-not $AsScale) {
        $number = 0.0
        if ([double]::TryParse($Value, [Globalization.NumberStyles]::AllowDecimalPoint,
                [Globalization.CultureInfo]::InvariantCulture, [ref]$number) -and
            -not [double]::IsInfinity($number)) {
            return $number
        }
        return $null
    }

    # Accept a decimal or a fraction of integers. touchHLE parses the original
    # components as u64 and requires the reduced fraction to fit in u32.
    if ($Value -notmatch '\A(?<whole>[0-9]+)(?:\.(?<fraction>[0-9]+)|/(?<denominator>[0-9]+))?\z') { return $null }
    $digits = $Matches['whole']
    $fraction = $Matches['fraction']
    $denominatorText = $Matches['denominator']
    if ($fraction) {
        if ($fraction.Length -gt 19) { return $null }
        $digits += $fraction
        $denominatorText = '1' + ('0' * $fraction.Length)
    }

    [uint64]$rawNumerator = 0
    [uint64]$rawDenominator = 1
    if (-not [uint64]::TryParse($digits, [ref]$rawNumerator) -or $rawNumerator -eq 0) { return $null }
    if ($denominatorText -and
        (-not [uint64]::TryParse($denominatorText, [ref]$rawDenominator) -or $rawDenominator -eq 0)) { return $null }

    # Decimal arithmetic keeps the remainder and reduced values exact.
    $gcd = [decimal]$rawNumerator
    $divisor = [decimal]$rawDenominator
    while ($divisor -ne 0) {
        $remainder = $gcd % $divisor
        $gcd = $divisor
        $divisor = $remainder
    }
    $numerator = [decimal]$rawNumerator / $gcd
    $denominator = [decimal]$rawDenominator / $gcd
    if ($numerator -gt [uint32]::MaxValue -or $denominator -gt [uint32]::MaxValue) { return $null }
    return [pscustomobject]@{ Numerator = $numerator; Denominator = $denominator }
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
        if ($c.Value -eq $Value -and $c.Value -ne 'custom') { return $true }
    }
    if (-not $def.AllowCustom) { return $false }

    $kind = if ($def.ContainsKey('CustomKind')) { $def.CustomKind } else { 'int' }
    if ($kind -eq 'scale') {
        $scale = ConvertTo-Number -Value $Value -AsScale
        return $null -ne $scale -and
            $scale.Numerator -ge ([decimal]$def.CustomMin * $scale.Denominator) -and
            $scale.Numerator -le ([decimal]$def.CustomMax * $scale.Denominator)
    }
    if (-not (Test-CustomSpelling -Kind $kind -Value $Value)) { return $false }

    $n = ConvertTo-Number -Value $Value
    if ($null -eq $n) { return $false }
    return $n -ge $def.CustomMin -and $n -le $def.CustomMax
}

# The window size a (family, scale) pair actually produces, in the landscape
# orientation declared by the selected IPA.
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

    $ratio = ConvertTo-Number -Value $Scale -AsScale
    if ($null -eq $ratio) { return '倍率无效' }

    # Landscape swaps the portrait dimensions: width = height * scale.
    $w = [int][Math]::Floor(($portrait[1] * $ratio.Numerator / $ratio.Denominator) + [decimal]0.5)
    $h = [int][Math]::Floor(($portrait[0] * $ratio.Numerator / $ratio.Denominator) + [decimal]0.5)
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

    if (-not $script:AppId) { return $null }
    foreach ($line in $Lines) {
        if ((Get-AppIdFromLine -Line $line) -ceq $script:AppId) {
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

    $tokens = $line -split '[\x09-\x0d\x20]+'
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
        } elseif ($tokens -ccontains $def.Prefix) {
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

    if (-not $script:AppId) { throw '无法识别当前 IPA 的应用标识，设置未写入。' }
    $file = Read-OptionsFile
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($l in $file.Lines) { $lines.Add($l) }

    foreach ($key in $Settings.Keys) {
        if ($Settings[$key] -eq 'custom' -or -not (Test-SettingValue -Key $key -Value $Settings[$key])) {
            throw "设置值无效：$key"
        }
    }

    # A fresh app row needs the manager's defaults. For an existing row, merge
    # only the requested changes and leave other emulator options in place.
    $updatedSettings = $Settings
    $currentLine = Get-OptionsLine -Lines $file.Lines
    if ([string]::IsNullOrEmpty($currentLine)) {
        $updatedSettings = Get-CurrentSettings
        foreach ($key in $Settings.Keys) { $updatedSettings[$key] = $Settings[$key] }
    }
    $valuesByPrefix = @{}
    foreach ($key in $updatedSettings.Keys) {
        $def = $script:SettingDefs[$key]
        $value = [string]$updatedSettings[$key]
        if ($def.Prefix.EndsWith('=')) {
            $valuesByPrefix[$def.Prefix] = $def.Prefix + $value
        } else {
            $valuesByPrefix[$def.Prefix] = if ($value -eq '1') { $def.Prefix } else { '' }
        }
    }

    $tokens = [System.Collections.Generic.List[string]]::new()
    foreach ($token in ($currentLine -split '[\x09-\x0d\x20]+')) {
        if (-not $token) { continue }
        if ($token.StartsWith('--device-size=') -and
            ($updatedSettings.Contains('window_family') -or $updatedSettings.Contains('window_scale'))) {
            # The obsolete size override prevents the device/scale controls from taking effect.
            continue
        }
        $equals = $token.IndexOf('=')
        $prefix = if ($equals -ge 0) { $token.Substring(0, $equals + 1) } else { $token }
        if ($valuesByPrefix.ContainsKey($prefix)) { continue }
        $tokens.Add($token)
    }
    foreach ($definition in $script:SettingDefs.Values) {
        $token = $valuesByPrefix[$definition.Prefix]
        if ($token) { $tokens.Add($token) }
    }
    $newLine = '{0}: {1}' -f $script:AppId, ($tokens -join ' ')

    $replaced = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ((Get-AppIdFromLine -Line $lines[$i]) -ceq $script:AppId) {
            $commentStart = $lines[$i].IndexOf('#')
            $lines[$i] = if ($commentStart -ge 0) { $newLine + ' ' + $lines[$i].Substring($commentStart) } else { $newLine }
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

function Write-ManagerLog {
    param([string]$Message)
    try {
        # Rotate once per manager run: a crash loop must not grow this forever.
        if (-not $script:ManagerLogReady) {
            $script:ManagerLogReady = $true
            try {
                if ((Test-Path -LiteralPath $script:ManagerLog) -and
                    ((Get-Item -LiteralPath $script:ManagerLog).Length -gt 1MB)) {
                    Move-Item -LiteralPath $script:ManagerLog -Destination "$($script:ManagerLog).1" -Force
                }
            } catch { }
        }
        $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
        [System.IO.File]::AppendAllText($script:ManagerLog, $line + "`r`n",
            (New-Object System.Text.UTF8Encoding($false)))
    } catch { <# a breadcrumb is a nicety, not a requirement #> }
}

function Remove-RunState {
    param([string]$Path = $script:RunStateFile)

    try {
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Force
        }
    } catch { }
}

function Get-ProcessStartStamp {
    param([Parameter(Mandatory = $true)]$Process)
    try { return $Process.StartTime.ToUniversalTime().ToString('o') } catch { return $null }
}

function Get-ProcessImagePath {
    param([Parameter(Mandatory = $true)]$Process)
    try { return $Process.Path } catch {
        try { return $Process.MainModule.FileName } catch { return $null }
    }
}

# Is the game running, and if so which process is it?
#
# The old check was a bare  Get-Process -Name touchHLE  scan, which is wrong in
# the three cases that matter in practice:
#
#   * a crash can leave the emulator alive with no window (the guest thread is
#     gone; a stuck host loop or an invisible modal error box keeps the process
#     resident), so the manager claimed "already running" while the player saw
#     nothing at all -- and could not find it in Task Manager either;
#   * a game started from a DIFFERENT copy of the bundle was treated as if it
#     were this one, blocking launches for no reason;
#   * a PID from an earlier run can be reused by an unrelated process.
#
# So the recorded pid + start time + exe path are all re-verified. A record that
# no longer matches is deleted on the spot: that self-healing is what keeps a
# crash from wedging backup/restore/currency for the rest of the session.
function Get-GameProcessState {
    param(
        [string]$RunStateFile = $script:RunStateFile,
        [string]$ExpectedExe = (Join-Path $script:HleDir 'touchHLE.exe')
    )

    $state = [pscustomobject]@{
        Running = $false      # a game process belonging to THIS bundle is alive
        Process = $null       # that process object, when we could get one
        Source  = 'none'      # 'record' = we launched it, 'scan' = started elsewhere
        Stale   = $false      # a leftover record was found and cleared
        Window  = [int64]0    # MainWindowHandle; 0 means "alive but no window"
        Pid     = 0
    }

    if (Test-Path -LiteralPath $RunStateFile) {
        $record = $null
        try {
            $record = Get-Content -LiteralPath $RunStateFile -Raw | ConvertFrom-Json
        } catch { $record = $null }

        $process = $null
        $recordPid = 0
        if ($record -and $record.start -and $record.exe -eq $expectedExe -and
            [int]::TryParse([string]$record.pid, [ref]$recordPid) -and $recordPid -gt 0) {
            $process = Get-Process -Id $recordPid -ErrorAction SilentlyContinue
        }
        if ($process) {
            # Both must hold: the recorded start time (guards PID reuse) and the
            # recorded image path (guards another copy of touchHLE.exe).
            $stampOk = (Get-ProcessStartStamp -Process $process) -eq [string]$record.start
            $pathOk = (Get-ProcessImagePath -Process $process) -eq $expectedExe
            if ($stampOk -and $pathOk) {
                try { $process.Refresh() } catch { }
                $state.Running = $true
                $state.Process = $process
                $state.Source = 'record'
                $state.Pid = $process.Id
                try { $state.Window = $process.MainWindowHandle.ToInt64() } catch { }
                return $state
            }
        }

        Remove-RunState -Path $RunStateFile
        $state.Stale = $true
        Write-ManagerLog ('stale run record cleared (pid={0})' -f $(if ($record) { $record.pid } else { '?' }))
    }

    # No record: the game may still have been started from the .bat launchers.
    # Only a process running THIS installation's executable counts as ours.
    $candidates = @()
    try { $candidates = @(Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue) } catch { }
    foreach ($process in $candidates) {
        $path = Get-ProcessImagePath -Process $process
        if ($path -ne $expectedExe) { continue }
        try { $process.Refresh() } catch { }
        $state.Running = $true
        $state.Process = $process
        $state.Source = 'scan'
        $state.Pid = $process.Id
        try { $state.Window = $process.MainWindowHandle.ToInt64() } catch { }
        return $state
    }

    return $state
}

function Test-GameRunning {
    return [bool](Get-GameProcessState).Running
}

# Paths the launcher needs. Defined up here (rather than next to the launching
# code further down) so the -SelfTest block, which runs before that code is
# parsed into scope, can still verify them.
function Get-FarmOffsetPath([string]$Id, [string]$Emulator = $script:HleDir, [switch]$ReadOnly) {
    if (-not $Id) { return $null }
    if ($Id -notmatch '^[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*$') { throw 'IPA 的应用标识无效。' }
    $folder = Join-Path $Emulator ('touchHLE_sandbox\{0}' -f $Id)
    $ready = Join-Path $Emulator ("zf_farm_backups\$Id\.ready")
    if (!$ReadOnly -and [IO.Directory]::Exists($ready)) {
        Invoke-WithTimeOffsetLock {
            if (![IO.Directory]::Exists($folder) -and [IO.Directory]::Exists($ready)) {
                Assert-FarmPath $ready $Emulator
                Assert-FarmPath $folder $Emulator
                [IO.Directory]::Move($ready, $folder)
            }
        }
    }
    $path = Join-Path $folder 'touchHLE_time_offset_seconds.txt'
    # Older managers kept a single clock without recording its owner. Migrate it
    # once to the bundled farm, even if an extra IPA is selected first.
    if (-not $ReadOnly -and $Id -ceq 'com.playforge.ZombieFarm.ZFR' -and -not [IO.File]::Exists($path)) {
        $legacy = Join-Path $Emulator 'touchHLE_time_offset_seconds.txt'
        if ([IO.File]::Exists($legacy)) {
            [void][IO.Directory]::CreateDirectory($folder)
            try { [IO.File]::Move($legacy, $path) } catch [IO.IOException] {
                if (-not [IO.File]::Exists($path)) { throw }
            }
        }
    }
    return $path
}

function Get-LaunchPaths {
    $ipa = $null
    if ($null -ne $script:CurrentIpa) { $ipa = $script:CurrentIpa.Path }
    if (-not $ipa) { $ipa = Get-DefaultIpaPath }

    return [pscustomobject]@{
        # touchHLE's own state lives beside touchHLE.exe.
        OffsetFile  = Get-FarmOffsetPath $script:AppId -ReadOnly:$SelfTest
        Fingerprint = Join-Path $script:HleDir 'zfr_last_launch.txt'
        TouchHLE    = Join-Path $script:HleDir 'touchHLE.exe'
        Ipa         = $ipa
        # Resources are found relative to the CURRENT DIRECTORY, so this is what
        # the child process must be started in.
        WorkingDir  = $script:HleDir
    }
}

# Windows exit codes are signed 32-bit; report the hex an engineer expects.
#
# These two helpers live up here (rather than beside the launching code) for the
# same reason Get-LaunchPaths does: the -SelfTest block runs before that part of
# the file is in scope, and it checks both of them.
function Get-ExitCodeHint {
    param([int]$Code)
    # -band with 0xFFFFFFFF is unreliable here (PowerShell keeps the sign), so
    # map the signed 32-bit value to its unsigned equivalent explicitly.
    $unsigned = [int64]$Code
    if ($unsigned -lt 0) { $unsigned += 4294967296 }
    $hex = '0x{0:X8}' -f $unsigned
    if ($Code -eq -1073741819) { return "$hex 访问冲突" }
    if ($Code -eq -1073741795) { return "$hex 非法指令" }
    if ($Code -eq -1073741571) { return "$hex 栈溢出" }
    if ($Code -eq -1073740791) { return "$hex 快速失败（fail-fast）" }
    if ($Code -eq -1073741515) { return "$hex 缺少 DLL" }
    if ($Code -eq -1073741816) { return "$hex 无法启动子进程" }
    if ($Code -eq -1) { return '0xFFFFFFFF 游戏主动退出（异常路径）' }
    if ($Code -eq 101) { return 'Rust panic' }
    return $hex
}

# The first panic-ish line of stderr, short enough for the status bar.
function Get-PanicSummary {
    param([string]$Text)
    if (-not $Text) { return '' }
    foreach ($line in ($Text -split "`r?`n")) {
        $t = $line.Trim()
        if (-not $t) { continue }
        if ($t -match "panicked at|^Error:|^thread '.*' panicked") {
            if ($t.Length -gt 160) { return $t.Substring(0, 160) + '…' }
            return $t
        }
    }
    return ''
}

# ---------------------------------------------------------------------------
# Save management (backup / restore / delete)
# ---------------------------------------------------------------------------
#
# Everything matching saveGame.bin2.bak* is listed, except its hidden .zf-offset
# companion file. Restoring archives both the current save and its time offset.

$script:FarmBackupPattern = '^(?<stamp>\d{8}-\d{6}-\d{3})_(?<kind>新建农场前|还原农场前)_[a-f0-9]{32}\.farm$'

function Get-FarmBackupDirectory {
    Join-Path $script:HleDir ("zf_farm_backups\" + $script:AppId)
}

# Reject junctions at every level before copying or moving player data.
function Assert-FarmPath([string]$Path, [string]$Root = $script:HleDir) {
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $p = [IO.Path]::GetFullPath($Path)
    if (!$p.StartsWith($rootPath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '农场路径超出游戏目录。' }
    while ($p -ne $rootPath) {
        $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "农场目录含有链接：$p" }
        $p = [IO.Path]::GetDirectoryName($p)
    }
}

function Get-FarmContents([string]$Root, [string]$Relative = '') {
    $dir = if ($Relative) { Join-Path $Root $Relative } else { $Root }
    foreach ($item in (Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "农场目录含有链接：$($item.FullName)" }
        $name = if ($Relative) { "$Relative\$($item.Name)" } else { $item.Name }
        if ($item.PSIsContainer) { Get-FarmContents $Root $name }
        else {
            $manager = $name -like 'Documents\recovery\*' -or
                ($Relative -eq 'Documents' -and $item.Name -like "$($script:BackupPrefix)*")
            [pscustomobject]@{ File = $item; Relative = $name; Manager = $manager; Clock = $name -eq 'touchHLE_time_offset_seconds.txt' }
        }
    }
}

function Test-FarmData {
    if (!$script:SaveDir) { return $false }
    $farm = Split-Path -Parent $script:SaveDir
    if (![IO.Directory]::Exists($farm)) { return $false }
    Assert-FarmPath $farm
    if ([IO.File]::Exists($script:LiveSave)) { return $true }
    return [bool](Get-FarmContents $farm | Where-Object { !$_.Manager -and !$_.Clock } | Select-Object -First 1)
}

function Copy-FarmMember($Member, [string]$Stage) {
    $dest = Join-Path $Stage $Member.Relative
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest))
    [IO.File]::Copy($Member.File.FullName, $dest)
    if ((Get-Sha256Hex $dest) -ne (Get-Sha256Hex $Member.File.FullName)) { throw '农场文件复制校验失败。' }
}

function Remove-FarmDirectory([string]$Path) {
    Assert-FarmPath $Path
    if ((Split-Path -Parent $Path) -ne (Get-FarmBackupDirectory)) { throw '无法确认农场备份的位置。' }
    if ([IO.Directory]::Exists($Path)) {
        # Check children before recursion, including player-added junctions.
        Get-FarmContents $Path | Out-Null
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
    }
}

# Move the original sandbox intact. The new sandbox receives existing manager
# backups and either the current clock or the chosen farm's files and clock.
function Switch-FarmSave([string]$AppId, [string]$RestoreFrom) {
    if (!$AppId -or $AppId -cne $script:AppId -or !$script:SaveDir) { throw '所选农场已改变，请重新确认。' }
    Invoke-WithTimeOffsetLock {
        if (Test-GameRunning) { throw '请先退出游戏，再操作当前农场。' }
        $farm = Split-Path -Parent $script:SaveDir
        $store = Get-FarmBackupDirectory
        Assert-FarmPath $farm
        Assert-FarmPath $store
        [void](Get-FarmOffsetPath $AppId)
        $current = @(if ([IO.Directory]::Exists($farm)) { Get-FarmContents $farm })
        $hasData = [bool]($current | Where-Object { !$_.Manager -and !$_.Clock } | Select-Object -First 1)
        if (!$RestoreFrom -and !$hasData) { throw '当前没有可清空的农场。' }
        if ($RestoreFrom) {
            if ((Split-Path -Parent $RestoreFrom) -ne $store -or (Split-Path -Leaf $RestoreFrom) -notmatch $script:FarmBackupPattern) {
                throw '请选择当前游戏的完整农场备份。'
            }
            Assert-FarmPath $RestoreFrom
        }
        $token = [guid]::NewGuid().ToString('N')
        $staging = Join-Path $store ('.stage-' + $token)
        $ready = Join-Path $store '.ready'
        $archive = Join-Path $store ('.empty-' + $token)
        $recovery = $false
        if ($hasData) {
            $kind = if ($RestoreFrom) { '还原农场前' } else { '新建农场前' }
            $archive = Join-Path $store ("{0}_{1}_{2}.farm" -f (Get-Date -Format yyyyMMdd-HHmmss-fff), $kind, $token)
            $recovery = ![IO.File]::Exists($script:LiveSave)
            if (!$recovery) {
                try { Assert-SaveBackupContent $script:LiveSave }
                catch [IO.IOException] { throw }
                catch [UnauthorizedAccessException] { throw }
                catch { $recovery = $true }
            }
            if ($recovery) { $archive += '.recovery' }
        }
        # A ready directory with an existing live farm is an interrupted,
        # uncommitted operation. Its files were copied from retained originals.
        Remove-FarmDirectory $ready
        [void][IO.Directory]::CreateDirectory((Join-Path $staging 'Documents'))
        $moved = $false
        try {
            foreach ($member in $current) {
                if ($member.Manager -or (!$RestoreFrom -and $member.Clock)) { Copy-FarmMember $member $staging }
            }
            if ($RestoreFrom) {
                foreach ($member in (Get-FarmContents $RestoreFrom)) {
                    if (!$member.Manager) { Copy-FarmMember $member $staging }
                }
                Assert-SaveBackupContent (Join-Path $staging 'Documents\saveGame.bin2')
            }
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($farm))
            [IO.Directory]::Move($staging, $ready)
            if ([IO.Directory]::Exists($farm)) { [IO.Directory]::Move($farm, $archive); $moved = $true }
            try { [IO.Directory]::Move($ready, $farm) } catch {
                if ($moved) { [IO.Directory]::Move($archive, $farm) }
                throw
            }
            if ($moved -and !$hasData) { Remove-FarmDirectory $archive }
            if ($recovery) { return $archive }
        } finally { Remove-FarmDirectory $staging }
    }
}

function Get-BackupFiles {
    param([string]$Directory = $script:SaveDir)

    if (-not $Directory) { return @() }
    $formats = [string[]]@('yyyyMMdd-HHmmss-fff', 'yyyyMMdd-HHmmss')
    $pattern = '^saveGame\.bin2\.bak-(?<stamp>[0-9]{8}-[0-9]{6}(?:-[0-9]{3})?)(?:-(?<label>(?![0-9]+$).+?))?(?:-(?<sequence>[0-9]+))?$'
    $files = @(if ($Directory -eq $script:SaveDir) {
        $store = Get-FarmBackupDirectory
        if ([IO.Directory]::Exists($store)) {
            Assert-FarmPath $store
            foreach ($dir in (Get-ChildItem -LiteralPath $store -Directory -Filter '*.farm')) {
                if ($dir.Name -notmatch $script:FarmBackupPattern -or ($dir.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
                $time = [datetime]::MinValue
                if (![datetime]::TryParseExact($Matches.stamp, 'yyyyMMdd-HHmmss-fff', [Globalization.CultureInfo]::InvariantCulture,
                        [Globalization.DateTimeStyles]::None, [ref]$time)) { continue }
                [pscustomobject]@{ Name = $dir.Name; FullName = $dir.FullName; Length = $null; BackupTime = $time
                    BackupKind = $Matches.kind; BackupSequence = 0; CreationTime = $dir.CreationTime }
            }
        }
    })
    $legacy = if ([IO.Directory]::Exists($Directory)) { Get-ChildItem -LiteralPath $Directory -File -Filter "$($script:BackupPrefix)*" }
    $files += @(foreach ($file in $legacy) {
        if ($file.Name.EndsWith($script:BackupOffsetSuffix, [StringComparison]::OrdinalIgnoreCase)) { continue }
        # Copying a save keeps its original modification time. The filename records
        # when the backup was made, even after it moves to another installation.
        $time = $file.CreationTime
        $kind = '备份'
        [long]$sequence = 0
        [datetime]$parsed = [datetime]::MinValue
        if ($file.Name -match $pattern -and [datetime]::TryParseExact($Matches.stamp, $formats,
                [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsed)) {
            $time = $parsed
            if ($Matches.label) { $kind = $Matches.label }
            [void][long]::TryParse($Matches.sequence, [ref]$sequence)
        }
        Add-Member -InputObject $file -NotePropertyMembers @{ BackupTime = $time; BackupKind = $kind; BackupSequence = $sequence } -PassThru
    })
    return @($files | Sort-Object -Property BackupTime, BackupSequence, CreationTime, Name -Descending)
}

function Get-BackupOffsetPath {
    param([Parameter(Mandatory = $true)][string]$BackupPath)
    return "$BackupPath$($script:BackupOffsetSuffix)"
}

function Read-TimeOffset {
    param([string]$Path = (Get-LaunchPaths).OffsetFile, [switch]$AllowInvalid)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return [int64]0 }
    $text = [System.IO.File]::ReadAllText($Path).Trim()
    if (-not $text) { return [int64]0 }
    [int64]$value = 0
    if (-not [int64]::TryParse($text, [ref]$value) -or $value -lt 0) {
        if ($AllowInvalid) { return $null }
        throw "累计时间偏移文件内容无效：$Path"
    }
    return $value
}

function Format-SimulatedTime {
    param([int64]$Offset, [DateTimeOffset]$Base)

    $simulated = $Base.AddSeconds($Offset)
    $epoch = $simulated.ToUnixTimeSeconds()
    if ($epoch -lt 0 -or $epoch -gt [int]::MaxValue) {
        throw '模拟时间超出游戏支持范围。'
    }
    return $simulated.ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
}

function Get-SimulatedTimeBase {
    [int64]$fixedTime = 0
    if ([int64]::TryParse($env:TOUCHHLE_FAKE_UNIX_TIME, [ref]$fixedTime)) {
        return [DateTimeOffset]::FromUnixTimeSeconds($fixedTime)
    }
    return [DateTimeOffset]::UtcNow
}

function Invoke-WithTimeOffsetLock([scriptblock]$Action) {
    # CLI launches, GUI launches and explicit clock changes can come from different processes.
    $mutex = [Threading.Mutex]::new($false, 'Local\ZombieFarm.TimeOffset')
    try {
        try { $acquired = $mutex.WaitOne(15000) }
        catch [Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) { throw '另一个操作正在更新模拟时间，请稍后再试。' }
        try { & $Action } finally { $mutex.ReleaseMutex() }
    } finally { $mutex.Dispose() }
}

# Caller holds the clock lock. File.Replace can keep the exact original for a failed launch.
function Set-TimeOffsetFile([string]$Path, [int64]$Value, [string]$PreviousPath) {
    if ($Value -lt 0) { throw '累计时间偏移不能为负数。' }
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temp = Join-Path $directory ('.time-offset-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
    try {
        [System.IO.File]::WriteAllText($temp, [string]$Value, [System.Text.Encoding]::ASCII)
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            if ($PreviousPath) { [IO.File]::Replace($temp, $Path, $PreviousPath) }
            else { [IO.File]::Replace($temp, $Path, [NullString]::Value) }
        } else {
            [System.IO.File]::Move($temp, $Path)
        }
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-TimeOffset {
    param(
        [Parameter(Mandatory = $true)][int64]$Value,
        [string]$Path = (Get-LaunchPaths).OffsetFile
    )
    Invoke-WithTimeOffsetLock { Set-TimeOffsetFile -Path $Path -Value $Value }
}

function Start-GameWithTimeOffset {
    param([Diagnostics.ProcessStartInfo]$StartInfo, $Paths, [int64]$SkipSeconds, [switch]$Reset, [string]$IpaHash)

    if (-not $IpaHash) { $IpaHash = Get-Sha256Hex $Paths.Ipa }
    $offsetFile = $Paths.OffsetFile
    Invoke-WithTimeOffsetLock {
        $offset = if ($Reset) { [int64]0 } else { Read-TimeOffset -Path $OffsetFile }
        if ($SkipSeconds -lt 0 -or $SkipSeconds -gt ([int64]::MaxValue - $offset)) {
            throw '累计时间偏移超出范围。'
        }
        $offset += $SkipSeconds
        [void](Format-SimulatedTime -Offset $offset -Base (Get-SimulatedTimeBase))
        $StartInfo.EnvironmentVariables['TOUCHHLE_TIME_OFFSET_SECONDS'] = [string]$offset
        $previous = $null
        if ($SkipSeconds -gt 0 -or $Reset) {
            $previous = "$OffsetFile.bak-$([Guid]::NewGuid().ToString('N'))"
            Set-TimeOffsetFile -Path $OffsetFile -Value $offset -PreviousPath $previous
        }
        try {
            $child = [Diagnostics.Process]::Start($StartInfo)
        } catch {
            if ($previous) {
                if ([IO.File]::Exists($previous)) { [IO.File]::Replace($previous, $OffsetFile, [NullString]::Value) }
                else { [IO.File]::Delete($OffsetFile) }
            }
            throw
        }
        if ([IO.File]::Exists($previous)) { Remove-Item -LiteralPath $previous -Force -ErrorAction SilentlyContinue }
        # Record successful launches in their actual order. A diagnostic cannot undo a running child.
        try {
            @("ipa = $(Split-Path -Leaf $Paths.Ipa)", "sha256 = $IpaHash", "launched = $(Get-Date -Format o)") |
                Set-Content -LiteralPath $Paths.Fingerprint -Encoding utf8
        } catch { Write-ManagerLog "Could not write launch fingerprint: $_" }
        return $child
    }
}

function Write-BackupOffset {
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [Parameter(Mandatory = $true)][int64]$Value,
        [string]$ContentPath = $BackupPath
    )

    $metadataPath = Get-BackupOffsetPath -BackupPath $BackupPath
    $temp = Join-Path (Split-Path -Parent $BackupPath) ('.zf-offset-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
    try {
        $metadata = @{ format = 1; offset = $Value; size = (Get-Item -LiteralPath $ContentPath).Length; sha256 = Get-Sha256Hex $ContentPath }
        [System.IO.File]::WriteAllText($temp, ($metadata | ConvertTo-Json -Compress), [Text.Encoding]::ASCII)
        [System.IO.File]::Move($temp, $metadataPath)
        [System.IO.File]::SetAttributes($metadataPath, [System.IO.FileAttributes]::Hidden)
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-SaveBackup {
    param(
        [string]$Directory = $script:SaveDir,
        [string]$Label = 'manual',
        [string]$SourcePath,
        [string]$OffsetFile = (Get-LaunchPaths).OffsetFile
    )

    if (-not $Directory) { throw '当前 IPA 没有可用的存档目录。' }
    if (-not $SourcePath) { $SourcePath = Join-Path $Directory 'saveGame.bin2' }
    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw '找不到当前存档，无法备份。'
    }

    $offset = Read-TimeOffset -Path $OffsetFile
    $stamp = [datetime]::Now.ToString('yyyyMMdd-HHmmss-fff', [Globalization.CultureInfo]::InvariantCulture)
    $target = Join-Path $Directory ("{0}-{1}-{2}" -f $script:BackupPrefix, $stamp, $Label)
    $suffix = 1
    while ((Test-Path -LiteralPath $target) -or (Test-Path -LiteralPath (Get-BackupOffsetPath -BackupPath $target))) {
        $target = Join-Path $Directory ("{0}-{1}-{2}-{3}" -f $script:BackupPrefix, $stamp, $Label, $suffix)
        $suffix++
    }

    $pending = Join-Path $Directory ('.backup-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
    $sidecarCreated = $false
    try {
        [IO.File]::Copy($SourcePath, $pending)
        if ($Label -ne 'pre-restore') { Assert-SaveBackupContent $pending }
        Write-BackupOffset -BackupPath $target -Value $offset -ContentPath $pending
        $sidecarCreated = $true
        [IO.File]::Move($pending, $target)
    } catch {
        if ($sidecarCreated) { Remove-Item -LiteralPath (Get-BackupOffsetPath $target) -Force }
        throw
    } finally {
        [IO.File]::Delete($pending)
    }
    return $target
}

function Restore-SaveBackup {
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [string]$Directory = $script:SaveDir,
        [string]$OffsetFile = (Get-LaunchPaths).OffsetFile
    )

    if ([IO.Directory]::Exists($BackupPath)) {
        return Switch-FarmSave -AppId $script:AppId -RestoreFrom $BackupPath
    }
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) { throw "备份不存在：$BackupPath" }

    $metadataPath = Get-BackupOffsetPath -BackupPath $BackupPath
    $restoreOffset = $null
    $metadata = $null
    if ([IO.File]::Exists($metadataPath)) {
        $raw = [IO.File]::ReadAllText($metadataPath).Trim()
        if ($raw.StartsWith('{')) {
            $metadata = $raw | ConvertFrom-Json
            if ($metadata.format -ne 1 -or [string]$metadata.offset -notmatch '^\d+$' -or
                [string]$metadata.size -notmatch '^[1-9]\d*$' -or [string]$metadata.sha256 -notmatch '^[a-f0-9]{64}$') {
                throw '备份校验记录无效。'
            }
            $restoreOffset = [int64]$metadata.offset
        } elseif ($raw -match '^\d+$') {
            $restoreOffset = [int64]$raw
        } else { throw '备份的累计时间无效。' }
    }

    $live = Join-Path $Directory 'saveGame.bin2'
    # Archive the current save first so a restore is itself undoable.
    $stagedSave = Join-Path $Directory ('.restore-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
    try {
        [void][IO.Directory]::CreateDirectory($Directory)
        [System.IO.File]::Copy($BackupPath, $stagedSave)
        $size = (Get-Item -LiteralPath $stagedSave).Length
        Assert-SaveBackupContent $stagedSave
        if ($metadata -and ($size -ne $metadata.size -or (Get-Sha256Hex $stagedSave) -ne $metadata.sha256)) {
            throw '备份大小或 SHA-256 与创建时不同，无法还原。'
        }
        Invoke-WithTimeOffsetLock {
            $preRestore = $null
            $hasLive = [IO.File]::Exists($live)
            if ($null -eq (Read-TimeOffset -Path $OffsetFile -AllowInvalid)) {
                # A damaged clock cannot be encoded in an ordinary backup. Keep
                # its original bytes alongside the displaced farm for recovery.
                $recovery = Join-Path $Directory ('recovery\{0}-{1}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), [guid]::NewGuid().ToString('N'))
                [void][IO.Directory]::CreateDirectory($recovery)
                [IO.File]::Copy($OffsetFile, (Join-Path $recovery 'touchHLE_time_offset_seconds.txt'))
                if ($hasLive) {
                    $preRestore = Join-Path $recovery 'saveGame.bin2'
                    [IO.File]::Copy($live, $preRestore)
                }
            } elseif ($hasLive) {
                $preRestore = New-SaveBackup -Directory $Directory -Label 'pre-restore' -SourcePath $live -OffsetFile $OffsetFile
            }

            if ($hasLive) {
                [IO.File]::Replace($stagedSave, $live, [NullString]::Value)
            } else {
                [IO.File]::Move($stagedSave, $live)
            }
            try {
                if ($null -ne $restoreOffset) { Set-TimeOffsetFile -Path $OffsetFile -Value $restoreOffset }
            } catch {
                if ($preRestore) {
                    [IO.File]::Copy($preRestore, $stagedSave)
                    [IO.File]::Replace($stagedSave, $live, [NullString]::Value)
                } else {
                    [IO.File]::Delete($live)
                }
                throw
            }
        }
    } finally {
        if (Test-Path -LiteralPath $stagedSave -PathType Leaf) {
            Remove-Item -LiteralPath $stagedSave -Force -ErrorAction SilentlyContinue
        }
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
    if ([IO.Directory]::Exists($BackupPath) -and $leaf -match $script:FarmBackupPattern) {
        Invoke-WithTimeOffsetLock { Remove-FarmDirectory $BackupPath }
        return $leaf
    }
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

function Get-ZfrPlayerOffset {
    param([Parameter(Mandatory = $true)][byte[]]$Data)

    if ($Data.Length -lt 4 -or [BitConverter]::ToInt32($Data, 0) -ne 14) {
        throw '这不是受支持的 Zombie Farm / ZFR 版本 14 存档。'
    }

    $marker = [byte[]]@(0x01,0x09,0x00,0x00,0x00,0x55,0x4E,0x44,0x45,0x46,0x49,0x4E,0x45,0x44)
    $markerOffset = -1
    $i = -1
    while (($i = [Array]::IndexOf($Data, $marker[0], $i + 1)) -ge 0 -and $i -le $Data.Length - $marker.Length) {
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

    if ($Data.Length -lt ($markerOffset + 0x5E)) {
        throw '玩家数据块不完整。请先还原一个未经修改的备份。'
    }

    $layoutVersion = [BitConverter]::ToInt32($Data, $markerOffset + 0x42)
    $reservedValue = [BitConverter]::ToInt32($Data, $markerOffset + 0x52)
    if ($layoutVersion -ne 4 -or $reservedValue -ne 0) {
        throw '玩家数据块校验失败，可能已经损坏。'
    }
    return $markerOffset
}

function Assert-SaveBackupContent([string]$Path) {
    if ((Get-Item -LiteralPath $Path).Length -eq 0) { throw '存档为空。' }
    if ($script:AppId -cne 'com.playforge.ZombieFarm.ZFR') { return }

    $data = [IO.File]::ReadAllBytes($Path)
    if ($data.Length -le 4) { throw '存档缺少版本号或游戏数据。' }
    $version = [BitConverter]::ToInt32($data, 0)
    # Only v14's layout is known. Preserve opaque backups for other versions.
    if ($version -le 0) { throw '存档版本号无效。' }
    if ($version -ne 14) { return }
    $marker = Get-ZfrPlayerOffset $data
    Assert-ZfrQuests $data $marker
}

function Assert-ZfrQuests([byte[]]$Data, [int]$Marker) {
    $completed = [BitConverter]::ToUInt32($data, $marker + 0x56)
    [long]$pos = $marker + 0x5a + 4L * $completed
    if ($pos + 4 -gt $data.Length) { throw '存档中的已完成任务列表不完整。' }
    $active = [BitConverter]::ToUInt32($data, $pos)
    $pos += 4
    if ($pos + 8L * $active -gt $data.Length) { throw '存档中的活动任务列表不完整。' }
    for ($i = 0; $i -lt $active; $i++) {
        if ($pos + 8 -gt $data.Length) { throw '存档中的活动任务记录不完整。' }
        $progress = [BitConverter]::ToUInt32($data, $pos + 4)
        $pos += 8L + 4L * $progress
        if ($pos -gt $data.Length) { throw '存档中的任务进度记录不完整。' }
    }
}

function Get-CurrencyLayout {
    param([Parameter(Mandatory = $true)][byte[]]$Data)

    $markerOffset = Get-ZfrPlayerOffset $Data
    if ($script:AppId -ceq 'com.playforge.ZombieFarm.ZFR') { Assert-ZfrQuests $Data $markerOffset }
    $goldOffset = $markerOffset + 0x46
    $brainOffset = $markerOffset + 0x4A
    $firstIndex = [BitConverter]::ToInt32($Data, $markerOffset + 0x56)
    $secondIndex = [BitConverter]::ToInt32($Data, $markerOffset + 0x5A)
    if (
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

    if (-not $SavePath -or -not (Test-Path -LiteralPath $SavePath)) { return $null }
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
    if (-not $SavePath -or -not (Test-Path -LiteralPath $SavePath -PathType Leaf)) {
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

        Write-BackupOffset -BackupPath $backupPath -Value $offset -ContentPath $SavePath
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
# modes need it too before reading settings or locating a save.
function Initialize-CurrentIpa {
    $path = Get-DefaultIpaPath
    if (-not $path) {
        Set-CurrentIpa $null
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
    # Target the same app-specific line that the interactive manager reads.
    [void](Initialize-CurrentIpa)

    $settings = @{}

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
    }

    if ($settings.Count) {
        Save-Settings -Settings $settings
        # Name the app id too: with several bundle ids in the folder, "which line
        # did that write?" is the first thing to check when a change seems to have
        # had no effect.
        Write-Host ("Saved for {0}: {1}" -f $script:AppId, (Get-OptionsLine -Lines (Read-OptionsFile).Lines))
    }
    exit 0
}

# Use .NET so hashing works even when another PowerShell overrides PSModulePath.
# This helper is also used before the WinForms UI is initialized.
function Get-Sha256Hex {
    param([string]$Path)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        $bytes = $sha.ComputeHash($stream)
        return ([System.BitConverter]::ToString($bytes)).Replace('-', '')
    } finally {
        if ($stream) { $stream.Dispose() }
        $sha.Dispose()
    }
}

function Write-RunState {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][string]$Ipa
    )
    try {
        # The exe path is recorded too: a bare PID would be enough to find a
        # process, but not enough to prove it is OURS (PIDs get reused).
        $exe = Get-ProcessImagePath -Process $Process
        if (-not $exe) { $exe = Join-Path $script:HleDir 'touchHLE.exe' }
        $record = [ordered]@{
            pid      = $Process.Id
            start    = Get-ProcessStartStamp -Process $Process
            exe      = $exe
            ipa      = $Ipa
            launched = (Get-Date).ToString('o')
        }
        [System.IO.File]::WriteAllText($script:RunStateFile, ($record | ConvertTo-Json -Compress),
            (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-ManagerLog ('could not write run record: {0}' -f $_.Exception.Message)
    }
}

function Test-BundledIpa {
    param([string]$Path)

    $pinned = Get-PinnedIpaPath
    if (-not $Path -or -not $pinned) { return $false }
    try {
        return ([System.IO.Path]::GetFullPath($Path) -eq [System.IO.Path]::GetFullPath($pinned))
    } catch {
        return $false
    }
}

# State is one of:
#   ok      the file exists and matches the pinned hash
#   bad     the file exists but does not match
#   missing the file is not there at all
#   info    no pinned value: GameManager.ps1 itself, or a custom IPA
function New-IntegrityRow {
    param([string]$Name, [string]$Path, [string]$Expected)

    $actual = $null
    try {
        $state = 'missing'
        if ($Path -and (Test-Path -LiteralPath $Path -PathType Leaf -ErrorAction Stop)) {
            $actual = Get-Sha256Hex $Path
            $state = if (-not $Expected) { 'info' }
                     elseif ($actual -eq $Expected) { 'ok' }
                     else { 'bad' }
        }
    } catch {
        $state = 'unreadable'
    }

    return [pscustomobject]@{
        Name     = $Name
        Path     = $Path
        Expected = $Expected
        Actual   = $actual
        State    = $state
    }
}

# The three files reported on the 文件校验 page, whatever IPA is selected: the
# emulator, the game package that shipped with this release, and the manager.
#
# The bundled IPA is reported from its own path rather than from the selection,
# because running a different IPA is a normal thing to do and must not make the
# official file look missing. What is being watched is the shipped file, not the
# player's choice of what to run.
function Get-IntegrityReport {
    $bundled = Join-Path $script:IpaDir $script:BundledIpaName

    $rows = New-Object System.Collections.ArrayList
    [void]$rows.Add((New-IntegrityRow 'touchHLE.exe' `
        (Join-Path $script:HleDir 'touchHLE.exe') $script:PinnedExeSha256))
    [void]$rows.Add((New-IntegrityRow '内置游戏 IPA' $bundled $script:PinnedIpaSha256))
    if ($CoreOnly -and $env:ZFR_MANAGER_EXECUTABLE) {
        [void]$rows.Add((New-IntegrityRow '游戏管理.exe' $env:ZFR_MANAGER_EXECUTABLE $null))
    } else {
        [void]$rows.Add((New-IntegrityRow 'GameManager.ps1（管理器自身）' $script:ManagerPath $null))
    }
    return @($rows)
}

# One line the notice dialog and the status bar can both show.
function Get-IntegrityHeadline {
    param($Rows)

    $bundled = $Rows | Where-Object { $_.Name -eq '内置游戏 IPA' }
    switch ($bundled.State) {
        'missing' { return [pscustomobject]@{ Level = 'bad'; Text = '文件校验：缺少内置游戏 IPA，你拿到的可能是改版。' } }
        'bad' { return [pscustomobject]@{ Level = 'bad'; Text = '文件校验：内置游戏 IPA 与官方版本不符，你拿到的可能是改版。' } }
        'unreadable' { return [pscustomobject]@{ Level = 'warn'; Text = '文件校验：无法读取内置游戏 IPA，请检查文件权限或占用后重新校验。' } }
    }
    $bad = @($Rows | Where-Object { $_.State -notin @('ok','info') })
    if ($bad.Count -gt 0) {
        return [pscustomobject]@{
            Level = 'bad'
            Text  = ('文件校验：{0} 校验未通过，详见「文件校验」页。' -f
                (($bad | ForEach-Object { $_.Name }) -join '、'))
        }
    }
    return [pscustomobject]@{
        Level = 'ok'
        Text  = '文件校验：touchHLE.exe 与内置游戏 IPA 均与官方发布一致'
    }
}

function New-GameChildProcess {
    param($Paths, [int64]$SkipSeconds)

    if (-not ('ZfGameOutput' -as [type])) {
        Add-Type -Path (Join-Path (Split-Path -Parent $script:ManagerPath) 'GameOutput.cs')
    }

    # Diagnostic fingerprint: which IPA build actually ran.
    $ipaHash = $null
    if (Test-BundledIpa $paths.Ipa) {
        $bundledPath = Get-PinnedIpaPath
        $ipaHash = $script:IntegrityRows | Where-Object { $_.Path -eq $bundledPath } |
            Select-Object -First 1 -ExpandProperty Actual
    }

    # Set the clock override for this child process. --device-family and the rest come from touchHLE_options.txt, which
    # this UI writes; passing them on the command line would override that file.

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $paths.TouchHLE
    # The manager has already shown any warning for this launch.
    $psi.EnvironmentVariables['ZFR_MANAGER_IPA_CHECKED'] = '1'
    # Quotes matter: the IPA file name contains spaces.
    #
    # --no-error-popup: on a guest panic touchHLE would otherwise show a modal
    # "touchHLE crashed!" box and stay alive until somebody clicks it. This
    # manager starts the game with no console and a hidden parent window, so
    # that box can end up invisible -- leaving a bare touchHLE.exe behind that
    # looks exactly like "the game is still running" while nothing is on screen.
    # The manager reports the crash itself (exit code + captured panic text), so
    # the box is pure downside on this launch path.
    $psi.Arguments = '"' + $paths.Ipa + '" --no-error-popup'
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

    $process = Start-GameWithTimeOffset -StartInfo $psi -Paths $paths -SkipSeconds $SkipSeconds -IpaHash $ipaHash
    Write-RunState -Process $process -Ipa $paths.Ipa
    Write-ManagerLog ('launch pid={0} ipa={1} skip={2}s' -f $process.Id, (Split-Path -Leaf $paths.Ipa), $SkipSeconds)
    return $process
}

if ($CoreOnly) { return }

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
    New-Item -ItemType Directory -Path $sandbox | Out-Null
    $script:OptionsFile = Join-Path $sandbox 'touchHLE_options.txt'
    if ($null -ne $optionsBackup) {
        [System.IO.File]::WriteAllText($script:OptionsFile, $optionsBackup)
    }

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
                $liveHashBefore = Get-Sha256Hex $script:LiveSave
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
            @{ K = 'window_scale'; V = '6';     Want = $true;  Note = 'upper bound' }
            @{ K = 'window_scale'; V = '4.5';   Want = $true;  Note = 'high decimal' }
            @{ K = 'window_scale'; V = '9/2';   Want = $true;  Note = 'high fraction' }
            @{ K = 'window_scale'; V = '4.294967295'; Want = $true;  Note = 'u32 numerator limit' }
            @{ K = 'window_scale'; V = '4.294967297'; Want = $false; Note = 'reduced numerator exceeds u32' }
            @{ K = 'window_scale'; V = '8589934590/4294967295'; Want = $true; Note = 'fits u32 after reduction' }
            @{ K = 'window_scale'; V = '18446744073709551616/9223372036854775808'; Want = $false; Note = 'raw numerator exceeds u64' }
            @{ K = 'window_scale'; V = '2.5/2'; Want = $false; Note = 'fraction numerator must be an integer' }
            @{ K = 'window_scale'; V = '3/1.5'; Want = $false; Note = 'fraction denominator must be an integer' }
            @{ K = 'window_scale'; V = '0.5';   Want = $false; Note = 'below range' }
            @{ K = 'window_scale'; V = '6.01';  Want = $false; Note = 'above range' }
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
            @{ Fam = 'iphone'; Scale = '6';    Want = '2880 × 1920' }
            @{ Fam = 'ipad';   Scale = '6';    Want = '6144 × 4608' }
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

        [System.IO.File]::WriteAllLines($script:OptionsFile, @(
            'com.example.One: --fps-limit=60 --device-family=iphone --scale-hack=3'
            "com.example.Two: --fps-limit=30`t--scale-hack=1.5 --device-family=ipad --dump-app-info # keep"
        ))
        $savedIpa = $script:CurrentIpa
        try {
            Set-CurrentIpa -IpaInfo @{ AppId = 'com.example.Two' }
            Save-Settings -Settings @{ fps_limit = '90' }
            $specific = Get-CurrentSettings
            $fileText = [System.IO.File]::ReadAllText($script:OptionsFile)
            $partialOk = $specific.fps_limit -eq '90' -and $specific.window_family -eq 'ipad' -and
                $specific.window_scale -eq '1.5' -and $fileText.Contains('--dump-app-info') -and
                $fileText.Contains('# keep') -and $fileText.Contains('com.example.One: --fps-limit=60 --device-family=iphone --scale-hack=3')
            Write-Host ("  partial settings merge : " + $(if ($partialOk) { 'PASS' } else { 'FAIL' }))
            if (-not $partialOk) { $ok = $false }

            $invalidRefused = $false
            try { Save-Settings -Settings @{ window_scale = '7/' } } catch { $invalidRefused = $true }
            if (-not $invalidRefused -or [System.IO.File]::ReadAllText($script:OptionsFile) -cne $fileText) {
                Write-Host '  invalid scale untouched : FAIL'
                $ok = $false
            } else {
                Write-Host '  invalid scale untouched : PASS'
            }

            Set-CurrentIpa -IpaInfo @{ Path = 'unreadable.ipa'; AppId = $null }
            $refused = $false
            try { Save-Settings -Settings @{ fps_limit = '30' } } catch { $refused = $true }
            $isolated = $refused -and -not $script:SaveDir -and -not $script:LiveSave -and
                @(Get-BackupFiles).Count -eq 0 -and [System.IO.File]::ReadAllText($script:OptionsFile) -ceq $fileText
            Write-Host ("  unknown IPA has no writable profile : " + $(if ($isolated) { 'PASS' } else { 'FAIL' }))
            if (-not $isolated) { $ok = $false }
        } finally {
            Set-CurrentIpa -IpaInfo $savedIpa
            [System.IO.File]::WriteAllBytes($script:OptionsFile, $bytes)
        }

        Write-Host ''
        Write-Host '--- save management (sandboxed) ---'
        New-Item -ItemType Directory -Force -Path $sandbox | Out-Null
        $clockRoot = Join-Path $sandbox 'clocks'
        [void][IO.Directory]::CreateDirectory($clockRoot)
        [IO.File]::WriteAllText((Join-Path $clockRoot 'touchHLE_time_offset_seconds.txt'), '7200')
        $secondFarm = Get-FarmOffsetPath 'com.playforge.ZombieFarmChinese' $clockRoot
        $firstFarm = Get-FarmOffsetPath 'com.playforge.ZombieFarm.ZFR' $clockRoot
        if ((Read-TimeOffset $secondFarm) -ne 0 -or (Read-TimeOffset $firstFarm) -ne 7200) { throw 'Farm clock migration failed' }
        Write-TimeOffset 3600 $secondFarm
        Write-TimeOffset 0 $secondFarm
        if ((Read-TimeOffset $firstFarm) -ne 7200) { throw 'Farm clocks are not isolated' }
        Write-Host '  legacy clock migration and independent resets : PASS'
        [System.IO.File]::WriteAllText($offsetFixture, '7200', [System.Text.Encoding]::ASCII)
        Write-TimeOffset -Value 0 -Path $offsetFixture
        $resetOffset = Read-TimeOffset -Path $offsetFixture
        Write-Host ("  reset time offset    : {0} sec  {1}" -f $resetOffset, $(if ($resetOffset -eq 0) { 'PASS' } else { 'FAIL' }))
        if ($resetOffset -ne 0) { $ok = $false }
        Write-TimeOffset -Value 7200 -Path $offsetFixture

        $launchClock = Join-Path $clockRoot 'launch-test.txt'
        $probePaths = @{ OffsetFile = $launchClock; Ipa = $offsetFixture; Fingerprint = (Join-Path $clockRoot 'probe-launch.txt') }
        $probe = [Diagnostics.ProcessStartInfo]::new()
        $probe.UseShellExecute = $false
        $probe.CreateNoWindow = $true
        $probe.FileName = Join-Path $clockRoot 'missing.exe'
        foreach ($before in @($null, '7200', 'unreadable')) {
            if ($null -ne $before) { [IO.File]::WriteAllText($launchClock, $before) }
            $failed = $false
            try { [void](Start-GameWithTimeOffset $probe $probePaths 3600 -Reset:($before -ne '7200')) }
            catch { $failed = $true }
            if (-not $failed -or [IO.File]::Exists($launchClock) -ne ($null -ne $before) -or
                ($null -ne $before -and [IO.File]::ReadAllText($launchClock) -cne $before)) {
                throw 'A failed process creation changed the farm clock.'
            }
        }
        $probe.FileName = $env:ComSpec
        $probe.Arguments = '/d /c exit 23'
        if ([IO.File]::Exists($probePaths.Fingerprint)) { throw 'A failed launch replaced the last successful launch record.' }
        $child = Start-GameWithTimeOffset $probe $probePaths 3600 -Reset
        try {
            $child.WaitForExit()
            if ($child.ExitCode -ne 23 -or (Read-TimeOffset $launchClock) -ne 3600) {
                throw 'An already-started child must keep its simulated time even on a nonzero exit.'
            }
        } finally { $child.Dispose() }
        Write-Host '  clock rollback on launch failure and nonzero child exit : PASS'

        # An extra IPA's saves are opaque; only the bundled ZFR has a known format.
        $selectedId = $script:AppId
        $script:AppId = 'org.example.OtherFarm'
        $live = Join-Path $sandbox 'saveGame.bin2'
        [System.IO.File]::WriteAllBytes($live, [byte[]](1..40))
        [System.IO.File]::WriteAllBytes((Join-Path $sandbox 'saveGame.bin2.bak'), [byte[]](1..20))

        $count0 = (Get-BackupFiles -Directory $sandbox).Count
        Write-Host ("  initial backups      : {0}" -f $count0)

        # 1. new backup
        [IO.File]::SetLastWriteTime($live, [datetime]'2000-01-01')
        $beforeBackup = [datetime]::Now.AddMilliseconds(-1)
        $made = New-SaveBackup -Directory $sandbox -Label 'manual' -OffsetFile $offsetFixture
        $row = Get-BackupFiles -Directory $sandbox | Where-Object FullName -eq $made
        if ($row.BackupTime -lt $beforeBackup -or $row.BackupTime -gt [datetime]::Now -or $row.BackupKind -ne 'manual') {
            throw 'New backup uses the modification time of the old farm.'
        }
        # Legacy second-resolution labels, currency-tool milliseconds and numeric collision suffixes.
        $orderDir = [IO.Directory]::CreateDirectory((Join-Path $sandbox 'backup-order')).FullName
        $names = @('20250301-120000-200-10', '20250301-120000-200-2', '20250301-120000-120',
            '20250301-120000-pre-restore-10', '20250301-120000-pre-restore-2', '20240101-180000-manual')
        foreach ($name in $names) { [IO.File]::WriteAllText((Join-Path $orderDir "$($script:BackupPrefix)-$name"), 'farm') }
        $legacy = Join-Path $orderDir $script:BackupPrefix
        [IO.File]::WriteAllText($legacy, 'farm')
        [IO.File]::SetCreationTime($legacy, [datetime]'2018-01-01')
        $ordered = @(Get-BackupFiles -Directory $orderDir)
        $expectedNames = @($names | ForEach-Object { "$($script:BackupPrefix)-$_" }) + $script:BackupPrefix
        if (($ordered.Name -join '|') -ne ($expectedNames -join '|') -or $ordered[0].BackupTime.Millisecond -ne 200 -or
            $ordered[0].BackupKind -ne '备份' -or $ordered[3].BackupKind -ne 'pre-restore' -or
            $ordered[-1].BackupTime -ne [IO.File]::GetCreationTime($legacy)) { throw 'Backup list chronology is incorrect.' }
        Write-Host '  backup creation dates, legacy names and numeric order : PASS'
        $count1 = (Get-BackupFiles -Directory $sandbox).Count
        $sizeOk = (Get-Item -LiteralPath $made).Length -eq 40
        $savedOffset = (Get-Content -Raw -LiteralPath (Get-BackupOffsetPath -BackupPath $made) -Force | ConvertFrom-Json).offset
        $sidecarsHiddenFromList = @((Get-BackupFiles -Directory $sandbox | Where-Object { $_.Name.EndsWith($script:BackupOffsetSuffix) })).Count -eq 0
        Write-Host ("  after 新增备份        : {0}  (+{1})  content={2}" -f `
            $count1, ($count1 - $count0), $(if ($sizeOk) { 'ok' } else { 'FAIL' }))
        if ($count1 -ne ($count0 + 1) -or -not $sizeOk) { $ok = $false }
        Write-Host ("  backup time offset   : {0} sec  {1}" -f $savedOffset, $(if ($savedOffset -eq 7200 -and $sidecarsHiddenFromList) { 'PASS' } else { 'FAIL' }))
        if ($savedOffset -ne 7200 -or -not $sidecarsHiddenFromList) { $ok = $false }

        $oldHash = Get-Sha256Hex $live
        foreach ($replacement in @('empty', 'tampered')) {
            if ($replacement -eq 'empty') { [IO.File]::WriteAllBytes($made, [byte[]]@()) }
            else { [IO.File]::WriteAllBytes($made, [byte[]](40..1)) }
            $rejected = $false
            try { [void](Restore-SaveBackup $made $sandbox $offsetFixture) } catch { $rejected = $true }
            if (-not $rejected -or (Get-Sha256Hex $live) -ne $oldHash) { throw "Damaged backup accepted: $replacement" }
        }
        [IO.File]::WriteAllBytes($made, [byte[]](1..40))
        Write-Host '  empty and same-size damaged backups refused : PASS'

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

        $emptySaveDir = Join-Path $sandbox 'first-restore'
        New-Item -ItemType Directory -Path $emptySaveDir | Out-Null
        $offsetBackup = New-SaveBackup -Directory $sandbox -Label 'rollback-test' -OffsetFile $offsetFixture
        $lockedClock = [System.IO.File]::Open($offsetFixture, 'Open', 'Read', 'Read')
        try {
            $restoreRefused = $false
            try {
                [void](Restore-SaveBackup -BackupPath $offsetBackup -Directory $emptySaveDir -OffsetFile $offsetFixture)
            } catch {
                $restoreRefused = $true
            }
            $rollbackOk = $restoreRefused -and -not (Test-Path -LiteralPath (Join-Path $emptySaveDir 'saveGame.bin2')) -and
                ((Read-TimeOffset -Path $offsetFixture) -eq 12345)
            Write-Host ("  interrupted first restore : " + $(if ($rollbackOk) { 'PASS' } else { 'FAIL' }))
            if (-not $rollbackOk) { $ok = $false }
        } finally {
            $lockedClock.Dispose()
            [void](Remove-SaveBackup -BackupPath $offsetBackup)
        }

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
            [void](New-SaveBackup -Directory $sandbox -Label "bulk$i" -OffsetFile $offsetFixture)
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
        Write-Host '--- currency fixture (v14) ---'
        if ($liveHashBefore) {
            $current = Get-Currency
            if ($current) { Write-Host ("  current farm: Gold={0} Brains={1}" -f $current.Gold, $current.Brains) }
        }
        $copy = Join-Path $sandbox 'saveGame.bin2'
        $fixture = New-Object byte[] 512
        $fixture[0] = 14
        ([byte[]]@(1,9,0,0,0) + [Text.Encoding]::ASCII.GetBytes('UNDEFINED')).CopyTo($fixture, 64)
        $fixture[64 + 0x42] = 4
        $script:AppId = 'com.playforge.ZombieFarm.ZFR'
        [IO.File]::WriteAllBytes($copy, $fixture)
        $validBackup = New-SaveBackup -Directory $sandbox -OffsetFile $offsetFixture
        $oldFormat = [byte[]]@(13,0,0,0,1,2,3,4)
        [IO.File]::WriteAllBytes($copy, $oldFormat)
        $olderBackup = New-SaveBackup -Directory $sandbox -OffsetFile $offsetFixture
        [IO.File]::Delete((Get-BackupOffsetPath $olderBackup))
        [IO.File]::WriteAllBytes($copy, $fixture)
        [void](Restore-SaveBackup $olderBackup $sandbox $offsetFixture)
        if ((Get-Sha256Hex $copy) -ne (Get-Sha256Hex $olderBackup)) { throw 'Legacy version backup was not preserved.' }
        foreach ($field in @('header', 'short', 'completed', 'active', 'progress')) {
            [byte[]]$damaged = $fixture.Clone()
            switch ($field) {
                'header' { $damaged = $oldFormat[0..2] }
                'short' { $damaged = $damaged[0..7] }
                'completed' { [BitConverter]::GetBytes([uint32]::MaxValue).CopyTo($damaged, 64 + 0x56) }
                'active' { [BitConverter]::GetBytes([uint32]::MaxValue).CopyTo($damaged, 64 + 0x5a) }
                'progress' { $damaged[64 + 0x5a] = 1; [BitConverter]::GetBytes([uint32]::MaxValue).CopyTo($damaged, 64 + 0x62) }
            }
            [IO.File]::WriteAllBytes($copy, $damaged)
            $rejected = $false
            try { [void](New-SaveBackup -Directory $sandbox -OffsetFile $offsetFixture) } catch { $rejected = $true }
            if (-not $rejected) { throw "Accepted invalid ZFR backup: $field" }
            [IO.File]::WriteAllBytes($legacyBackup, $damaged)
            [IO.File]::WriteAllBytes($copy, $fixture)
            $rejected = $false
            try { [void](Restore-SaveBackup $legacyBackup $sandbox $offsetFixture) } catch { $rejected = $true }
            if (-not $rejected -or (Get-Sha256Hex $copy) -ne (Get-Sha256Hex $validBackup)) { throw "Accepted invalid ZFR restore: $field" }
        }
        # Integrity of a backup does not depend on whether its currency is editable.
        [BitConverter]::GetBytes([int]-1).CopyTo($fixture, 64 + 0x46)
        [IO.File]::WriteAllBytes($copy, $fixture)
        [void](New-SaveBackup -Directory $sandbox -OffsetFile $offsetFixture)
        [IO.File]::Copy($copy, $legacyBackup, $true)
        [void](Restore-SaveBackup $legacyBackup $sandbox $offsetFixture)
        if ((Get-Sha256Hex $copy) -ne (Get-Sha256Hex $legacyBackup)) { throw 'Legacy ZFR restore changed its contents.' }
        foreach ($withFarm in @($true, $false)) {
            if (-not $withFarm) { [IO.File]::Delete($copy) }
            [IO.File]::WriteAllBytes($offsetFixture, [byte[]]@(0xfe, 0x11, 0x09))
            $clockHash = Get-Sha256Hex $offsetFixture
            $archivesBefore = @(Get-ChildItem -LiteralPath (Join-Path $sandbox 'recovery') -Directory -ErrorAction SilentlyContinue)
            [void](Restore-SaveBackup $validBackup $sandbox $offsetFixture)
            $archive = @(Get-ChildItem -LiteralPath (Join-Path $sandbox 'recovery') -Directory | Where-Object { $_.FullName -notin $archivesBefore.FullName })
            if ($archive.Count -ne 1 -or (Get-Sha256Hex (Join-Path $archive[0].FullName 'touchHLE_time_offset_seconds.txt')) -ne $clockHash -or
                (Read-TimeOffset $offsetFixture) -ne 12345 -or (Get-Sha256Hex $copy) -ne (Get-Sha256Hex $validBackup)) {
                throw 'Failed to preserve damaged clock and restore backup.'
            }
            $archivedFarm = Join-Path $archive[0].FullName 'saveGame.bin2'
            if ([IO.File]::Exists($archivedFarm) -ne $withFarm -or ($withFarm -and (Get-Sha256Hex $archivedFarm) -ne (Get-Sha256Hex $legacyBackup))) {
                throw 'Recovery archive does not match the farm present before restoring.'
            }
        }
        Write-Host '  ZFR player and quest bounds, legacy backups, damaged clock recovery with and without live save : PASS'
        $script:AppId = $selectedId
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
        $sizeSame = (Get-Item -LiteralPath $copy).Length -eq $fixture.Length
        Write-Host ("  file size unchanged  : " + $(if ($sizeSame) { 'PASS' } else { 'FAIL' }))
        if (-not $sizeSame) { $ok = $false }

        # A backup must have been made alongside it.
        $bakExists = Test-Path -LiteralPath $writtenBackup
        Write-Host ("  backup written       : " + $(if ($bakExists) { 'PASS' } else { 'FAIL' }))
        if (-not $bakExists) { $ok = $false }
        $currencyBackupOffset = (Get-Content -Raw -LiteralPath (Get-BackupOffsetPath -BackupPath $writtenBackup) -Force | ConvertFrom-Json).offset
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

        # "Is the game running?" must be answered from a verified record, not
        # from a name-wide scan: a leftover record or a reused PID used to make
        # the manager claim a game was running when nothing was on screen.
        Write-Host ''
        Write-Host '--- game process state ---'
        $savedRunState = $script:RunStateFile
        $savedManagerLog = $script:ManagerLog
        $script:RunStateFile = Join-Path $sandbox 'zfr_running.json'
        $script:ManagerLog = Join-Path $sandbox 'zfr_manager.log'
        try {
            $self = Get-Process -Id $PID
            $selfPath = Get-ProcessImagePath -Process $self
            $selfStamp = Get-ProcessStartStamp -Process $self

            # A record that matches a live process is authoritative.
            @{ pid = $PID; start = $selfStamp; exe = $selfPath } | ConvertTo-Json -Compress |
                Set-Content -LiteralPath $script:RunStateFile -Encoding utf8
            $st = Get-GameProcessState -ExpectedExe $selfPath
            $recOk = $st.Running -and $st.Source -eq 'record'
            Write-Host ("  live record honoured : running={0} source={1}  {2}" -f $st.Running, $st.Source, $(if ($recOk) { 'PASS' } else { 'FAIL' }))
            if (-not $recOk) { $ok = $false }

            # Same PID, different start time = the PID was reused: the record
            # must be dropped instead of reporting a phantom game.
            @{ pid = $PID; start = '2001-01-01T00:00:00.0000000Z'; exe = $selfPath } |
                ConvertTo-Json -Compress | Set-Content -LiteralPath $script:RunStateFile -Encoding utf8
            $st = Get-GameProcessState -ExpectedExe $selfPath
            $reuseOk = (-not $st.Running -or $st.Source -ne 'record') -and
                       (-not (Test-Path -LiteralPath $script:RunStateFile))
            Write-Host ("  reused pid rejected  : running={0} record cleared={1}  {2}" -f $st.Running,
                (-not (Test-Path -LiteralPath $script:RunStateFile)),
                $(if ($reuseOk) { 'PASS' } else { 'FAIL' }))
            if (-not $reuseOk) { $ok = $false }

            # A record whose process is gone must not survive.
            @{ pid = 999999; start = 'x'; exe = 'x' } | ConvertTo-Json -Compress |
                Set-Content -LiteralPath $script:RunStateFile -Encoding utf8
            $st = Get-GameProcessState
            $deadOk = (-not (Test-Path -LiteralPath $script:RunStateFile))
            Write-Host ("  dead pid rejected    : record cleared={0}  {1}" -f $deadOk, $(if ($deadOk) { 'PASS' } else { 'FAIL' }))
            if (-not $deadOk) { $ok = $false }

            $invalidRecords = @(
                @{ pid = $PID }
                @{ pid = 'not-a-number'; start = $selfStamp; exe = $selfPath }
            )
            foreach ($record in $invalidRecords) {
                $record | ConvertTo-Json -Compress | Set-Content -LiteralPath $script:RunStateFile -Encoding utf8
                $st = Get-GameProcessState -ExpectedExe $selfPath
                $invalidOk = -not $st.Running -and -not (Test-Path -LiteralPath $script:RunStateFile)
                Write-Host ("  invalid record cleared : " + $(if ($invalidOk) { 'PASS' } else { 'FAIL' }))
                if (-not $invalidOk) { $ok = $false }
            }

            # Exit codes and panic text are what the player actually sees.
            $hint = Get-ExitCodeHint -Code -1073741819
            $hintOk = $hint -like '0xC0000005*'
            Write-Host ("  crash code readable  : '{0}'  {1}" -f $hint, $(if ($hintOk) { 'PASS' } else { 'FAIL' }))
            if (-not $hintOk) { $ok = $false }

            $panic = Get-PanicSummary -Text "noise`r`nthread 'main' panicked at src/foo.rs:12:3`r`nnote: run with RUST_BACKTRACE"
            $panicOk = $panic -like "*panicked at src/foo.rs*"
            Write-Host ("  panic line extracted : '{0}'  {1}" -f $panic, $(if ($panicOk) { 'PASS' } else { 'FAIL' }))
            if (-not $panicOk) { $ok = $false }
        } finally {
            $script:RunStateFile = $savedRunState
            $script:ManagerLog = $savedManagerLog
        }

        # The real save must be byte-identical to when the selftest started.
        # (Also fails if the game itself wrote the save mid-test -- close the
        # game before running -SelfTest.)
        if ($null -ne $liveHashBefore) {
            $liveHashAfter = Get-Sha256Hex $script:LiveSave
            $liveOk = $liveHashAfter -eq $liveHashBefore
            Write-Host ("  real save untouched  : " + $(if ($liveOk) { 'PASS' } else { 'FAIL (live save changed during selftest!)' }))
            if (-not $liveOk) { $ok = $false }
        }

        Write-Host ''
        Write-Host ("SELFTEST: " + $(if ($ok) { 'PASS' } else { 'FAIL' }))
        exit $(if ($ok) { 0 } else { 1 })
    } finally {
        if (Test-Path -LiteralPath $sandbox) {
            $sandboxPath = (Resolve-Path -LiteralPath $sandbox).Path
            $tempPath = (Resolve-Path -LiteralPath $env:TEMP).Path.TrimEnd('\')
            if ((Split-Path -Parent $sandboxPath) -eq $tempPath -and
                (Split-Path -Leaf $sandboxPath) -match '^zfr_savetest_[a-f0-9]{32}$') {
                Remove-Item -LiteralPath $sandboxPath -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# Only the compatibility window needs WinForms.
. (Join-Path $PSScriptRoot 'compat\WinForms.ps1')
