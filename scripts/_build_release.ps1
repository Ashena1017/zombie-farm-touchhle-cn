# Assemble and verify the portable Windows ZIP in a disposable staging folder.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$OutputDir = (Join-Path $Root 'dist\windows'),
    [switch]$SkipVerify
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath $Root).Path
$windowsDir = Join-Path $Root 'windows'
$hleRoot = Join-Path $Root 'run\windows\touchHLE'
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$outputName = 'zombie-farm-windows-x64'
$manifestPath = Join-Path $Root 'release.json'
$releaseInfo = Get-Content -Raw -Encoding UTF8 -LiteralPath $manifestPath | ConvertFrom-Json
$ipaName = $releaseInfo.ipa.name

function Log([string]$message) { Write-Host $message }

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$stage = Join-Path $outputDir ('.package-' + [Guid]::NewGuid().ToString('N'))
$release = Join-Path $stage $outputName
$archive = Join-Path $stage ($outputName + '.zip')
$output = Join-Path $outputDir ($outputName + '.zip')
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $release 'zombie_farm_ipa') | Out-Null

    $hleDir = Join-Path $release 'touchHLE'
    New-Item -ItemType Directory -Force -Path $hleDir | Out-Null

    # --- the emulator, in its own folder ---------------------------------------
    Log ''
    Log '--- touchHLE\ ---'
    foreach ($f in @('touchHLE.exe', 'touchHLE_default_options.txt')) {
        $src = Join-Path $hleRoot $f
        if (-not (Test-Path -LiteralPath $src)) { throw "missing: $src" }
        Copy-Item -LiteralPath $src -Destination $hleDir
        Log ("  {0,-30} {1,12:N0} B" -f $f, (Get-Item -LiteralPath $src).Length)
    }
    Copy-Item -LiteralPath (Join-Path $windowsDir 'touchHLE_options.txt') -Destination $hleDir
    foreach ($d in @('touchHLE_dylibs', 'touchHLE_fonts')) {
        $src = Join-Path $hleRoot $d
        if (-not (Test-Path -LiteralPath $src)) { throw "missing folder: $src" }
        Copy-Item -LiteralPath $src -Destination $hleDir -Recurse
        $n = (Get-ChildItem -LiteralPath (Join-Path $hleDir $d) -Recurse -File | Measure-Object).Count
        $sz = (Get-ChildItem -LiteralPath (Join-Path $hleDir $d) -Recurse -File |
            Measure-Object -Property Length -Sum).Sum
        Log ("  {0,-30} {1,3} files  {2,12:N0} B" -f $d, $n, $sz)
    }

    # --- the manager, at the top level -----------------------------------------
    Log ''
    Log '--- manager (top level) ---'
    & (Join-Path $windowsDir 'launcher\build.ps1') -Destination (Join-Path $release '游戏管理.exe')
    New-Item -ItemType Directory -Path (Join-Path $release 'compat') | Out-Null
    foreach ($f in @('GameManager.ps1', 'ManagerWorker.ps1', 'compat\WinForms.ps1')) {
        $src = Join-Path $windowsDir $f
        if (-not (Test-Path -LiteralPath $src)) { throw "missing: $src" }
        Copy-Item -LiteralPath $src -Destination (Join-Path $release $f)
        Log ("  {0,-30} {1,12:N0} B" -f $f, (Get-Item -LiteralPath $src).Length)
    }
    Copy-Item -LiteralPath $manifestPath -Destination $release

    # --- the non-system DLLs the exe actually imports ---------------------------
    # From dumpbin /dependents. Without these the exe will not start on a machine that
    # lacks the VC++ 2015-2022 redistributable. touchHLE.exe imports the same ones.
    Log ''
    Log '--- required VC++ runtime DLLs (top level) ---'
    foreach ($f in @('MSVCP140.dll', 'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll')) {
        $src = Join-Path $windowsDir $f
        if (-not (Test-Path -LiteralPath $src)) { throw "missing runtime DLL: $src" }
        Copy-Item -LiteralPath $src -Destination $release
        Log ("  {0,-30} {1,12:N0} B" -f $f, (Get-Item -LiteralPath $src).Length)
    }

    # --- the game --------------------------------------------------------------
    Log ''
    Log '--- zombie_farm_ipa\ ---'
    $ipaSrc = Join-Path $Root "zombie_farm_ipa\$ipaName"
    if (-not (Test-Path -LiteralPath $ipaSrc)) { throw "missing IPA: $ipaSrc" }
    Copy-Item -LiteralPath $ipaSrc -Destination (Join-Path $release 'zombie_farm_ipa')
    Log ("  zombie_farm_ipa\{0}" -f $ipaName)
    Log ("  {0,12:N0} B" -f (Get-Item -LiteralPath $ipaSrc).Length)

    # --- a fresh, empty sandbox -------------------------------------------------
    # Never seed a release with a save from the development machine. The game will
    # create a new profile and save after the player enters it for the first time.
    Log ''
    Log '--- sandbox ---'
    $sandbox = Join-Path $hleDir 'touchHLE_sandbox'
    New-Item -ItemType Directory -Force -Path $sandbox | Out-Null
    Log '  empty; the game will create a save after the player enters'

    # --- a short readme for the recipient --------------------------------------
    # Single self-contained HTML page (inline CSS, no external deps, system fonts)
    # so it opens in any browser by double-click. Written with a UTF-8 BOM so the
    # Chinese text renders correctly regardless of the system's default encoding.
    Log ''
    Log '--- 使用说明.html ---'
    $readme = @'
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zombie Farm 中文版 —— 使用说明</title>
<style>
  :root {
    --accent: #5b8c5a;
    --accent-soft: #eef4ee;
    --ink: #2c2c2c;
    --ink-dim: #666;
    --line: #e0e0e0;
    --code-bg: #f4f4f0;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: #fafaf7;
    color: var(--ink);
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    line-height: 1.75;
    font-size: 15.5px;
  }
  .page { max-width: 760px; margin: 0 auto; padding: 48px 28px 64px; }
  header {
    border-bottom: 3px solid var(--accent);
    padding-bottom: 18px;
    margin-bottom: 32px;
  }
  h1 { font-size: 26px; margin: 0 0 6px; }
  header .sub { color: var(--ink-dim); font-size: 14px; }
  h2 {
    font-size: 19px;
    margin: 40px 0 12px;
    padding-left: 12px;
    border-left: 4px solid var(--accent);
  }
  h3 { font-size: 16px; margin: 26px 0 8px; color: #3c5c3c; }
  p { margin: 10px 0; }
  ul { margin: 10px 0; padding-left: 24px; }
  li { margin: 4px 0; }
  code {
    background: var(--code-bg);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 1px 6px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 0.92em;
    word-break: break-all;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 14.5px;
  }
  th, td {
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--line);
    vertical-align: top;
  }
  th { background: var(--accent-soft); }
  td:first-child { white-space: nowrap; font-family: Consolas, monospace; font-size: 13.5px; }
  .tip {
    background: var(--accent-soft);
    border-left: 4px solid var(--accent);
    border-radius: 0 6px 6px 0;
    padding: 10px 16px;
    margin: 14px 0;
  }
  .warn {
    background: #fdf3e7;
    border-left: 4px solid #d9a45b;
    border-radius: 0 6px 6px 0;
    padding: 10px 16px;
    margin: 14px 0;
  }
  footer {
    margin-top: 48px;
    padding-top: 16px;
    border-top: 1px solid var(--line);
    color: var(--ink-dim);
    font-size: 13.5px;
  }
  a { color: var(--accent); }
</style>
</head>
<body>
<div class="page">

<header>
  <h1>Zombie Farm 中文版</h1>
  <div class="sub">运行说明 · 双击「游戏管理.exe」开始</div>
</header>

<div class="warn" style="border-left:4px solid #c8892f;background:#fdf6e8;">
<strong>本软件完全免费、开源。</strong>
官方地址：<a href="https://github.com/Ashena1017/zombie-farm-touchhle-cn">github.com/Ashena1017/zombie-farm-touchhle-cn</a><br>
交流群：QQ 1185712984<br>
如果你是通过付款拿到这个压缩包的，请尽快向卖家申请退款，并向平台举报那条商品 —— 你买到的只是一份可以免费下载的公开文件。
本项目不通过任何中间渠道销售，也不对转卖渠道提供任何支持。
</div>

<h2>一、怎么玩</h2>
<p>双击 <code>游戏管理.exe</code>，点「启动游戏」即可。窗口标题栏是「Zombie Farm 游戏管理」，里面可以：</p>
<ul>
  <li>切换游戏版本（IPA）</li>
  <li>改帧率（30 / 60 / 90 / 120 / 不限 / 自定义）</li>
  <li>改窗口大小（iPhone 或 iPad 尺寸，以及放大倍数）</li>
  <li>改滚轮缩放倍率</li>
  <li>全屏 / 窗口模式</li>
  <li>改金币和脑子</li>
  <li>备份、还原、删除存档</li>
  <li>在「外观」里选择浅色、深色、跟随系统，或自定义强调色</li>
</ul>
<div class="tip">设置改完立刻生效，不用点保存。</div>
<p>每次打开管理器都会显示「免费开源声明」，点击「我知道了」即可进入。后台会核对模拟器和内置 IPA；
如提示文件缺失或与官方发布不一致，可在「文件校验」查看具体文件并从项目主页重新下载。</p>

<h2>二、设置都是什么意思</h2>
<p>管理器里每个设置右边都有一个下拉框，下面逐项说明。这一页就是原来的「?」按钮里
的内容，所以界面上不再有问号。</p>

<h3>游戏帧率</h3>
<ul>
  <li><strong>30 帧</strong> — 最省电，但画面较顿。</li>
  <li><strong>60 帧</strong> — 推荐，与原版 iPhone 一致（原版是 60Hz 加垂直同步）。</li>
  <li><strong>90 帧</strong> — 折中。</li>
  <li><strong>120 帧</strong> — 更顺滑，显卡占用更高。</li>
  <li><strong>不限帧</strong> — 不推荐，实测会跑到约 1900 帧，只是白耗电发热。</li>
  <li><strong>自定义</strong> — 在右边的数字框里填 1 到 1000 之间的任意帧率。</li>
</ul>
<div class="tip">提高帧率不会让游戏里的时间走得更快。游戏用真实时间计算每帧间隔，所以帧率只影响
画面流畅度，作物生长、僵尸行为等仍按真实时间推进。</div>

<h3>滚轮缩放倍率</h3>
<p>鼠标滚轮每滚一格，农场地图缩放多少。<strong>默认 1.1</strong>。</p>
<p>滚轮驱动的是游戏自己的缩放方法（和它的双指捏合是同一个），所以数值越大，每格缩放得
越多。它是<strong>乘法</strong>而不是加法：1.1 表示每格把当前倍率乘以 1.1，因此在任何
缩放级别下手感都一样。</p>
<ul>
  <li><strong>1.1</strong> — 默认；从 1.0 放大到上限 2.0 约需 8 格。</li>
  <li><strong>1.2</strong> — 每格更快。</li>
  <li><strong>1.5</strong> — 每格跨度很大，适合快速拉近拉远。</li>
  <li><strong>自定义</strong> — 填 1.01 到 2.00 之间的任意值。</li>
</ul>
<p>可填范围是 1.01 到 2.00：1.00 及以下等于没缩放（或方向相反），2.00 以上一格就会跨过
游戏整个 0.2–2.0 的缩放范围。</p>
<div class="tip">滚轮上滚放大、下滚缩小，这个方向不可改；能改的是每格的幅度。</div>

<h3>窗口大小 / 分辨率</h3>
<p>这一行有<strong>两个下拉框</strong>，行尾会实时显示这样组合出来的窗口尺寸。</p>
<p><strong>左边选设备</strong>：</p>
<ul>
  <li><strong>iPad（平板）768 × 1024</strong> — 推荐。界面宽松，放大后排布依然正常。</li>
  <li><strong>iPhone（手机）480 × 320</strong> — 原版手机界面。放大后 logo 会偏小、
      状态栏会显得拥挤（实测），仅在想对照原版时使用。</li>
</ul>
<p><strong>右边选放大倍数</strong>，窗口大小 = 左边选的原生尺寸 × 这个倍数：</p>
<table>
  <tr><th>倍数</th><th>iPad 时窗口</th><th>说明</th></tr>
  <tr><td>×1.25</td><td>1280 × 960</td><td>最省性能</td></tr>
  <tr><td>×1.5</td><td>1536 × 1152</td><td><strong>默认，推荐</strong>；1080p 级别，也放得进 2560×1440 屏幕</td></tr>
  <tr><td>×1.75</td><td>1792 × 1344</td><td>更清晰，但更大更吃显卡</td></tr>
  <tr><td>自定义</td><td>—</td><td>自己填倍数，可填小数（<code>4.5</code>）或分数（<code>9/2</code>），范围 1.00–6.00；高倍率需要更多显存</td></tr>
</table>
<p>为什么倍数是小数而不是整数一倍两倍：iPad 原生的 1024×768 整数倍只有 ×1
（1024×768）和 ×2（2048×1536），而 ×2 的外框约 2070×1592，<strong>放不进 1440 高的
屏幕</strong> —— 中间是空的，所以需要 ×1.5 这样的中间倍数。</p>
<div class="warn">
不要把「模拟屏幕」本身调大。这个游戏是<strong>固定分辨率</strong>的：界面按「点」排版，
图片素材也是固定大小（最大的图只有 1024×768）。把模拟屏幕调大会让游戏拿到一块更大的画布，
它仍然按原来的点数画小界面，再把背景拉满，于是画面出现「拉扯」、UI 变小、底部状态栏被挤出
屏幕。<strong>正确做法是保持模拟屏幕为原生尺寸，只用放大倍数放大窗口</strong> ——
界面比例不变，只是整体变大。管理器已经只暴露倍数，所以照上面选就行。
</div>
<div class="tip">放大只是让画面变大变清楚，<strong>不会增加素材细节</strong> —— 游戏的图
本身就是 1024×768 级别的，放大到 1.5 倍以上会开始发虚。</div>
<p>窗口本身不能拖动缩放（touchHLE 的窗口模式没有开启可调整大小）。</p>

<h3>显示模式</h3>
<ul>
  <li><strong>窗口模式</strong> — 推荐，便于随时切回桌面。</li>
  <li><strong>全屏</strong> — 把画面拉伸铺满屏幕，按显示器的分辨率显示。</li>
</ul>
<p>全屏后想退出，按 <code>Alt+Enter</code> 或 <code>Alt+F4</code>。</p>

<h3>高速帧率修复</h3>
<p>修复 touchHLE 把「零超时 run loop 调用」当成阻塞调用的问题。</p>
<p>Zombie Farm 用的是 cocos2d 的 CCFastDirector，它每帧要调用两次
<code>CFRunLoopRunInMode(超时=0)</code>。真实 iPhone 上超时为 0 表示「不阻塞、立刻返回」，
但 touchHLE 会跑完整一圈并睡 16 毫秒，每帧因此付出 2×16 毫秒，帧率被压到 30。</p>
<div class="warn"><strong>Zombie Farm 必须选「开启」</strong>，关了就只有 30 帧。</div>

<h2>三、文件夹里都是什么</h2>
<table>
  <tr><th>文件 / 文件夹</th><th>作用</th></tr>
  <tr><td>游戏管理.exe</td><td>双击这个启动管理器</td></tr>
  <tr><td>GameManager.ps1、ManagerWorker.ps1</td><td>管理器读写游戏设置、存档和备份时使用的后台脚本，请与 EXE 一起保留</td></tr>
  <tr><td>compat\WinForms.ps1</td><td>电脑缺少 WebView2 时使用的兼容界面</td></tr>
  <tr><td>*.dll</td><td>C++ 运行库</td></tr>
  <tr><td>zombie_farm_ipa\</td><td>游戏本体（IPA 文件放这里）</td></tr>
  <tr><td>touchHLE\</td><td>模拟器本体，不用管它</td></tr>
  <tr><td>使用说明.html</td><td>本文件</td></tr>
  <tr><td>请勿购买.txt</td><td>免费声明与官方地址，内容与本文顶部相同</td></tr>
  <tr><td>校验.bat</td><td>双击核对文件有没有被改过（用系统自带的 certutil，不联网、不改文件）</td></tr>
  <tr><td>SHA256SUMS.txt</td><td>包内每个文件的 SHA-256，可手动或脚本核对</td></tr>
</table>
<p>想换游戏版本，可以把其他 <code>.ipa</code> 加进 <code>zombie_farm_ipa\</code>，在管理器的「游戏版本 (IPA)」里选择。请保留原有的内置 IPA。它缺失或内容发生变化时，管理器会提示安装包可能是改版。</p>

<h2>四、想跳过游戏时间</h2>
<p>「游戏启动」页显示当前模拟时间。点「快进并启动」，分别填小时和分钟（例如 6 小时 15 分），确认预览显示的快进后时间，再启动游戏。快进会累加，下次启动继续使用累计值。要清除累计值并回到当前时间，点「重置为当前时间」。</p>
<p>「新增备份」会同时记录当时的游戏存档和累计跳过时间；恢复备份后，两者都会回到备份时的状态。旧版管理器创建的备份没有时间记录，恢复时只还原存档，并保留当前累计时间。</p>

<h2>五、存档在哪</h2>
<p>首次进入游戏后会在 <code>touchHLE\touchHLE_sandbox</code> 中创建新的玩家存档；交付包不预置任何人物进度。</p>
<div class="warn">删除它就会重新开始。建议先用管理器里的「新增备份」存一份，出问题随时能还原。</div>

<h2>六、电脑要求</h2>
<ul>
  <li>Windows 10 / 11 64 位</li>
  <li>新版管理界面使用 Microsoft Edge WebView2 运行时。系统缺少该组件时会打开兼容界面。</li>
  <li>支持 OpenGL 的显卡（近十年的集显或独显都可以）</li>
</ul>

<h2>七、性能与清晰度小抄</h2>
<table>
  <tr><th>想要</th><th>怎么选</th></tr>
  <tr><td>最省电 / 老机器</td><td>帧率 30，倍数 ×1.25</td></tr>
  <tr><td>平衡（推荐）</td><td>帧率 60，倍数 ×1.5</td></tr>
  <tr><td>画面最大</td><td>帧率 60，倍数 ×1.75 或自定义（注意别超过屏幕）</td></tr>
  <tr><td>铺满屏幕</td><td>显示模式选「全屏」</td></tr>
</table>
<div class="tip">窗口越大、帧率越高，显卡占用越高。这台机器上 ×1.5 是 1536×1152，已经相当于
1080p 级别。</div>

<footer>
  <p>本项目仅为个人学习与怀旧用途，游戏版权归原作者所有。<br>
  touchHLE 是开源项目（Mozilla Public License 2.0）：<a href="https://touchhle.org/">https://touchhle.org/</a></p>
</footer>

</div>
</body>
</html>
'@
    [System.IO.File]::WriteAllText((Join-Path $release '使用说明.html'), $readme,
        (New-Object System.Text.UTF8Encoding($true)))
    Log '  written'

    # --- a plain-text copy of the free statement ------------------------------
    # The HTML page covers anyone who opens it; this file exists so the statement is
    # readable without a browser, is trivially greppable, and travels with the zip
    # even if the folder is re-packed by a reseller who drops the HTML.
    Log ''
    Log '--- 请勿购买.txt ---'
    $noticeSrc = Join-Path $windowsDir '请勿购买.txt'
    if (-not (Test-Path -LiteralPath $noticeSrc)) { throw "missing: $noticeSrc" }
    Copy-Item -LiteralPath $noticeSrc -Destination $release
    Log ("  {0,-30} {1,12:N0} B" -f '请勿购买.txt', (Get-Item -LiteralPath $noticeSrc).Length)

    # Also carry the licenses, since third-party components are redistributed. They go
    # beside touchHLE.exe because they cover the emulator and its dylibs.
    # Dst is already a full path, so it must NOT be joined onto $release again.
    foreach ($pair in @(
        @{ Src = (Join-Path $Root 'touchHLE\LICENSE'); Dst = (Join-Path $hleDir 'LICENSE-touchHLE.txt') },
        @{ Src = (Join-Path $hleRoot 'touchHLE_dylibs\COPYING.libgcc'); Dst = (Join-Path $hleDir 'COPYING.libgcc') },
        @{ Src = (Join-Path $hleRoot 'touchHLE_dylibs\COPYING.libstdcxx'); Dst = (Join-Path $hleDir 'COPYING.libstdcxx') },
        @{ Src = (Join-Path $hleRoot 'touchHLE_dylibs\COPYING.libz'); Dst = (Join-Path $hleDir 'COPYING.libz') }
    )) {
        if (Test-Path -LiteralPath $pair.Src) {
            Copy-Item -LiteralPath $pair.Src -Destination $pair.Dst
        }
    }
    Log '  licenses copied'

    # --- fingerprints -----------------------------------------------------------
    # Check the staged files against the same pins the bundled manager reads.
    Log ''
    Log '--- pinned hashes (GameManager.ps1 vs the files being packaged) ---'
    & (Join-Path $PSScriptRoot '_check_pinned_hashes.ps1') `
        -ManagerPath (Join-Path $release 'GameManager.ps1') `
        -RequireManagerPins -ManifestPath (Join-Path $release 'release.json') `
        -ExePath (Join-Path $hleDir 'touchHLE.exe') `
        -IpaPath (Join-Path (Join-Path $release 'zombie_farm_ipa') $ipaName)
    if ($LASTEXITCODE -ne 0) {
        throw 'The staged files do not match the pinned executable and release IPA.'
    }

    . (Join-Path $PSScriptRoot '_file_hash.ps1')

    # --- 校验.bat: check the files without trusting the manager ----------------
    #
    # Publishing a hash only helps if checking it is easy. The manager shows the
    # numbers, but whoever hands over the folder also hands over the manager; this
    # script hashes the files itself with certutil, which ships with Windows, and
    # says which ones do not match.
    #
    # Switch code pages on an ASCII line before cmd.exe reads the Unicode IPA name.
    Log ''
    Log '--- 校验.bat ---'
    $checkTargets = @(
        @{ Rel = 'touchHLE\touchHLE.exe';                 File = (Join-Path $hleDir 'touchHLE.exe') },
        @{ Rel = ('zombie_farm_ipa\' + $ipaName);         File = (Join-Path (Join-Path $release 'zombie_farm_ipa') $ipaName) },
        @{ Rel = 'GameManager.ps1';                       File = (Join-Path $release 'GameManager.ps1') },
        @{ Rel = 'ManagerWorker.ps1';                     File = (Join-Path $release 'ManagerWorker.ps1') },
        @{ Rel = 'compat\WinForms.ps1';                  File = (Join-Path $release 'compat\WinForms.ps1') },
        @{ Rel = 'release.json';                          File = (Join-Path $release 'release.json') },
        @{ Rel = '游戏管理.exe';                          File = (Join-Path $release '游戏管理.exe') },
        @{ Rel = '请勿购买.txt';                          File = (Join-Path $release '请勿购买.txt') }
    )

    $bat = New-Object System.Collections.Generic.List[string]
    foreach ($line in @(
        '@echo off',
        'chcp 65001 >nul',
        'setlocal enabledelayedexpansion',
        'cd /d "%~dp0"',
        'set "FAILS=0"',
        'echo.',
        'echo   Zombie Farm 中文版 - 文件校验',
        'echo   只读取文件、计算 SHA-256，不会改动任何东西。',
        'echo.'
    )) { $bat.Add($line) }

    foreach ($target in $checkTargets) {
        $bat.Add(('call :check "{0}" "{1}"' -f $target.Rel, (Get-Sha256Hex $target.File)))
    }

    foreach ($line in @(
        'echo.',
        'if "!FAILS!"=="0" (',
        '  echo   全部通过：这些文件和官方发布的一致。',
        ') else (',
        '  echo   有 !FAILS! 个文件对不上，可能被替换或被改过。',
        '  echo   请从官方地址重新下载：https://github.com/Ashena1017/zombie-farm-touchhle-cn',
        ')',
        'echo.',
        'pause',
        'exit /b 0',
        '',
        ':check',
        'set "FILE=%~1"',
        'set "EXPECT=%~2"',
        'if not exist "%FILE%" (',
        '  echo   [MISS] %FILE%',
        '  set /a FAILS+=1',
        '  exit /b',
        ')',
        'set "ACTUAL="',
        'for /f "skip=1 delims=" %%H in (''certutil -hashfile "%FILE%" SHA256 2^>nul'') do (',
        '  if not defined ACTUAL set "ACTUAL=%%H"',
        ')',
        'set "ACTUAL=!ACTUAL: =!"',
        'if /i "!ACTUAL!"=="!EXPECT!" (',
        '  echo   [ OK ] %FILE%',
        ') else (',
        '  echo   [FAIL] %FILE%',
        '  echo          期望 !EXPECT!',
        '  echo          实际 !ACTUAL!',
        '  set /a FAILS+=1',
        ')',
        'exit /b'
    )) { $bat.Add($line) }

    [System.IO.File]::WriteAllLines((Join-Path $release '校验.bat'), $bat,
        (New-Object System.Text.UTF8Encoding($false)))
    Log ("  {0,-30} {1,12:N0} B" -f '校验.bat', (Get-Item -LiteralPath (Join-Path $release '校验.bat')).Length)

    # --- SHA256SUMS.txt ---------------------------------------------------------
    # Every file in the bundle except itself, in `sha256sum -c` format. The .bat
    # above covers the five files that matter for "was this tampered with"; this is
    # the complete list, for anyone who wants to check all 45.
    Log ''
    Log '--- SHA256SUMS.txt ---'
    $sums = New-Object System.Collections.Generic.List[string]
    Get-ChildItem -LiteralPath $release -Recurse -File |
        Where-Object { $_.Name -ne 'SHA256SUMS.txt' } |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($release.Length + 1)
            $sums.Add(('{0}  {1}' -f (Get-Sha256Hex $_.FullName), $relative))
        }
    [System.IO.File]::WriteAllLines((Join-Path $release 'SHA256SUMS.txt'), $sums,
        (New-Object System.Text.UTF8Encoding($false)))
    Log ("  {0,-30} {1,3} entries" -f 'SHA256SUMS.txt', $sums.Count)

    # --- summary ---------------------------------------------------------------
    Log ''
    Log '--- bundle ---'
    $total = (Get-ChildItem -LiteralPath $release -Recurse -File |
        Measure-Object -Property Length -Sum).Sum
    $files = (Get-ChildItem -LiteralPath $release -Recurse -File | Measure-Object).Count
    Log ("  {0} files, {1:N1} MB" -f $files, ($total / 1MB))
    Log ''
    Get-ChildItem -LiteralPath $release | Sort-Object PSIsContainer, Name | ForEach-Object {
        $kind = if ($_.PSIsContainer) { 'DIR ' } else { 'FILE' }
        Log ("  {0} {1}" -f $kind, $_.Name)
    }
    Log ''
    # Preserve the one top-level directory and the empty touchHLE_sandbox.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory(
        $release, $archive, [IO.Compression.CompressionLevel]::Optimal, $true)

    if (-not $SkipVerify) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot '_verify_release.ps1') -ZipPath $archive
        if ($LASTEXITCODE -ne 0) { throw 'The Windows ZIP did not pass standalone verification.' }
    }

    if (Test-Path -LiteralPath $output -PathType Leaf) {
        [IO.File]::Replace($archive, $output, [NullString]::Value)
    } else {
        [IO.File]::Move($archive, $output)
    }
    Log "Built Windows ZIP: $output"
}
finally {
    $resolved = (Resolve-Path -LiteralPath $stage).Path
    $parent = (Resolve-Path -LiteralPath $outputDir).Path
    if ((Split-Path -Parent $resolved) -ne $parent -or (Split-Path -Leaf $resolved) -notmatch '^\.package-[a-f0-9]{32}$') {
        throw "Unexpected packaging directory: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
