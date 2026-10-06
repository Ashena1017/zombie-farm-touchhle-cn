# Build the playable Release folder.
#
# What goes in is decided by measurement, not by guessing:
#   * touchHLE.exe's real imports come from `dumpbin /dependents`, which showed
#     only 3 non-system DLLs: MSVCP140, VCRUNTIME140, VCRUNTIME140_1
#   * the resource folders touchHLE looks for at runtime are named in
#     src/paths.rs: touchHLE_dylibs, touchHLE_fonts, touchHLE_sandbox,
#     touchHLE_options.txt, touchHLE_default_options.txt
#   * the IPA itself, since the game is not inside the emulator
#
# Deliberately EXCLUDED:
#   * zfrpatch_current.dylib -- the game ships its own copy inside the IPA
#     (Payload/ZFR.app/Frameworks/zfrpatch.dylib), and nothing in the launcher
#     references the loose file
#   * every other version of the IPA -- shipping one avoids the "which version do
#     I pick?" problem entirely, and the picker falls back to whatever it finds
#   * touchHLE_fork.exe, backups, logs, _analysis, _build_tools, tools, the two
#     source trees, and the development helper scripts
#
# Verified afterwards by launching the copy in place.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [switch]$SkipVerify
)
$root = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}


$ErrorActionPreference = 'Stop'

$release = Join-Path $Root 'Release'
$ipaName = 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'

function Log([string]$m) { Write-Host $m }

# --- start clean ------------------------------------------------------------
if (Test-Path -LiteralPath $release) {
    Log "clearing $release"
    Remove-Item -LiteralPath $release -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $release | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $release 'zombie_farm_ipa') | Out-Null

# Layout:
#
#   Release\
#   ├── 游戏管理.exe / GameManager.ps1   the manager and its runtime DLLs
#   ├── MSVCP140.dll / VCRUNTIME140*.dll
#   ├── zombie_farm_ipa\                     the game(s)
#   ├── 使用说明.html
#   └── touchHLE\                        everything belonging to the emulator
#       ├── touchHLE.exe
#       ├── touchHLE_dylibs\  touchHLE_fonts\  touchHLE_sandbox\
#       └── touchHLE_options.txt  touchHLE_default_options.txt
#
# The emulator is kept in its own folder on request, which is safe because
# touchHLE resolves its resources from the CURRENT DIRECTORY (src/paths.rs returns
# Path::new(".") on Windows), not from the executable's location -- and the manager
# sets that directory explicitly. Verified: running with the working directory left
# one level up panics with
#   Unexpected I/O failure ... "touchHLE_dylibs/libz.1.2.3.dylib"
$hleDir = Join-Path $release 'touchHLE'
New-Item -ItemType Directory -Force -Path $hleDir | Out-Null

# --- the emulator, in its own folder ---------------------------------------
Log ''
Log '--- touchHLE\ ---'
foreach ($f in @('touchHLE.exe', 'touchHLE_default_options.txt', 'touchHLE_options.txt')) {
    $src = Join-Path $hleRoot $f
    if (-not (Test-Path -LiteralPath $src)) { throw "missing: $src" }
    Copy-Item -LiteralPath $src -Destination $hleDir
    Log ("  {0,-30} {1,12:N0} B" -f $f, (Get-Item -LiteralPath $src).Length)
}
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
foreach ($f in @('游戏管理.exe', 'GameManager.ps1')) {
    $src = Join-Path $Root $f
    if (-not (Test-Path -LiteralPath $src)) { throw "missing: $src" }
    Copy-Item -LiteralPath $src -Destination $release
    Log ("  {0,-30} {1,12:N0} B" -f $f, (Get-Item -LiteralPath $src).Length)
}
Log '  (GameManager.ps1 is required: the .exe is only a stub that runs it)'

# --- the non-system DLLs the exe actually imports ---------------------------
# From dumpbin /dependents. Without these the exe will not start on a machine that
# lacks the VC++ 2015-2022 redistributable. touchHLE.exe imports the same ones.
Log ''
Log '--- required VC++ runtime DLLs (top level) ---'
foreach ($f in @('MSVCP140.dll', 'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll')) {
    $src = Join-Path $Root $f
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

# --- a fresh sandbox with the reference save -------------------------------
# Empty apart from the save folder, so the game starts from a clean profile. The
# user's own saves are NOT included; only a starting save is.
Log ''
Log '--- sandbox ---'
$sandboxDocs = Join-Path $hleDir 'touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents'
New-Item -ItemType Directory -Force -Path $sandboxDocs | Out-Null

$refSave = Join-Path $hleRoot 'touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents\saveGame.bin2'
if (Test-Path -LiteralPath $refSave) {
    Copy-Item -LiteralPath $refSave -Destination (Join-Path $sandboxDocs 'saveGame.bin2')
    Log ("  starting save included ({0:N0} B)" -f (Get-Item -LiteralPath $refSave).Length)
} else {
    Log '  no starting save found; the game will create one'
}

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
</ul>
<div class="tip">设置改完立刻生效，不用点保存。</div>

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
  <tr><td>自定义</td><td>—</td><td>自己填倍数，可填小数（<code>1.6</code>）或分数（<code>7/4</code>），范围 1.00–3.00</td></tr>
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
  <tr><td>GameManager.ps1</td><td>管理器的本体（exe 只是启动壳，别删）</td></tr>
  <tr><td>*.dll</td><td>C++ 运行库</td></tr>
  <tr><td>zombie_farm_ipa\</td><td>游戏本体（IPA 文件放这里）</td></tr>
  <tr><td>touchHLE\</td><td>模拟器本体，不用管它</td></tr>
  <tr><td>使用说明.html</td><td>本文件</td></tr>
</table>
<p>想换游戏版本，就把别的 <code>.ipa</code> 放进 <code>zombie_farm_ipa\</code>，然后在管理器的「游戏版本 (IPA)」里选。</p>

<h2>四、想跳过游戏时间</h2>
<p>在管理器里点「启动并跳过时间…」，填 <code>HH:MM</code>（例如 <code>6:15</code> 就是快进 6 小时 15 分）。时间会累加，下次启动继续往后走。</p>
<p>「新增备份」会同时记录当时的游戏存档和累计跳过时间；恢复备份后，两者都会回到备份时的状态。旧版管理器创建的备份没有时间记录，恢复时只还原存档，并保留当前累计时间。</p>

<h2>五、存档在哪</h2>
<p><code>touchHLE\touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents\saveGame.bin2</code></p>
<div class="warn">删除它就会重新开始。建议先用管理器里的「新增备份」存一份，出问题随时能还原。</div>

<h2>六、电脑要求</h2>
<ul>
  <li>Windows 10 / 11 64 位</li>
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

# Also carry the licenses, since third-party components are redistributed. They go
# beside touchHLE.exe because they cover the emulator and its dylibs.
# Dst is already a full path, so it must NOT be joined onto $release again.
foreach ($pair in @(
    @{ Src = (Join-Path $hleRoot 'LICENSE'); Dst = (Join-Path $hleDir 'LICENSE-touchHLE.txt') },
    @{ Src = (Join-Path $hleRoot 'touchHLE_dylibs\COPYING.libgcc'); Dst = (Join-Path $hleDir 'COPYING.libgcc') },
    @{ Src = (Join-Path $hleRoot 'touchHLE_dylibs\COPYING.libstdcxx'); Dst = (Join-Path $hleDir 'COPYING.libstdcxx') },
    @{ Src = (Join-Path $hleRoot 'touchHLE_dylibs\COPYING.libz'); Dst = (Join-Path $hleDir 'COPYING.libz') }
)) {
    if (Test-Path -LiteralPath $pair.Src) {
        Copy-Item -LiteralPath $pair.Src -Destination $pair.Dst
    }
}
Log '  licenses copied'

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
Log "DONE: $release"
