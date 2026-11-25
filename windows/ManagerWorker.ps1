# Persistent, windowless storage worker for the Tauri launcher. Only JSON is
# written to stdout. One request finishes before the next can modify the save.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
. (Join-Path $PSScriptRoot 'GameManager.ps1') -CoreOnly
$script:KnownIpas = @{}
$script:ExternalIpas = @{}
$script:Session = $null

function Read-ManagerIpa($file) {
    $cached = $script:KnownIpas[$file.FullName]
    $stamp = "$($file.LastWriteTimeUtc.Ticks):$($file.Length)"
    if (-not $cached -or $cached.stamp -ne $stamp) {
        $cached = @{ stamp = $stamp; info = Read-IpaInfo $file.FullName }
        $script:KnownIpas[$file.FullName] = $cached
    }
    return $cached.info
}

function Get-ManagerSnapshot {
    $files = @(Get-IpaList)
    $wanted = Get-DefaultIpaPath
    if ($wanted -and $files.FullName -notcontains $wanted) { $script:ExternalIpas[$wanted] = $true }
    foreach ($path in $script:ExternalIpas.Keys) {
        if ($files.FullName -notcontains $path -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            $files += Get-Item -LiteralPath $path
        }
    }
    $selected = $null
    $entries = @(foreach ($file in $files) {
        $info = Read-ManagerIpa $file
        if ($info.Path -eq $wanted) { $selected = $info }
        @{ name = $info.Name; path = $info.Path; appId = $info.AppId; version = $info.Version; error = $info.Error }
    })
    Set-CurrentIpa $selected
    $saves = @(if ($script:SaveDir) {
        if (Test-Path -LiteralPath $script:LiveSave -PathType Leaf) {
            $file = Get-Item -LiteralPath $script:LiveSave
            @{ name = $file.Name; kind = '当前存档'; size = $file.Length; modified = $file.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'); live = $true }
        }
        foreach ($file in (Get-BackupFiles)) {
            @{ name = $file.Name; kind = (Get-BackupKind $file); size = $file.Length; modified = $file.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'); live = $false }
        }
    })
    $amounts = Get-Currency
    $currency = $null
    if ($amounts) { $currency = @{ gold = $amounts.Gold; brains = $amounts.Brains } }
    $offset = try {
        $seconds = Read-TimeOffset
        [void](Format-SimulatedTime -Offset $seconds -Base (Get-SimulatedTimeBase))
        $seconds
    } catch { $null }
    [int64]$fixedSeconds = 0
    $fixedTime = $null
    if ([int64]::TryParse($env:TOUCHHLE_FAKE_UNIX_TIME, [ref]$fixedSeconds)) { $fixedTime = $fixedSeconds }
    $skip = Read-SkipMemory
    if (-not $skip) { $skip = @{ hours = 6; minutes = 0 } }
    return @{
        ipas = $entries; selected = $selected.Path; settings = Get-CurrentSettings; currency = $currency
        saves = $saves; saveDir = $script:SaveDir; offset = $offset; fixedTime = $fixedTime
        skip = @{ hours = $skip.Hours; minutes = $skip.Minutes }; running = Test-GameRunning
    }
}

function Get-ManagerVerification {
    $script:IntegrityRows = @(Get-IntegrityReport)
    $headline = Get-IntegrityHeadline $script:IntegrityRows
    $rows = @(foreach ($row in $script:IntegrityRows) {
        @{ name = $row.Name; path = $row.Path; state = $row.State; expected = $row.Expected; actual = $row.Actual }
    })
    return @{ level = $headline.Level; text = $headline.Text; rows = $rows }
}

function Resolve-ManagerBackups([string[]]$names) {
    $requested = [Collections.Generic.HashSet[string]]::new($names, [StringComparer]::Ordinal)
    foreach ($file in (Get-BackupFiles)) {
        if ($requested.Remove($file.Name)) { $file.FullName }
    }
    if ($requested.Count) { throw '备份已不存在，请刷新列表。' }
}

function Start-ManagerGame($data) {
    $running = Get-GameProcessState
    if ($running.Running) {
        if ($running.Window -ne 0) { throw '游戏已经在运行了。' }
        $stamp = Get-ProcessStartStamp $running.Process
        if (-not $data.orphan) { return @{ orphan = @{ pid = $running.Pid; start = $stamp } } }
        if (-not $stamp -or $stamp -cne $data.orphan.start -or $running.Pid -ne $data.orphan.pid) {
            throw '游戏进程已变化，请再次尝试。'
        }
        $running.Process.Refresh()
        if ($running.Process.MainWindowHandle.ToInt64() -ne 0) { throw '游戏窗口已经出现。' }
        $running.Process.Kill()
        if (-not $running.Process.WaitForExit(5000)) { throw '游戏进程仍在退出，请稍后重试。' }
        Remove-RunState
        Write-ManagerLog ("ended windowless pid={0}" -f $running.Pid)
    }
    if ($script:Session) { throw '上次运行正在结束，请稍后重试。' }
    $paths = Get-LaunchPaths
    if (-not $paths.Ipa -or -not (Test-Path -LiteralPath $paths.Ipa -PathType Leaf)) { throw '找不到游戏 IPA，请选择一个可用的文件。' }
    if (-not (Test-Path -LiteralPath $paths.TouchHLE -PathType Leaf)) { throw '找不到 touchHLE.exe。' }
    $report = Get-ManagerVerification
    if ($report.level -ne 'ok' -and $data.allowModified -ne $true) { return @{ warning = $report.text } }
    if ([string]$data.hours -notmatch '^\d{1,4}$' -or [string]$data.minutes -notmatch '^\d{1,2}$' -or [int]$data.minutes -gt 59) {
        throw '请输入 0～9999 的小时与 0～59 的分钟。'
    }
    $skip = ([int64]$data.hours * 3600) + ([int]$data.minutes * 60)
    $process = New-GameChildProcess -Paths $paths -SkipSeconds $skip
    $script:Session = @{
        process = $process; started = (Get-Date); seenWindow = $false; lastWindow = (Get-Date); offered = $false
        stdout = $process.StandardOutput.ReadToEndAsync(); stderr = $process.StandardError.ReadToEndAsync()
    }
    if ($data.remember) { Save-SkipMemory -Hours $data.hours -Minutes $data.minutes }
    return @{ started = $true }
}

function Get-ManagerGameStatus {
    $session = $script:Session
    if (-not $session) { return @{ done = $true; error = $false; message = '游戏已退出。' } }
    $process = $session.process
    $process.Refresh()
    if (-not $process.HasExited) {
        if ($process.MainWindowHandle.ToInt64() -ne 0) {
            $session.seenWindow = $true
            $session.lastWindow = Get-Date
        } elseif (-not $session.offered) {
            $grace = if ($session.seenWindow) { 20 } else { 120 }
            if (((Get-Date) - $session.lastWindow).TotalSeconds -ge $grace) {
                $session.offered = $true
                return @{ stalled = $true; message = '游戏进程仍在运行，但没有显示窗口。是否结束这个进程，回到管理器？' }
            }
        }
        return @{ done = $false }
    }
    $process.WaitForExit()
    $code = $process.ExitCode
    $out = $session.stdout.Result
    $err = $session.stderr.Result
    $duration = ((Get-Date) - $session.started).TotalSeconds
    Write-ManagerLog ('exit pid={0} code={1} after {2:N0}s' -f $process.Id, $code, $duration)
    try {
        if ($out -or $err) {
            Add-Content -LiteralPath (Join-Path $script:HleDir 'zfr_last_run.log') -Encoding UTF8 -Value (
                '[{0}] exit={1}{2}{3}{2}{4}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $code, [Environment]::NewLine, $out, $err)
        }
    } finally {
        # Another manager can take over if the original GUI closes mid-game.
        # Clear the record only while it still names this child.
        if (Test-Path -LiteralPath $script:RunStateFile) {
            try {
                $record = Get-Content -LiteralPath $script:RunStateFile -Raw | ConvertFrom-Json
                if ($record.pid -eq $process.Id) { Remove-RunState }
            } catch { }
        }
        $process.Dispose()
        $script:Session = $null
    }
    $message = '游戏已退出。'
    if ($code -ne 0) {
        $reason = Get-PanicSummary $err
        if (-not $reason) { $reason = Get-ExitCodeHint $code }
        $message = "游戏异常退出：${reason}（详见 zfr_last_run.log）"
    }
    return @{ done = $true; error = ($code -ne 0); message = $message }
}

function Invoke-ManagerAction([string]$action, $data) {
    switch -Exact ($action) {
        'snapshot' { return Get-ManagerSnapshot }
        'verify' { return Get-ManagerVerification }
        'selectIpa' {
            $file = Get-Item -LiteralPath $data.path
            if ($file.PSIsContainer -or $file.Extension -ine '.ipa') { throw '请选择 IPA 文件。' }
            $info = Read-ManagerIpa $file
            Save-IpaSelection $info.Path
        }
        'setSetting' {
            if (-not $script:CurrentIpa) { throw '请先选择 IPA。' }
            $key = [string]$data.key
            if (-not $script:SettingDefs.Contains($key)) { throw '设置项无效。' }
            Save-Settings -Settings @{ $key = [string]$data.value }
            return @{ settings = Get-CurrentSettings }
        }
        'resetTime' {
            if (-not $script:CurrentIpa) { throw '请先选择 IPA。' }
            if (Test-GameRunning) { throw '请先退出游戏再重置模拟时间。' }
            Write-TimeOffset -Value 0 -Path (Get-LaunchPaths).OffsetFile
        }
        'setCurrency' {
            if (Test-GameRunning) { throw '请先关闭游戏再修改存档。' }
            if ([string]$data.gold -notmatch '^\d{1,10}$' -or [string]$data.brains -notmatch '^\d{1,10}$') {
                throw '金币与脑子必须是 0～2147483647 的整数。'
            }
            [void](Set-Currency -Gold $data.gold -Brains $data.brains)
        }
        'backup' {
            if (Test-GameRunning) { throw '请先关闭游戏再备份存档。' }
            [void](New-SaveBackup)
        }
        'restore' {
            if (Test-GameRunning) { throw '请先关闭游戏再还原存档。' }
            [void](Restore-SaveBackup -BackupPath (Resolve-ManagerBackups $data.name))
        }
        'delete' {
            # Resolve the full selection before deleting anything, including when a
            # backup disappeared after the list was displayed.
            $targets = @(Resolve-ManagerBackups $data.names)
            foreach ($path in $targets) { [void](Remove-SaveBackup -BackupPath $path) }
        }
        'openSaves' {
            if (-not $script:SaveDir -or -not (Test-Path -LiteralPath $script:SaveDir -PathType Container)) { throw '当前 IPA 尚无存档目录。' }
            [void][Diagnostics.Process]::Start((Join-Path $env:SystemRoot 'explorer.exe'), ('"' + $script:SaveDir + '"'))
            return $null
        }
        'openProject' { Start-Process -FilePath $script:ProjectUrl; return $null }
        'launch' { return Start-ManagerGame $data }
        'gameStatus' { return Get-ManagerGameStatus }
        'stopStalled' {
            if ($script:Session -and $script:Session.offered) {
                $process = $script:Session.process
                $process.Refresh()
                if (-not $process.HasExited -and $process.MainWindowHandle.ToInt64() -eq 0) { $process.Kill() }
            }
            return $null
        }
        default { throw '未知操作。' }
    }
    return Get-ManagerSnapshot
}

while ($null -ne ($line = [Console]::ReadLine())) {
    try {
        $request = $line | ConvertFrom-Json
        $result = Invoke-ManagerAction $request.action $request.data
        $response = @{ ok = $true; value = $result }
    } catch {
        $response = @{ ok = $false; error = $_.Exception.Message }
    }
    [Console]::WriteLine(($response | ConvertTo-Json -Depth 8 -Compress))
}


# Keep redirected game output draining if the user closes the manager mid-game.
if ($script:Session) {
    $script:Session.process.WaitForExit()
    [void](Get-ManagerGameStatus)
}
