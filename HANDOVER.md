# 项目交接（供新会话使用）

> **写于 2026-09-23**。本会话过长，新会话从这里接手。
> 先读完本文件，再按需查 `TECHNICAL.md`（技术细节）与 `process.md`（历代改动流水账）。
> **回复一律用中文**（标识符、路径、地址、字节保持原样不翻译）。

---

## 0. 一句话现状

**Zombie Farm 中文版已经做完并可用。** touchHLE 的 ZFR 专用 fork + 图形化管理器
`游戏管理.exe` + 交付包 `Release\` 都是绿的，主人正在实机使用。

当前会话最后两件事也都已完成并验证：
1. 给管理器加了「窗口大小/分辨率」（左选 iPad/iPhone，右选小数倍率）与「滚轮缩放倍率」两项设置；
2. 去掉界面上所有 `?` 按钮（说明搬进 `使用说明.html`）、倍率预置改成小数 ×1.25 / ×1.5 / ×1.75；
3. 清理了 126 MB 过往会话记录与过程性产物，并重写了文档。

**Windows 版本没有未完成的阻塞项，正在等主人实机反馈。** 2026-10-06 Windows 存档备份已扩展为同时恢复累计跳过时间，旧备份兼容性保留；Android ARM64 已完成 MuMu 黑屏、形象页裁剪、沉浸式全屏修复，并新增「ZF游戏管理」原生管理器。Windows 备份细节见 §20；Android 管理器最终 APK、MuMu 启动/存档复原结果与验证边界见 §19。

---

## 1. 目录结构（当前实际状态）

```
touchHLE-zombiefarm/
├── TECHNICAL.md                  ★ 主文档：技术细节 + 血泪教训（11 章，最大的文件）
├── process.md                 ★ 历代改动流水账，一行一个批次（最新 #30）
├── HANDOVER.md                本文件
├── 交接提示词.md              给新会话的开场提示词（复制粘贴用）
├── 游戏管理.exe / GameManager.ps1   ★ 图形管理器（唯一入口，双击 exe）
├── launcher_selected_ipa.txt  记住上次选的 IPA（运行时状态）
├── launcher_skip_memory.txt   记住上次快进时长（运行时状态，可能不存在）
├── StartZombieFarmNextHour.ps1 / RestoreTestSave.ps1 / SetZombieFarmCurrency.ps1
│                              命令行辅助脚本（管理器不依赖它们，但保留可用）
├── 运行游戏.bat / 选择跳过时间并启动.bat / 使用教程.txt
├── MSVCP140.dll / VCRUNTIME140*.dll        VC++ 运行库（管理器需要）
├── zombie_farm_ipa/           IPA 谱系（63 个文件 / 1.8 GB）
├── tools/                     ★ 活代码：patcher + 反汇编基础设施（46 + 4 模块）
├── _analysis/                 ★ 分析/验证脚本 + 精简后的历史产物（见其 TECHNICAL.md）
├── Release/                   ★ 交付包（构建产物，由 _build_release.ps1 生成）
├── touchHLE-zombiefarm-android-arm64/ Android APK 输出（构建产物，不入库）
└── touchHLE/                  ★ 模拟器相关的一切
    ├── touchHLE.exe           当前运行的模拟器（= fork 构建）
    ├── touchHLE_fork.exe      构建输出（内容应与上面一致）
    ├── touchHLE.exe.backup-*  4 个可回滚的旧版 exe（见 README 二·五）
    ├── touchHLE_dylibs/  touchHLE_fonts/  touchHLE_sandbox/（存档在这里）
    ├── touchHLE_options.txt   ★ 管理器写的设置（每个 app id 一行）
    ├── touchHLE_default_options.txt  touchHLE_log.txt  zfr_last_run.log
    ├── touchHLE_time_offset_seconds.txt / zfrpatch_current.dylib / LICENSE
    ├── touchHLE-fork/         模拟器源码（上游 fa3d095 + 本项目适配）
    │   └── vendor/            构建依赖，**自包含**（曾是 junction，见 process.md #26）
    └── _build_tools/          自包含 rust/cmake 工具链 + cargo 缓存 + target-fork
```

**`touchHLE-trunk/` 已删除**（2026-09-23，主人的上游参考源码，含提示注入文件）。

---

## 2. 关键事实（改东西前必看）

### 2.1 路径与 app id

| 项 | 值 |
|---|---|
| 开发树模拟器 | `touchHLE\` （脚本用 `$hleRoot` 定位，**别硬编码**） |
| 当前 IPA | `zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa`（59,564,493 B） |
| 存档目录 | `touchHLE\touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents\saveGame.bin2` |
| 真实存档 | 金币 **140586** / 脑子 **4410** / 等级 40（**主人的真进度，测试绝不能污染**） |
| 当前 options 行 | `com.playforge.ZombieFarm.ZFR: --fps-limit=60 --zf-wheel-zoom-step=1.1 --device-family=ipad --scale-hack=1.5 --non-blocking-zero-timeout-run-loop` |

> ⚠️ `zombie_farm_ipa\` 里有 **3 个不同的 bundle id**。切换 IPA 会**同时切换设置行与存档目录**。
> 换默认 IPA 要改三处：`GameManager.ps1` 的 `Get-DefaultIpaPath` fallback、
> `launcher_selected_ipa.txt`、`_analysis\_build_release.ps1` 的 `$ipaName`。

### 2.2 二进制哈希（用于确认三方同步）

| 文件 | sha256 前缀 |
|---|---|
| `touchHLE\touchHLE.exe` | `75A0F9DD97BF0C27` |
| `touchHLE\touchHLE_fork.exe` | `75A0F9DD97BF0C27` |
| `Release\touchHLE\touchHLE.exe` | `75A0F9DD97BF0C27` |
| `GameManager.ps1` | `8A949E6742721E55` |
| `Release\GameManager.ps1` | `8A949E6742721E55` |
| v29fix IPA | `E5951F945D23E88F`（前 16 位） |

### 2.3 这台机器的环境坑（**踩过多次**）

- **`edit`/`write` 工具会剥掉 `.ps1` 的 BOM** → 改完含中文的 `.ps1` **必须**跑
  `_analysis\_ensure_bom.ps1`，否则 PowerShell 5.1 用 ANSI 码页解码，报一堆
  `'30 帧'` 之类莫名其妙的语法错误。
- **PowerShell 变量名大小写不敏感**：脚本作用域的 `$rowY` 与 `$script:RowY` 是**同一个变量**。
  曾因此把哈希表毁成整数。
- **PS 5.1 把弯引号 `“ ”` 当字符串定界符**（即使在双引号串里），字符串里只能用直引号 `'`。
- **`pwsh` 不在 PATH**，用 `powershell -NoProfile -ExecutionPolicy Bypass -File`。
- **`Start-Process` 在这台机器上崩**（`NO_PROXY`/`no_proxy` 重复键）→ 用
  `[System.Diagnostics.Process]::Start($psi)`。
- **`ProcessStartInfo.EnvironmentVariables` 在 PS 5.1 里是 null** → 先在同进程设 `$env:VAR` 让子进程继承。
- **桌面 2560×1440 @150%**：任何读窗口几何的脚本**必须先 `SetProcessDPIAware()`**，
  否则量到的值是真实值的 2/3，而且**自洽地错**（连未改动的档位也一起缩），极易误判成功能 bug。
- **不要用 `Select-String` 直接搜 `touchHLE\zfr_last_run.log`** —— 它是累积文件，
  要先切到最后一个 `CPU emulation begins now.` 之后那段。
- **`_gui_shot.ps1` 截图前要确认没有遗留的同名窗口**，否则会抓到旧会话留下的进程窗口
  （本会话就被这个骗过一次，以为改动没生效）。

### 2.4 别用 `Get-Content` 判断中文文件行数

`Get-Content` 不带 `-Encoding UTF8` 时按 **ANSI 码页**解码无 BOM 的 UTF-8 文件：
中文的尾字节会和紧随的 `0x0A` 粘成一个字符，**换行被吞掉，行数虚低**。
本会话实测：`process.md` 真实约 1050 行，`Get-Content` 只报 **726**（现为 727）；
`TECHNICAL.md` 真实约 1780 行，只报 **1100**。一度以为文件被截断，虚惊一场。

要正确读中文文件，任选其一：

```powershell
[System.IO.File]::ReadAllText($p, [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::ReadAllLines($p, [System.Text.UTF8Encoding]::new($false))
Get-Content $p -Encoding UTF8        # 也可以，但上面两个更明确
```

**判据**：行数明显偏低（比如按 `Write-Host` 次数估的应该更多）就是踩了这个坑，
而不是文件真的坏了。用 `[regex]::Matches($txt,"`n").Count` 复核。
（本文件不再写死这些行数 —— 每次编辑都会变，写死了就会过期。）

---

## 3. 常用工作流（照抄即可）

### 3.1 改管理器（`GameManager.ps1`）

```powershell
# 1. 改完先修 BOM + 全脚本 parse 检查
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_ensure_bom.ps1
# 2. 自检（设置读写 + 存档管理，不开界面）
powershell -NoProfile -ExecutionPolicy Bypass -File GameManager.ps1 -SelfTest
# 3. 无头改设置 / 看当前设置
powershell -NoProfile -ExecutionPolicy Bypass -File GameManager.ps1 -Set wheel_zoom=1.5
powershell -NoProfile -ExecutionPolicy Bypass -File GameManager.ps1 -ShowSettings
# 4. 同步到交付包（Release\GameManager.ps1 是副本！）
Copy-Item GameManager.ps1 Release\GameManager.ps1 -Force
```

### 3.2 改模拟器（`touchHLE\touchHLE-fork\src\`）

```powershell
# 增量构建（约 1m20s）
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_build_fork_now.ps1
# ⚠️ 它只产出 touchHLE_fork.exe，必须再复制两处：
Copy-Item touchHLE\touchHLE_fork.exe touchHLE\touchHLE.exe -Force
Copy-Item touchHLE\touchHLE_fork.exe Release\touchHLE\touchHLE.exe -Force
```

### 3.3 重建交付包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_build_release.ps1
# 它会先清空 Release\ 再重建，并在最后自检
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_verify_release.ps1
```

> `Release\使用说明.html` 是**构建产物**，内容在 `_build_release.ps1` 的内嵌模板里。
> 直接改 Release 会被下次构建覆盖。

### 3.4 完整验证套件（改完必跑）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_verify_layout.ps1         # 目录布局
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_verify_layout_match.ps1   # 与 Release 同构
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_device_size_roundtrip.ps1 # 设置读写+算术
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_verify_release.ps1        # 交付包能跑
powershell -NoProfile -ExecutionPolicy Bypass -File GameManager.ps1 -SelfTest
```

GUI 相关（每个约 1 分钟，会开界面）：

```powershell
_analysis\_gui_controls_test.ps1   # 驱动真实控件，验证设置落盘
_analysis\_res_order_check.ps1     # 读运行中 GUI 的下拉框内容与顺序
_analysis\_gui_tip_test.ps1        # 验证没有 ? 按钮，且说明书覆盖这些设置
```

窗口尺寸**实测**（会真的开 8 次游戏，约 3 分钟）：

```powershell
_analysis\_device_size_e2e.ps1
```

### 3.5 发 PR（`git-pr.mjs`，Gitee / GitHub 通用）

脚本：`C:\Users\Loner\.dsh\tools\git-pr.mjs`（零依赖，只用 Node 内置模块）。
**默认是预演，加了 `--apply` 才真动手** —— 这个设计是刻意的，别绕过它。

```powershell
# 0. 先确认 git 身份（新克隆的仓库必然没有；用仓库本地配置，不要 --global）
git config user.name; git config user.email
git config user.name "Lonerwcq"; git config user.email "754663659@qq.com"

# 1. 预演：只检查权限与分支，不推送、不开 PR
node "$env:USERPROFILE\.dsh\tools\git-pr.mjs" --repo <本地仓库路径> --branch <分支> --title "<标题>"

# 2. 真提交：推 fork → 开 PR → 回读文件清单（幂等，可重复运行）
node "$env:USERPROFILE\.dsh\tools\git-pr.mjs" --repo <本地仓库路径> --branch <分支> `
  --title "<标题>" --body-file <PR描述.md> --base main --apply
```

**四条必守规则：**

1. **GitHub 上必须显式传 `--base main`** —— 脚本的 `--base` 默认是 `master`，
   而 GitHub 仓库默认分支是 `main`；不传就会以不存在的 `master` 为目标去建 PR，
   **必然失败**（脚本会把它当 `HTTP 4xx` 抛出）。先查准：
   `git -C <仓库> remote show origin | Select-String 'HEAD branch'`。
   本仓库 `zombie-farm-touchhle-cn` 是例外，它的默认分支**就是 `master`**。
2. **目标必须是自己的 fork，不是上游**。上游一般 `permission.push = false`，
   直推 `origin` 必然 **403** —— 403 的根因几乎总是「推错仓库」，不是令牌无效。
   脚本会先探测上游权限、不可推时自动改用 fork。
3. **分支必须与当前 HEAD 一致**（脚本会校验），且**基线要基于上游默认分支的最新 HEAD**
   （先 `git fetch`），否则会把上游较新的提交一起带进 PR，看起来像在回退别人的工作。
4. **脚本只认文档里列出的参数，未知参数直接报错**（同样是刻意的）——
   别自己发明 `--force` 之类的参数，否则「以为在预演、其实已经推送并开了 PR」。

**注意本仓库不需要走这条路**：`zombie-farm-touchhle-cn` 就是主人自己的仓库
（origin = `Ashena1017/zombie-farm-touchhle-cn`），直接 `git push origin master` 即可。
`git-pr.mjs` 是给**往别人的仓库提 PR** 用的（例如给上游 touchHLE 提改动、
或给 `actualdoctornerd-ai/Zombie-Farm-2-Reforged` 提 PR）。

**令牌与安全**：令牌由脚本从 Windows 凭据管理器自动读取（GitHub / Gitee 都已存在，
不需要主人做任何事）。**绝不打印令牌值**，不写进文件、不 `echo`、不贴进会话。
自己写 PowerShell 取令牌时有个静默陷阱：`git credential fill` 返回的是**字符串数组**，
`$x.Length` 是**元素个数**而不是字符数（40 字符的令牌会显示成 `4`），必须先 join 再解析：

```powershell
$raw = (("protocol=https`nhost=github.com`n`n" | git credential fill 2>$null) -join "`n")
$tok = (($raw -split "`n") | Where-Object { $_ -like 'password=*' }) -replace '^password=', ''
if (-not $tok) { throw '未取到令牌' }   # 别把空值带进后续请求
```

### 3.6 发 Release（打包 → 建 tag → 传附件 → 回读）

**只有 `_build_release.ps1` 能产出交付包**，`Release\` 是构建产物，`zip` 不入库
（`.gitignore` 排除 `Release/`）。完整流程：

```powershell
# 1. 重建 Release\ 并自检（它会先清空 Release\ 再重建）
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_build_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_verify_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_verify_layout_match.ps1

# 2. 打包：顶层必须是一个同名目录，收到 %TEMP%（zip 不进仓库）
$stage = "$env:TEMP\touchHLE-zombiefarm-<版本>"
$zip   = "$env:TEMP\touchHLE-zombiefarm-<版本>.zip"
robocopy Release $stage /E /NFL /NDL /NJH /NJS | Out-Null   # 别用 Copy-Item -LiteralPath "…\*"（它不展开通配符）
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal -Force

# 3. 记下大小与 sha256，写进 Release 说明的「校验信息」表
(Get-Item $zip).Length
(Get-FileHash $zip -Algorithm SHA256).Hash
```

**回读校验**（`$zip` 里应有 43 个文件，IPA 59,564,493 B，`touchHLE.exe` 26,376,704 B）：

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
$a = [System.IO.Compression.ZipFile]::OpenRead($zip)
($a.Entries | Where-Object { $_.Name -ne '' }).Count      # 应为 43
$a.Entries | Where-Object { $_.FullName -match '\.ipa$' } | ForEach-Object { "$($_.FullName)  $($_.Length)" }
$a.Dispose()
```

**建 Release 与传附件**（本项目实测走 GitHub REST；`curl.exe` 可用，**.NET WebRequest 不行**）：

```powershell
# ⚠️ 先清掉代理变量，否则 api.github.com 连不上（本机 HTTP_PROXY 指向本地代理）
$env:HTTP_PROXY=''; $env:HTTPS_PROXY=''; $env:ALL_PROXY=''

# 建 Release（body 从本地说明文件读，中文必须按 UTF-8 字节发，否则乱码）
# POST https://api.github.com/repos/<owner>/<repo>/releases
#   {"tag_name":"<tag>","name":"<标题>","body":"<说明>","draft":false,"prerelease":false}
# 传附件：POST https://uploads.github.com/repos/<owner>/<repo>/releases/<id>/assets?name=<文件名>
```

**五个坑（都踩过）：**

1. **附件名必须纯 ASCII**。`POST …?name=<文件名>` 里的中文名会被**静默丢弃** ——
   内容传上去了，但资产名变成 `default.html`，**且不报错**。中文名文件仍可正常放**仓库内**。
   所以附件名用 `touchHLE-zombiefarm-v29fix.zip` 这种，中文留给说明正文。
2. **上传后必须回读** `GET /releases/tags/<tag>` 核对 `assets[].name` 与 `size`，
   不能只看 HTTP 200；**内容完好**要下载回来算 SHA-256 与本地比对（大小相同 ≠ 内容相同）。
3. **改了 Release 说明要 PATCH 并回读**：`PATCH /repos/<owner>/<repo>/releases/<id>`，
   body 用 `ConvertTo-Json` 后**按 UTF-8 字节**发，回读时与本地文件 `-eq` 比对确认逐字符一致。
4. **发布后要核验线上渲染**：抓 release 页面 HTML 确认新链接/新文案真的渲染出来了
   （本会话就是靠这一步发现正文已更新但需刷新确认）。
5. **别忘 `.git/config`**：推送用的令牌不要留在 remote URL 里，发完检查
   `Get-Content .git\config -Raw` 里没有 `ghp_` / `github_pat_` / `x-access-token` 之类的串。

**当前已发布的 Release**（作为格式参考）：

| 项 | 值 |
|---|---|
| 仓库 | `Ashena1017/zombie-farm-touchhle-cn`（public，默认分支 `master`） |
| Release | tag `v29fix`，release id `399756311` |
| 附件 | `touchHLE-zombiefarm-v29fix.zip`，asset id `600164778`，95,050,820 B，state `uploaded` |
| 说明源文件 | `_analysis\reports\RELEASE_NOTES_v29fix.md`（**改完要 PATCH 到线上**） |
| zip 的 sha256 | `39601F129B20E53C641E1D6D37D22057B8B9D578E36E75B22060919C5ADA8841` |

> ⚠️ **重建 zip 会让说明里记录的 sha256 失效** —— 重新打包后必须同步更新
> `RELEASE_NOTES_*.md` 的「校验信息」表并 PATCH 到线上。

---

## 4. 当前设置模型（`GameManager.ps1` 的 `$script:SettingDefs`）

| key | 选项 | 默认 | 说明 |
|---|---|---|---|
| `fps_limit` | `--fps-limit=` | `60` | 30/60/90/120/off/自定义(1–1000) |
| `wheel_zoom` | `--zf-wheel-zoom-step=` | `1.1` | 滚轮每格乘数，预置 1.1/1.2/1.5，自定义 1.01–2.00 |
| `window_family` | `--device-family=` | `ipad` | 只有 ipad/iphone 两项，与 `window_scale` **共用一行** |
| `window_scale` | `--scale-hack=` | `1.5` | 预置 **1.25 / 1.5 / 1.75**（小数），自定义可填小数或分数 |
| `fullscreen` | `--fullscreen` | `0` | 开关型 |
| `run_loop_fix` | `--non-blocking-zero-timeout-run-loop` | `1` | 开关型，**ZFR 必须开** |

设计要点：
- **每个设置只对应一个命令行选项**（不再有 `Extra` 展开多个 token 的机制），
  所以读取时不需要「取最具体匹配」那套规则。
- **共用一行**靠 `Row` 键；布局参数是 `ComboX` / `ComboW` / `CustomX` / `CustomWidth`。
- 行尾 `LblWindowSize` 用 `Get-WindowSizeForScale` **实时算窗口尺寸**
  （算法与 `options.rs` 的 `scale_dim` 一致：横向、分数精确运算、四舍五入加半个分母；
  超出屏幕变琥珀色）。
- **自定义倍率是文本框**（不是数字框）：数字框表达不了 `7/4`，四舍五入会**偷偷改变窗口尺寸**。
  每次按键校验，非法中间态（`1.`、`7/`、`abc`）**不写文件**。
- 开关型选项读取：**行存在但无 token → `'0'`**；整行都不存在才用 `Default`。
  （`Default` 的语义是"推荐值"，不是"缺席时代表什么"。）

界面**没有任何 `?` 按钮**，全部说明在 `Release\使用说明.html`（第二节逐项讲原理）。

---

## 5. 刚做完的三件事（细节在 process.md #27/#28）

1. **新增 `--zf-wheel-zoom-step=`**（fork 扩展）：原来 1.08 是硬编码常量
   （`zombie_farm.rs` 的 `ZOMBIE_FARM_ZOOM_STEP`），现在读 `options.zf_wheel_zoom_step`，
   范围 1.01–2.00。实测每格恰好 ×1.1，改成 1.5 后每格 ×1.5（日志可证）。
2. **窗口大小拆成两个独立设置**（原来是一个打包的 `device_size` 选项组），
   倍率预置统一改成**小数** ×1.25/×1.5/×1.75。
   小数写进 options 文件后 touchHLE 会**约分成分数**再按整数运算，
   所以 `1.5` 与 `3/2` 产生**完全相同**的窗口（八档实测证实）。
3. **删掉 `?` 按钮与全部 `Tip` 文案**，说明搬进 `使用说明.html`；
   顺带修掉两个**原有 bug**：
   - 「高速帧率修复」关掉后重开界面又变回「开启」（读取器错误回退到推荐值）；
   - `-Set` 没解析当前选中的 IPA，写到了**占位** app id 的另一行（GUI 与 `-ShowSettings` 默默不一致）。

---

## 6. 清理了什么（2026-09-23，回收 126 MB）

删除判据：**没有任何在用脚本读取它**（引用清一色是写入），
且**能由 `_analysis/` 里现存脚本重新跑出来**；被文档按名字引用的一律保留。

| 删除 | 内容 |
|---|---|
| 旧会话对话记录 | `_claude_*`、`hist_*`、`history_*`、`session_*`、`analysis_hist_*`（45 个 / 21 MB） |
| `__pycache__` | 3 个目录 / 260 个 `.pyc` |
| 死胡同构建产物 | `_analysis\touchHLE_trunk_build_deadend.exe`（19.6 MB） |
| 测试截图与日志 | `_analysis\perf\` 全部 218 个文件（75.6 MB） |
| 孤儿 dump | `dumps/` 里没有脚本写入、也没有文档引用的 |
| 过期日志 | `_analysis\*.log`（`_build_*`、`_pin_vendor`、`_fork_fetch` …）与旧 GUI 截图 |

**保留**：
- `_analysis\dumps\` 只剩被点名的取证产物 —— `_zfz_*`（施肥机制）、
  `_abil2.out.txt`、`_flags.out.txt`、`_reorg_moves.json`。
- `_analysis\perf\` **保留为空目录**（多个脚本往这里写输出）。
- `_analysis\reports\` 11 份**技术报告**（当前状态的事实来源）。
- `_analysis\archive\` 436 个旧探针脚本（**结论的推导过程只在这些脚本里，别删**）。
- `touchHLE\*.backup-*` 4 个 exe 回滚点（README 明确列为回滚手段）。

清理后**全部验证套件重跑通过**。

---

## 7. 文档地图（要找什么去哪里）

| 想查 | 去哪 |
|---|---|
| 怎么用、界面长什么样 | `TECHNICAL.md` §1（含 GUI 截图文字版） |
| 字号/本地化补丁怎么做 | `TECHNICAL.md` §5（核心技术知识，**务先读**） |
| 历代 patcher 与验证器对应关系 | `TECHNICAL.md` §6.1/6.2；`_analysis/README.md` |
| 已知问题、哪些已修 | `TECHNICAL.md` §7；`process.md` 全表 |
| 能不能重写游戏（重构可行性） | `TECHNICAL.md` §7.5 |
| 历代改动的「现象→根因→修法→验证」 | `process.md`（最新 #28） |
| 每个分析脚本干什么 | `_analysis/README.md` |
| 具体的取证报告 | `_analysis/reports/*.md` |
| **怎么把项目交给下一个会话** | `交接提示词.md`（复制里面的 prompt 直接开新会话） |
| 改补丁的固定套路 | `TECHNICAL.md` §6.3 |

**重要约定**（`TECHNICAL.md` §9 有完整列表，这里列最容易踩的）：
- 改 IPA 前先读对应 `report.json`，改完**必须**跑独立验证器；
- **不碰已占用的 code cave**（§5.10 有清单，新补丁必须列入 `FORBIDDEN_PRIOR`）；
- **根目录只放运行时和交付物**：新脚本进 `_analysis/`，新输出进 `_analysis/dumps/`，活代码进 `tools/`；
- **汇报时不许把「静态全绿」写成「已修好」** —— 游戏内验证由主人做；
- **动存档前先快照**整个 `touchHLE\touchHLE_sandbox` 到 `%TEMP%`，跑完还原；
- **读内存一律 `sl.addr_to_file(va)`**，绝不 `data[va]`；反汇编从方法入口开始（Thumb 会漂相位）。

---

## 8. 建议新会话的起手式

1. 读本文件 → 读 `TECHNICAL.md` §1（用法）与 §5（改补丁必读）。
2. 若主人报「某个功能不对」：先看 `process.md` 最后几行有无同类先例，
   再决定是**功能 bug** 还是**预期行为**。
3. 若主人要改管理器：按 §3.1 流程，改完**必跑** `_ensure_bom.ps1` + `-SelfTest` + 同步 Release。
4. 若主人要改模拟器：按 §3.2 流程，**记得复制二进制到两处**（这个坑踩过）。
5. 若主人要改游戏内容：按 `TECHNICAL.md` §6.3 的固定套路写 patcher + 独立验证器。

**当前等主人的反馈**：×1.5 放大后的画面排布、滚轮 1.1 的手感、`使用说明.html` 的写法。
若主人说「都正常」，则本阶段收尾，无遗留任务。

> 查历史改动时注意：`process.md` 的**最新内容在文件顶部**的待办总览表（最新一行 `#29`），
> 不是文件末尾 —— 末尾是「工作约定」与更早的专题章节。

---

## 9. 交接后追加（2026-09-29，只读核验）

本节由下一个会话追加，记录**本文件写就之后**发生的变化。

**核验结论**：本文件的事实性声明与磁盘**一致**（5 个哈希、IPA 字节数、options 生效行、
6 项验证套件全绿、回滚点 4 个、`archive` 436 / `reports` 11 / `tools` 50 个 `.py`、
`zombie_farm_ipa` 63 文件 33 个 IPA / 1.79 GB）。完整逐条证据见
`_analysis\reports\ZFR_交接核验_20260929.md`。

**核验之后的新事实**：

1. **游戏被真实游玩过一次** —— `zfr_last_launch.txt` 记 `2026-09-29T02:50:32`、IPA = v29fix。
   因此真实存档的字节数已从本文写的 11592 变成 **10864 B**（游戏自己改写，非事故）；
   货币仍是**金币 140586 / 脑子 4410**（本次用 `SetZombieFarmCurrency.ps1 -WhatIf` 只读复核），
   存档 sha256 = `05B5D250CCAF818BD3D9AA82CF7FDBB6402E1901732D1268C10062BA12AFE35D`。
   **「等级 40」本次未复核**（没单独取证等级字段），引用时请注明未核验。
2. **模拟时间偏移累计 118800 秒（33 小时）** —— 见 `touchHLE\touchHLE_time_offset_seconds.txt`。
3. **订正本文 §6 一处**：`_analysis\perf\` **不可能是空目录** ——
   `_verify_release.ps1` 第 27 行固定把日志写到 `_analysis\perf\release_verify.log`，
   每跑一次就留一份。它是该脚本的正常输出，**别当垃圾删**（删了不影响功能，只是白删）。
4. **另外 4 处过时/易误导的表述**（README 界面示意里的 v28fix、存档示意里的 3885 B、
   `交接提示词.md` 与构建脚本注释里的「最新 #29」、`Release\touchHLE\` 多出的 4 个许可文件）
   已列在核验报告 §4，**均未改动**，等主人决定是否订正。

**状态**：无阻塞项，环境全绿。

---

## 10. 交接后追加（2026-10-01，发布流程）

本节记录**发布到 GitHub** 这条链路的固定做法。新增两节工作流在 §3.5（发 PR）与
§3.6（发 Release），**动手前务必先读那两节**，这里只列最容易忘的几条。

**仓库与 Release 现状**：

| 项 | 值 |
|---|---|
| 仓库 | <https://github.com/Ashena1017/zombie-farm-touchhle-cn>（public，默认分支 **`master`**） |
| Release | <https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/tag/v29fix>（release id `399756311`） |
| 附件 | `touchHLE-zombiefarm-v29fix.zip`（asset id `600164778`，95,050,820 B，`uploaded`） |
| 说明源文件 | `_analysis\reports\RELEASE_NOTES_v29fix.md` —— 改完**必须 PATCH 到线上** |
| zip 的 sha256 | `39601F129B20E53C641E1D6D37D22057B8B9D578E36E75B22060919C5ADA8841` |

**入库范围**（`.gitignore` 已排除，别再手动 `git add -f`）：构建产物、Rust 工具链（4.4 GB）、
上游 `vendor/`（843 MB）、游戏 IPA、`Release/`、存档、日志。6.25 GB 的工作树压成 **38.6 MB** 的提交。

**关键提醒**：

1. **`Release/` 与 zip 都不入库**，交付靠 Release 附件；改交付内容 = 重建 → 重新打包 → 重新上传。
2. **附件名必须纯 ASCII** —— 中文名会被 GitHub **静默丢弃**成 `default.html`，且不报错。
3. **上传/改说明后一律回读**：附件核对 `name` + `size` + 下载回来算 sha256；
   说明正文与本地文件做 `-eq` 比对。
4. **重建 zip 会让说明里的 sha256 失效**，必须同步更新「校验信息」表并 PATCH 到线上。
5. **`curl.exe` 能用，.NET `WebRequest` 在这台机器上不行**（代理变量会让它返回 HTTP 0）——
   调用 API 前先 `$env:HTTP_PROXY=''; $env:HTTPS_PROXY=''; $env:ALL_PROXY=''`。
6. **`git credential fill` 返回的是字符串数组**，`$x.Length` 是元素个数不是字符数，
   必须先 join 再解析（见 §3.5）。
7. **绝不打印令牌**，不写进文件、不 `echo`、不贴进会话；发完检查 `.git/config` 里没有残留令牌。

---

## 11. 交接后追加（2026-10-05，Android ARM64 同步）

**Android ARM64 fixed APK 已构建并通过静态包核验**。Android Gradle 构建会把仓库默认 v29fix IPA 放进 APK assets；首次启动或 IPA 哈希变化时，touchHLE 会自动原子复制到应用数据目录的 `touchHLE_apps/Zombie_Farm_v29fix.ipa`，不需要用户手动操作 `data`。Android 专属选项按触屏使用：横屏、60fps、iPhone 设备族、原生倍率、non-blocking run-loop fix；不配置滚轮，由游戏处理两指捏合。GL/FBO 相关改动复用共享 fork 源码。

新增构建与静态包校验入口：`_analysis\_build_android.ps1`、`_analysis\_verify_android_package.ps1`。构建需要 JDK 17、Gradle 8.11.1、Android SDK/NDK `27.2.12479018`，并设置 `ANDROID_HOME` 或 `ANDROID_SDK_ROOT`。旧 APK `touchHLE-zombiefarm-android-arm64\touchHLE-zombiefarm-android-arm64.apk`（36,121,590 B）未修改；fixed APK 位于 `touchHLE-zombiefarm-android-arm64\touchHLE-zombiefarm-android-arm64-fixed.apk`。构建与 APK 结构核验已通过：内置 IPA `59,564,493 B`，SHA-256 为 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`；Android 实机安装、启动、两指捏合和自动安装 IPA 仍待主人验证。

**文档命名口径**（本会话订正过，别再改回去）：

- 本项目跑的是**原版**《僵尸农场》（Zombie Farm）。`ZFR` 是**游戏自己的 bundle 代号**，
  来自 `Payload/ZFR.app/Info.plist`（`CFBundleIdentifier` = `com.playforge.ZombieFarm.ZFR`，
  `zh-Hans` 显示名 = `僵尸农场`，`zh-Hant` = `殭屍農場`）—— **不要把 `ZFR` 展开成任何词**。
- **「Reforged」只指 `actualdoctornerd-ai/Zombie-Farm-2-Reforged`**（另一位粉丝从零重写的
  TypeScript 项目），**不是本项目**。README 与 Release 说明里都有显式辟谣句，别删。
- 配套的**汉化脚本**是主人另一个仓库
  `Ashena1017/zombie-farm-reforged-translation-cn`（Tampermonkey 用户脚本，精翻，
  词库取自原版官方简体中文语言包），在 README 的「想玩原版还是重制版」小节里推荐。

## 12. 交接后追加（2026-10-06，Android MuMu 黑屏定位）

本次 Android 实测已经把现象边界固定下来，明日从本节继续：

1. 使用固定设备 `127.0.0.1:5557`、包名 `org.touchhle.zombiefarm`、ADB
   `C:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe`。本轮测试时 MuMu 进程 PID 为
   `12903`，前台 Activity 为 `org.touchhle.android.MainActivity`；收尾时已执行
   `am force-stop`，明日启动 APK 即可继续。
2. fixed APK 已安装并启动。启动菜单中文画面正常，截图为
   `_analysis\dumps\android-mumu-composition-launch.png`；ADB 点击「开始游戏」后，截图
   `_analysis\dumps\android-mumu-game-after-tap.png` 变为近乎纯黑，但进程持续运行，日志显示
   游戏逻辑继续、角色加载与 `saveGame.bin2` 保存继续，没有 `FATAL EXCEPTION`、`SIGSEGV`、
   `Panic` 或 `touchHLE crashed!`。
3. 当前问题已经从「启动呈现失败」缩小为「切换到游戏场景后的 Core Animation/GLES 输出失败」。
   `ZFR GL trace` 仍显示游戏在 `fbo 1`、`viewport 320x480` 绘制；`presentRenderbuffer` 日志显示
   `fullscreen (null)`，按当前源码应走慢速 `glReadPixels`→`present_pixels`→compositor 路径，
   但现有日志尚未看到预期的 `ZFR Android readback`，这是明日第一检查点。
4. 当前未清理的临时诊断日志包括 `ZFR Android present/readback/probe/frame stats` 与
   `ZFR GL trace`。定位完成后再删除日志并重跑 Android 构建与静态包校验；今晚不要把这些诊断
   改动宣布为最终修复。
5. 明日优先检查：`composition.rs` 的 `recomposite_if_necessary` 是否在点击后执行、drawable
   layer 的 `presented_pixels` 是否被更新、`read_renderbuffer` 是否实际返回非零像素，以及
   layer bounds/sublayers 是否在场景切换后改变。已有完整日志：
   `_analysis\dumps\android_clean_tap640_log.txt`、`android_original_force_composition_log.txt`、
   `android_diag_direct3_log.txt`、`android_gl_trace.log`。

**当前结论边界**：Android APK 的内置 IPA、默认 iPhone/60fps/横屏/non-blocking 参数和静态包
校验已经确认；「点击开始游戏后画面可见」尚未确认，不能写成已修好。

## 13. 交接后追加（2026-10-06，Android 读回修复与形象页）

1. `eagl.rs` Android 默认 framebuffer (`framebuffer 0`) 读回分支已保留：诊断确认游戏帧在默认 framebuffer，而 drawable renderbuffer 为空。临时 `ZFR Android` / `ZFR GL trace` 探针已从源码移除；Android GL 状态恢复仍把 `GLboolean` 当作零/非零处理。
2. 无诊断日志的 fixed APK 已重建并通过 `_analysis\_verify_android_package.ps1`。APK SHA-256 为 `152B4E8F59CC136C12269C71A2B6A010728307983417928D0D4C3ED8297037D3`；内置 IPA 为 `59,564,493 B`，SHA-256 仍为 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`。
3. MuMu 实测：新 APK 从开始菜单进入游戏后不再黑屏，等待后到达欢迎教程与「选择形象」页。加载过渡采样到的 Playforge 画面连续哈希一致；形象页稳定后仍有横贯头像列表的棕色遮挡区，头像只在右侧部分可见。截图：`_analysis\dumps\android-final-apk-menu-20261006.png`、`android-final-entry-settled-20261006.png`、`android-final-avatar-settled-20261006.png`。这不是 IPA 内缺图的证据：右侧头像素材可见，Android 实际载入 IPA 与 Windows 使用的 v29fix SHA-256 完全一致。更可能是 touchHLE 的 Core Animation/UIScrollView 合成或内容偏移问题；`composition.rs` 仍明确标记 `clipping/masksToBounds` 未实现（第 689 行）。该根因尚未由 Windows 对照或代码修复验证。
4. 本轮没有在取样的稳定画面中复现闪黑，但这不能证明所有进场时序都无闪烁。最终结论应写成「已解决黑屏、发现形象页遮挡、闪烁待进一步复现」，不能写成 Android 全部正常。
5. 测试后 MuMu 已 force-stop、卸载并干净重装 fixed APK，以恢复 Android 私有目录权限；随后把测试前外部快照恢复。MuMu 的 `saveGame.bin2` **870 B**，SHA-256 `05BD833C4A952C3A38BBFFB78D4071E775EBEB1F49BB326101FE81CA82086BAB`，与快照逐字节一致；设备上的 IPA 也与预期 SHA-256 一致。当前包名 `org.touchhle.zombiefarm` 已停止，`run-as` 正常，无需 root。不要用 Windows tar 重打包后直接解到 Android app 私有目录；异常权限时干净重装比 root 更稳妥。

## 14. 交接后追加（2026-10-06，Android 形象页遮挡续查）

1. **只查 Android；Windows 版本已由主人确认无此问题，不要再做 Windows 对照。IPA 不改。** MuMu 设备仍用 `127.0.0.1:5557`，ADB 路径见 §12；安装更新必须用 `adb install -r`，不可卸载，以免清掉当前 Android 测试数据。
2. 已在 MuMu 上用 fixed APK 重现遮挡，并成功用 `adb shell input keyevent 141` 触发 F11 导出实时 inspector。当前可复核证据：截图 `_analysis\dumps\android-avatar-scissor-probe-after.png`；转储 `_analysis\dumps\android-avatar-scissor-probe-inspector.txt`。转储显示表格 `view_size=480×100`、`content_size=1050×100`，15 个头像格和 sprite 存在；滑动后 `content_offset.x=-603.6433`、子层 `x=-570`，可见头像确实随表格滚动。**资源缺失与静态表格偏移都不符合现象。**
3. 水平滑动后，棕色横带相对屏幕保持不动，而头像内容移动；同一转储显示背景 `CCColorLayer` 位于 `{0,140}`、尺寸 `480×75`、`z=3`，`CCTableView` 为 `z=5`。因此当前首要方向是 Android 下该场景的 Cocos 绘制/层级顺序，暂不归因于 IPA 或滚动偏移。
4. `gles_guest.rs` 当前有临时 `ZFR Android scissor probe`，记录前 256 次调用的原始请求、实际提交矩形、缩放状态和 framebuffer。全量探针 APK 已构建、静态包核验通过并以 `adb install -r` 安装；包内 IPA 字节数 `59,564,493`，SHA-256 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`。从清空 logcat、冷启动到形象页稳定，未出现任何 scissor probe 日志；这是比上一轮窄筛选更强的证据，表明本次进场/形象页流程没有经 guest `glScissor` wrapper，但不排除 GL 状态由其它路径设置。
5. **当前仍未修复。** 水平滑动实测显示头像会跟随表格移动，棕色带固定在屏幕上；故遮挡物不是表格内容或其滚动偏移。下一步记录 Android 上该背景 `CCColorLayer z=3` 与表格/sprite 的实际 `visit`/`draw` 次序，并核实 GL 绘制状态，找出为何 z3 区域最后盖住 z5 表格；然后再做 Android 专属、按证据限定范围的修复，重建并实机复测。不要照搬 Windows 窗口设置，不要动存档或选择头像来“验证”。
6. 本轮 MuMu 是新测试存档（200 金币），当前停在选择形象页；通过滑动只改变了临时表格偏移，未确认/保存形象。全量探针截图为 `_analysis\dumps\android-avatar-scissor-probe-full.png`，Inspector 为 `_analysis\dumps\android-avatar-scissor-probe-inspector.txt`。工具链位置和构建命令仍以本文 §11 与本会话记录为准，不要重复搜索 Android/ADB/Cargo 环境。

## 15. 交接后追加（2026-10-06，Android 一键进形象页与遮挡续查）

1. 新增双击工具 `tools\AndroidEnterAvatar.exe`，源码为 `tools\AndroidEnterAvatar.cs`。它使用固定 ADB
   `C:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe`、设备 `127.0.0.1:5557`、包名
   `org.touchhle.zombiefarm`，自动 force-stop / 启动 / 点击开始 / 点击欢迎页勾。屏幕点击按实时截图尺寸比例换算：
   开始按钮 `(0.5, 0.5833)`、欢迎页勾 `(0.5, 0.7778)`；等待分别为 8 秒、18 秒、4 秒。
   在 1920×1080 MuMu 横屏完整实测通过，停在“选择形象”页，没有选中头像。运行：双击 `tools\AndroidEnterAvatar.exe`。
2. 运行截图 `_analysis\dumps\android-entry-tool-final.png`；同次 F11 Inspector
   `_analysis\dumps\android-avatar-oneclick-inspector.txt`。它确认背景为同一父层下的 `CCColorLayer`
   （480×75，位置 `{0,140}`，z=3），头像表格为 `CCTableView`（view 480×100，内容 1050×100，z=5）。
   旧的消息钩子提升 z-order 没生效：转储仍为 z=5，运行日志无 `raised avatar` 记录。
3. `zombie_farm_debug.rs::repair_android_avatar_table_order` 从 Android `eagl.rs::presentRenderbuffer`
   入口调用；精确匹配上述棕色层与表格后，用父节点 `reorderChild:z:` 将表格提高至 z=20。
   首次构建/实测后 Inspector 仍为 z=5；根因已查明是守卫误用了另一个历史 bundle id
   `com.playforge.ZFR.LZ54D2GT3D`。真实运行日志确认当前 IPA bundle id 是
   `com.playforge.ZombieFarm.ZFR`，源码守卫刚已改正；一次性 `presentRenderbuffer hook entered`、
   table size 和重排日志用于下次验证。**该改正尚未构建/实测，遮挡仍未修复。**
4. 本轮构建命令仍是 `powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_build_android.ps1`。
   本机快捷构建封装为 `_analysis\_build_android_local.ps1`，直接运行即可。固定目录为
   `C:\Users\Loner\AppData\Local\Temp\zfr-android-toolchain`：Gradle `gradle-8.11.1\bin\gradle.bat`，
   JDK 17 `jdk17\`，Android SDK `android\`，Gradle 缓存 `gradle-home\`；Cargo/Rustup 分别为
   `touchHLE\_build_tools\cargo\` 与 `touchHLE\_build_tools\rustup\`。快捷脚本统一设置这些变量并调用
   `_build_android.ps1`（含静态包核验）。不要再次搜索 Android/ADB/Gradle/Cargo 环境；ADB 路径见 §12/§14。
5. 测试结束 MuMu 应仍在选择形象页，存档仍为新测试存档（200 金币）；不要点“选择”或确认形象。
   目标仍是修复 Android 形象页头像被棕色横带遮挡；Windows 无此问题，不查 Windows、不改 IPA。

### 15.1 常驻环境速查与本轮续查

**不要在新会话重新搜索 Android/ADB/Gradle/Cargo 环境**，先核对本小节；只有命令明确报路径不存在时才重新定位。

| 项 | 固定值 / 做法 |
|---|---|
| MuMu 目标设备 | `127.0.0.1:5557`；`adb devices -l` 还会列出 `emulator-5556`，所有命令必须显式 `-s 127.0.0.1:5557` |
| ADB | `C:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe` |
| Android 包 | `org.touchhle.zombiefarm`；前台 Activity `org.touchhle.android.MainActivity` |
| root | 不需要。`adb shell run-as org.touchhle.zombiefarm` 可用；不要为本问题开启 root |
| 快捷构建 | `powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_build_android_local.ps1`（构建后含静态包核验） |
| Android 工具链 | `C:\Users\Loner\AppData\Local\Temp\zfr-android-toolchain`；Gradle `gradle-8.11.1\bin\gradle.bat`、JDK `jdk17\`、SDK `android\`；Cargo/Rustup 在 `touchHLE\_build_tools\cargo\` 与 `touchHLE\_build_tools\rustup\` |
| 一键进入头像页 | `tools\AndroidEnterAvatar.exe`；更新 APK 用 `adb install -r`，不要卸载 |
| F11 Inspector | `adb shell input keyevent 141`；文件在 `/storage/emulated/0/Android/data/org.touchhle.zombiefarm/files/zombie_farm_inspector.txt`，用 `adb pull` 拉到 `_analysis\dumps\` |

**本轮续查结论（2026-10-06）**：隐藏 `CCColorLayer`（480×75，位置 `{0,140}`、z=3）能去掉棕色横带，但头像左侧仍为空；故该层不是完整根因。试验把表格 `contentOffset.x` 设为 210，只改变了当前显示的头像项，屏幕上的可见头像区域仍固定在右侧，没有修复左侧留白。证据为 `_analysis\dumps\android-avatar-offset-test.png` 与 `android-avatar-offset-test-inspector.txt`。**源码已撤销 210px 偏移，但刚安装的测试 APK 仍含这项偏移**；下次改好/确认源码后必须重新构建再装。下一步应检查 Android GLES/Cocos 实际绘制与可见裁剪区域，不能再把滚动偏移当作已证实原因。

一键工具在本次从非交互 PowerShell 调用时确实完成进场，但最后 `Console.Read` 因无控制台输入抛异常并返回 1；若继续使用该工具，需让它在输入重定向时直接退出，或从交互终端启动。MuMu 仍停在头像页；只进行了滑动与截图，未选中或确认形象。当前问题未修复。


## 16. 交接后追加（2026-10-06，稳定形象页逐 draw 取证）

- §15/§15.1 关于已安装 offset=210、z-order 修改尚未构建的状态已过时：当前源码撤销这些无效试验；`hide_android_avatar_selection_overlay` 及 visit 前抬高 z-order 的函数已移除，完整原始界面恢复。depth/stencil 强制关闭也已移除，两项均没有改善，不能继续保留为修复。
- 本轮关闭 depth、关闭 stencil、有效隐藏 `412×139` 面板、隔离表格兄弟节点，均没让左侧头像出现。有效证据：`android-depth-test-avatar.png`、`android-stencil-off-test.png`、`android-panel-hide-test2.png`、`android-table-isolation-test.png`（均在 `_analysis/dumps/`）。第一次 panel-hide 未命中，不作为有效证据。
- 新诊断 APK 支持稳定页抓整帧：`adb shell touch /storage/emulated/0/Android/data/org.touchhle.zombiefarm/files/zfr_capture_frame`。在下次 guest glClear 后，逐 draw 保存 `zfr-frame-NNN.rgba`（320×480 RGBA）及 `zfr-frame-state.txt`，到 presentRenderbuffer 结束，最大 300 draws。主机转换脚本 `_analysis/_convert_android_frame.ps1`。本轮抓到 95 draws，输出 `_analysis/dumps/android-frame-probe/`。
- **关键新证据**：头像 draw #49～85 期间 `GL_CLIP_PLANE0..3` 全部 enabled；此前启动计数探针捕得太早，遗漏稳定页状态。scissor/stencil/alpha/cull 均关闭；modelview 是正常横屏旋转，viewport=320×480 本身不是已证明的问题。逐 draw #55 就没有左侧头像，末帧 #94 仍只见右侧两个：继续查裁剪平面方程及 native GLES 的变换，停止猜测普通 panel 遮盖或 offset。
- `tools/AndroidEnterAvatar.cs` 已修正重定向输入时等待按键抛异常的问题，EXE 已重编译；非交互自动执行成功退出 0。
- 当前临时探针在 `gles_guest.rs`（整帧）及 `gles1_native.rs`（ClipPlanef 输入/存储值）。问题仍未修复，修好后必须去掉探针再构建复测。不改变 IPA、Windows 和存档；不点击“选择”确认。
## 17. 交接后追加（2026-10-06，Android 形象页裁剪修复完成）

**本节记录已完成的裁剪修复；最新 APK 与全屏追加见 §18。§12～§16 是取证历史，不再代表未完成事项。**

1. **根因有日志与画面证据**：MuMu native GLES 的 `glClipPlanef` 没有按当前 modelview 的逆转置变换方程。Cocos 在头像表格局部坐标提交 `[0,-1,0,100]`，当时 modelview 含 -90° 旋转与 `{130,480}` 平移；`glGetClipPlanef` 仍返回原方程。它把裁剪错误应用成眼坐标 `y<=100`，对应截图只保留右侧约 100px（两头像）。证据：`_analysis/dumps/android-clip-native-log.txt`、`android-frame-probe/zfr-frame-state.txt` 与逐 draw 图像。**不是 IPA 缺图，也不是普通 panel 覆盖、contentOffset 或 z-order。**
2. **最终修法**：`src/gles/gles1_native.rs` Android `ClipPlanef/ClipPlanex` 先在 CPU 求 modelview 逆转置后的 eye-space plane，临时用 identity modelview 提交，再恢复原矩阵与 matrix mode。标准 GLES driver 也得到同样的正确方程；非 Android 保留原透传。保留真正的列表边界，不关闭裁剪、不隐藏背景、不修改 IPA。
3. **清理完成**：整帧、scissor、clip 方程探针均已从活源码移除；无效的 depth/stencil 强制关闭、表格偏移、z-order 抬高、CCArray 重排与面板隐藏都已移除。保留前序黑屏修复、GLboolean 状态恢复、Android 包内 IPA 自动安装等必要改动。`ca_eagl_layer.rs` 去掉了强制 Android composition 返回之后不可达的 Android 放宽检查。
4. **无探针正式包实测**：覆盖安装后冷启动、一键进入头像页、横向滑至列表后端、再滑回起点均正常；第一排头像和绿色选中框可见，后端上锁头像正常显示、边界处正确裁剪。最后 Inspector `content_offset={0,0}`，进程持续存活（当次 PID 17743），本轮 logcat 未发现 `FATAL EXCEPTION`、`SIGSEGV`、`Panic`、`touchHLE crashed!`，也无诊断探针日志。未点击头像或“选择”确认。截图 `_analysis/dumps/android-avatar-final-cold.png`、`android-avatar-final-scroll.png`、`android-avatar-final-end.png`；Inspector/log 同前缀。
5. **包与数学校验**：最终 APK `touchHLE-zombiefarm-android-arm64/touchHLE-zombiefarm-android-arm64-fixed.apk`，97,270,439 B，SHA-256 `FAE0C10DBDB71FFCF075030CCEBC759CA35520BC81CF98461E968F457493F9AE`；设备已安装 `base.apk` SHA-256 与本地完全一致。构建及 `_verify_android_package.ps1` PASS；内置 IPA 59,564,493 B / `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED` 未变。真实源码裁剪变换函数的 3 项测试（四个旋转表格边界、缩放平移斜平面、奇异矩阵回退）全过，测试保存在 native 源码 `clip_plane_tests` 中；本机通过 rustc 单独编译执行该函数与测试，无需启动 Windows 游戏。
6. **固定操作补充**：构建使用的 SDK ADB 可能让本机 ADB server 重启、丢失连接；每次安装前先用 MuMu ADB `connect 127.0.0.1:5557`，确认 `install -r` 成功后再运行 `tools/AndroidEnterAvatar.exe`。不要只因一键工具能启动就推断新包已安装。当前包已装到 MuMu，停在选择形象页。真实 Android 手机、其它页面及长时闪烁仍未由本轮覆盖；不要把这项 MuMu 头像修复写成所有设备全游戏已确认。

## 18. 交接后追加（2026-10-06，Android 沉浸式全屏）

**本节是最新交付状态。** 主人反馈顶部时间、Wi-Fi、电池状态栏一直显示，希望隐藏并让游戏画面使用顶部空间。

1. **实测根因**：旧包运行时 `dumpsys window` 显示 `FORCE_NOT_FULLSCREEN`、`vsysui=LAYOUT_STABLE`。SDLActivity 在创建窗口时调用 `setWindowStyle(false)`，其异步窗口样式设置会覆盖 Manifest 的全屏主题；只设置主题不足以保持全屏。证据：`_analysis/dumps/android-fullscreen-before-window.txt` 与 `android-fullscreen-before.png`。
2. **实现**：只修改 Android `android/app/src/main/java/org/touchhle/android/MainActivity.java`。在 `onCreate`、`onResume`、恢复窗口焦点及 SDL 退出全屏时重新隐藏系统栏；清除 `FLAG_FORCE_NOT_FULLSCREEN`，设置 `FLAG_FULLSCREEN`，并同步 SDL `mFullscreenModeActive`。Android API 30+ 使用 `WindowInsetsController`、`setDecorFitsSystemWindows(false)` 和 `BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE`；API 21～29 使用 immersive-sticky flags。游戏保持原有比例，系统栏空间交还渲染区域；边缘滑动仍可临时显示系统栏。没有修改 IPA、Rust 渲染代码或 Windows 二进制。
3. **MuMu API 35 实测通过**：覆盖安装、冷启动开始菜单、一键进入选择形象页、切桌面后返回、顶部边缘滑动。开始菜单与形象页顶部第一游戏像素为 `y=0`，旧包为 `y=72`；系统状态 `statusBars visible=false`。滑动时 `visible=true`，4 秒后恢复 `visible=false`。头像仍完整可见；本轮日志未发现 `FATAL EXCEPTION`、`SIGSEGV`、`panicked at` 或 `touchHLE crashed!`。截图：`android-fullscreen-menu.png`、`android-fullscreen-avatar.png`、`android-fullscreen-resume.png`、`android-fullscreen-delivery.png`，均在 `_analysis/dumps/`。切回时采样到了开始菜单画面，本轮不据此宣称游戏后台进度恢复正常。
4. **最新交付 APK**：`touchHLE-zombiefarm-android-arm64/touchHLE-zombiefarm-android-arm64-fixed.apk`，`97270814` B，SHA-256 `00122762D11ADE481550E95953CAB836B594867D5B4B7349FC71F07457697A67`。MuMu 已安装 `base.apk` SHA-256 与本地相同，当前停在全屏开始菜单。内置 IPA 仍为 `59564493` B / `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`。快捷构建与 `_verify_android_package.ps1` PASS；修改前 6 项项目基线全部 PASS。构建日志 `android-fullscreen-build.txt`。
5. **存档保护**：测试前已 force-stop 并将整个 Android `touchHLE_sandbox` 快照到 `%TEMP%`；测试结束还原并重新拉取，全部 4 个文件 SHA-256 与快照逐字节一致。快照位置记在 `_analysis/dumps/android-fullscreen-snapshot-path.txt`。没有选择或确认头像；Windows 真实存档未用于本轮测试。
6. **验证范围**：目前全屏效果实测覆盖 MuMu Android API 35；API 21～29 的兼容分支已编译，尚未在对应设备实测。真实手机、刘海屏以及全游戏长时运行仍待主人继续确认。固定 ADB、构建工具与一键入口沿用 §15.1，无需重新搜索环境。

## 19. 交接后追加（2026-10-06，Android「ZF游戏管理」）

1. **产品行为**：APK 启动入口名为「ZF游戏管理」，首页先进入原生管理器，不会直接进入游戏。v29fix IPA 内置在 APK assets，首次启动时校验 SHA-256 并安装到应用数据目录；无需用户复制 `data`。其他 IPA 通过 Android 系统文件选择器导入，校验后加入版本列表并可切换。选择、设置和累计跳过时间按 IPA 的 bundle id 隔离。
2. **管理功能**：游戏页有版本切换、导入 IPA、启动、启动并跳过时间、重置累计偏移、金币/脑子读取与修改；设置页有 iPhone/iPad、渲染倍率、30/60/90/120/不限/自定义 FPS、高速帧率修复开关；存档页有完整备份、恢复前自动备份、完整 ZIP 与 `saveGame.bin2` 导入、ZIP 导出和备份删除。存档/设置操作与独立 `:game` 进程使用独占文件锁；游戏运行期间存档操作禁用。Android 默认 iPhone ×1/60 FPS，不使用 Windows 滚轮或 `scale-hack`，触控缩放交给游戏两指手势。
3. **代码与构建**：新增 `ManagerActivity.java`、`ZfIpa.java`、`ZfSave.java`、`ZfStorage.java` 与隔离目录 instrumentation runner；修改 `MainActivity.java`、Android manifest、Gradle 版本与 Rust Android 参数入口。快捷构建：`powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_build_android_local.ps1`；隔离测试：`powershell -NoProfile -ExecutionPolicy Bypass -File _analysis\_test_android_manager.ps1`；APK 静态检查由构建脚本调用 `_analysis\_verify_android_package.ps1`。不要重复定位环境：MuMu ADB 为 `C:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe`，设备 `127.0.0.1:5557`，工具链根目录 `C:\Users\Loner\AppData\Local\Temp\zfr-android-toolchain`，其余固定路径见 §15.1。
4. **最终 APK**：`touchHLE-zombiefarm-android-arm64\touchHLE-zombiefarm-android-arm64-fixed.apk`，97,298,603 B，SHA-256 `CAE397A0901A1DCAE069834E6421D856819DAF84995298FFE0F8D9E61DBB7167`。MuMu `base.apk` SHA-256 与本地逐字节一致。APK 内 v29fix IPA 59,564,493 B / SHA-256 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`；静态校验 PASS。隔离 instrumentation `30 checks PASS`，输出 `_analysis\dumps\android-manager-tests.txt`。构建输出见 `_analysis\dumps\android-manager-build.txt`，测试构建/设备输出见 `_analysis\dumps\android-manager-test-build.txt` 与 `android-manager-tests-run.txt`。
5. **MuMu 最终包实测**：API 35 覆盖安装后冷启动进入管理器首页，显示内置 v29fix；游戏/设置/存档三页、设备/倍率/FPS 选项、跳过时间对话框和完整备份操作都已在 MuMu 检查。最终包从「启动游戏」进入中文开始菜单成功，再退出回管理器，创建并恢复完整备份。开始菜单显示 MuMu 测试存档金币 200 / 脑子 0；没有点「开始游戏」、确认头像或改动货币。快照在 `%TEMP%\zfr-android-manager-final-<GUID>\touchHLE_sandbox`，路径记录于 `_analysis\dumps\android-manager-final-snapshot-path.txt`；恢复后四个 sandbox 文件与快照逐字节一致（哈希记录见上一节 §18 与本轮 shell 输出）。测试 ZIP 和创建的 `zf_manager.json` 已删除，MuMu 停在管理器存档页。截图包括 `android-manager-final-clean.png`、`android-manager-final-save-backedup.png`、`android-manager-final-game-launch.png`。
6. **验证边界**：静态校验和隔离测试不等于所有真实流程均已实测。当前未在真实 Android 手机验证；没有实际执行「启动并跳过时间」、金币/脑子写入或系统文件选择器导入 IPA；没有验证厂商系统/刘海屏适配与长时间游戏稳定性。MuMu 入口游戏启动只到中文开始菜单。抓取无关 logcat 时出现的 SIGSEGV 进程名为系统 `uiautomator` helper 的 Shutdown thread（PID 9554），不是 `org.touchhle.zombiefarm`；Android Activity exit-info 没有本轮应用崩溃记录。Windows 真实存档未用于 Android 测试。

## 20. 交接后追加（2026-10-06，Windows 备份恢复累计时间）

1. Windows `GameManager.ps1` 现为每份备份创建隐藏伴随文件 `<backup>.zf-offset`，内容是创建时 `touchHLE_time_offset_seconds.txt` 的累计秒数。恢复新备份时，先自动创建包含当前存档与当前 offset 的 `pre-restore` 备份，再还原存档并原子写回 offset。删除和批量删除会一起移除伴随文件；伴随文件不会显示为备份条目。
2. **旧备份兼容**：没有 `.zf-offset` 的旧文件仍可恢复，按旧行为只恢复 `saveGame.bin2`，保留当前 offset；不臆测为 0。若元数据内容无效则在改动实时存档前拒绝恢复。`launcher_skip_memory.txt` 只记住对话框上次输入的本次跳过时长，不属于累计 offset，不随存档恢复。
3. 自检已扩展覆盖新建时保存 7200 秒、恢复时从 9999 秒还原为 7200、旧备份保留当前值、非法元数据不改动存档/offset，以及删除 sidecar。完整 `GameManager.ps1 -SelfTest` PASS；真实 Windows sandbox 在 `%TEMP%\zfr-windows-backup-offset-before-<GUID>\touchHLE_sandbox` 逐文件比对 5 个文件均与测试前 SHA-256 一致。静态测试没有使用 Windows 真实存档写入。
4. 交付脚本 `_analysis\_build_release.ps1` 已同步说明此行为，必须用该脚本重建 `Release\`，不要手动改生成后的 `Release\使用说明.html`。累计时间仍是 touchHLE 根目录下的全局 `touchHLE_time_offset_seconds.txt`，不会随 IPA 单独隔离。

## 21. 交接后追加（2026-10-07，双平台启动器主题）

1. 主人要求启动器采用伊蕾娜相关配色，随后明确取消角色插画，只保留配色。原始配色版本记录在本节；主人随后指出主体应为银白、灰紫、夜蓝与金色，不应使用酒红。最终校正与 Windows 页面重构见 §22。
2. Windows `GameManager.ps1` 的旧版「游戏」页采用桌面双栏，右侧集中画面和帧率设置；主人反馈这只是移动设置位置，要求重新设计。最终独立页面与动态窗口尺寸见 §22。
3. Android 保留原生触屏纵向信息顺序，更新 `ManagerActivity.java` 与 `res\values\zf_styles.xml` 的主题色、系统栏颜色、选中页签/按钮、卡片和开关颜色。没有修改游戏 Activity、渲染代码、IPA 或数据处理。
4. 原始主题版本的 Android APK 与验证记录保留作历史；如按 §22 校正 Android 配色并重建，须在 §22 更新当前 APK 哈希。Windows Release 与实窗截图的最终状态按 §22 记录。

## 22. 交接后追加（2026-10-07，Windows 管理器重构与配色校正）

1. 主人指出旧 Windows 界面只是把设置移到右侧，并纠正伊蕾娜配色不应使用酒红。Windows 管理器改为三个独立页面：**游戏**仅放 IPA、启动与货币操作；**设置**集中设备/窗口倍率、帧率和显示选项；**存档**独立管理备份。页面切换时窗口高度按当前页面内容调整，避免短页面留下大块空白。
2. 配色校正为银白底、灰紫控件、夜蓝主操作和古金页眉细线；错误提示仍使用语义红色。Android 管理器的系统强调色、状态栏和导航栏也改为夜蓝，管理页保留原生触屏纵向布局。没有增加图片或依赖，也没有更改设置模型、启动行为或存档逻辑。
3. 修复布局重构末尾的 PowerShell 尺寸构造与函数调用语法。实窗截图 `_analysis\dumps\windows-manager-redesign.png` 显示游戏页窗口 `976 × 467`，状态栏紧跟页面内容。真实控件回归中三页外框高度设置/游戏/存档=`433/467/591`，并验证 FPS/窗口设置落盘与存档列表。
4. 只读取 Windows 真实存档，看到金币 `140586` / 脑子 `4410`；没有写入、备份或恢复真实存档。静态检查与 UI 自动化通过不等于主人已做游戏内实测；本次不据此宣称游戏效果变化。
5. `_analysis\_ensure_bom.ps1`、`GameManager.ps1 -SelfTest`、`_analysis\_verify_layout.ps1`、`_analysis\_verify_layout_match.ps1`、`_analysis\_device_size_roundtrip.ps1`、`_analysis\_gui_controls_test.ps1`、`Release\GameManager.ps1 -SelfTest`、`_analysis\_verify_release.ps1` 均 PASS。Release 运行验证等待 45 秒，窗口出现且进程存活，无 panic；测试后 Release sandbox 已恢复。开发版与 Release 管理器都是 141,807 B / SHA-256 `11F19771E083EBEDC1B0850B540DA12C1B2C746F02FE72230652957D7CB81BEC`。`git -c core.whitespace=cr-at-eol diff --check` PASS。没有发布新的 GitHub Release。
6. Android `ManagerActivity.java` 原已采用银白/灰紫/夜蓝/古金；本次只将 `zf_styles.xml` 系统强调色及状态/导航栏改为夜蓝。快捷构建、`_verify_android_package.ps1` 与隔离 instrumentation 30 项 PASS。MuMu `127.0.0.1:5557` 覆盖安装成功，设备 `base.apk` SHA-256 与本地相同：`2AB94757AC8DAC964823356E5AD74E96FCF454E3187128C46A2EB1FB8CA775BF`；APK 为 97,299,598 B，内置 IPA 哈希仍为 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`。首页截图 `_analysis\dumps\android-manager-night-blue.png` 显示夜蓝状态栏/导航栏和管理页；没有启动游戏或操作存档，真实 Android sandbox 未读取或写入。

## 23. 交接后追加（2026-10-07，Windows 启动器异常复核）

1. 主人反馈启动器弹出 .NET 异常：“Visual Style handle creation operation did not succeed.” 截图没有展开 `Details`，因此没有异常调用栈。
2. 对当前开发脚本执行 `GameManager.ps1 -SelfTest`、真实 GUI 控件回归（含日/夜按钮来回切换两次）均 PASS；通过 `游戏管理.exe` 启动开发版和 `Release\游戏管理.exe`，窗口正常出现、没有控制台或异常对话框。当前无法复现该异常，不能仅据静态/自动化通过断言用户机器上的触发条件已根治。
3. 定位到开发版 `GameManager.ps1` 为 150,540 B，而旧 `Release\GameManager.ps1` 为 146,204 B。已用 `_analysis\_build_release.ps1` 重建 Release，两个脚本现在字节数及 SHA-256 一致；`_analysis\_verify_layout.ps1`、`_analysis\_verify_layout_match.ps1` 与 `_analysis\_verify_release.ps1` 均 PASS。Release 验证只运行其自身包内副本，测试后 sandbox 已恢复。
4. `_analysis\_gui_controls_test.ps1` 增加日/夜按钮的实际 Win32 点击及异常对话框检查。`_analysis\_no_console_test.ps1` 改用 `[System.Diagnostics.Process]::Start()` 并正确采用 `-Root`，可独立检查开发目录或 `Release\` 启动入口；这样也避开本机 `Start-Process`/`NO_PROXY` 问题。测试夜间状态最后已恢复为 `launcher_night_mode.txt=0`。
5. 若异常仍能在当前重建的 Release 复现，需要展开异常窗的 `Details` 获取调用栈；目前截图提供的消息不足以确认是否仍是相同运行版本或触发路径。静态检查通过不等于异常根因已证实修复。

## 24. 交接后追加（2026-10-07，夜间模式控件白边）

1. 主人指出夜间模式的设置页仍有刺眼白线/白方块，存档页也有亮白表头空块。实窗复核确认：组合框 Windows 主题边框/箭头分隔线不受普通 BackColor 控制；存档 ListView 表头列宽总和短于控件宽度，剩余区域由系统绘成白色。
2. `PaletteComboBox` 去除原生 `WS_EX_CLIENTEDGE` / `WS_BORDER`，由主题颜色绘制外框与箭头，并把箭头背景向左覆盖系统留出的单像素白线。存档表格最后一列扩展到控件右边缘；夜间分隔线由 RGB `62,75,69` 降至 RGB `49,59,56`。没有更改选项写入、游戏启动或存档行为。
3. 截图 `_analysis\dumps\windows-night-after-settings.png` 与 `windows-night-after-saves.png` 用于开发版核验；Release 重建后副本与开发版相同。设置页组合框原白色像素实测从 RGB `255,255,255` 变为表面色 RGB `38,46,48`，存档表头右侧白块消失。截图尺寸分别为 976 × 433 与 976 × 591。
4. `_analysis\_ensure_bom.ps1`、`GameManager.ps1 -SelfTest`、`_analysis\_gui_controls_test.ps1`、`_analysis\_verify_layout.ps1`、`_analysis\_verify_layout_match.ps1`、`Release\GameManager.ps1 -SelfTest`、`_analysis\_verify_release.ps1` 均 PASS；控件回归验证三页高度、设置落盘、存档条目及日夜切换。Release 测试后 sandbox 已按脚本恢复。真实存档只读取，未启动游戏或写入存档。夜间效果由开发版实际截图和控件像素采样确认；交付包的 `GameManager.ps1` 已逐字节同步。

## 25. 交接后追加（2026-10-07，Windows 标题栏随日夜模式）

1. 主人询问窗口最上方系统标题栏能否更改颜色。该区域由 DWM 绘制，WinForms 的 `Form.BackColor` 不控制它。
2. 新增 `WindowChrome` DWM 调用：日间恢复系统默认 caption/text/border 颜色；夜间模式设置标题栏底色为管理器深色背景、文字为浅色前景、边框为夜间分隔色。通过 `DWMWA_USE_IMMERSIVE_DARK_MODE`（不支持时回退属性 19）与 Windows 11 caption/text/border color 属性实现；颜色值由 C# 按 COLORREF 正确打包，避免 PowerShell byte 位移丢失高位。
3. 当前 Windows 11 23H2 / build 22631 实窗验证：夜间标题栏为深灰底、浅色系统标题与按钮；日间标题栏恢复浅色系统样式。截图 `_analysis\dumps\windows-night-titlebar-settings.png` 和 `windows-day-titlebar-settings.png`。旧版 Windows 若不支持 caption color 属性，会保留系统可用的沉浸式深色模式，精确标题栏颜色由系统决定。
4. Release 已通过 `_analysis\_build_release.ps1` 重建；`_analysis\_verify_release.ps1` 与 `_analysis\_gui_controls_test.ps1` PASS，后者实际切换日夜两次，无异常；Release sandbox 由验证脚本恢复。`git -c core.whitespace=cr-at-eol diff --check` PASS。没有启动游戏或写入真实存档。

## 26. 交接后追加（2026-10-07，双平台默认夜间与清洁发行存档）

1. README 分开写清设备分辨率：iPhone 原生 `480×320`；iPad 原生 `1024×768`，iPad ×1.5 才是 `1536×1152`。Android 首页截图改用 `_analysis\dumps\android-manager-night-relaunch.png` 的夜间管理器实拍。两端首次启动管理器都默认夜间；Windows 通过未创建 `launcher_night_mode.txt` 时默认 `$true` 实现，Android 新安装偏好默认 `true`，已有用户保存过的显式主题选择继续保留。Windows 按钮显式设置 `MiddleCenter` 与零 Padding。
2. 发现并修正公开存档泄露来源：`_analysis\_build_release.ps1` 原会把开发机 `touchHLE\touchHLE_sandbox\...\saveGame.bin2` 复制进 Windows Release。现在 Release 从空 `touchHLE_sandbox` 构建，玩家首次进入游戏再自行生成进度；Release verifier 强制 sandbox 中没有文件。Android APK 本身只内置 IPA，不允许出现 `touchHLE_sandbox`、`sandbox/` 或 `saveGame.bin2` 条目，静态验证器已加断言。后续任何发行包都不要读取或复制工作目录真实 sandbox。
3. 修复后 Windows ZIP 为 `95,055,963 B`，SHA-256 `0FC4DC8E3EF544C3945651F04434D883181586120E836E6953BBE374FBA49924`，42 个文件、0 个 sandbox/save 条目；Android APK 为 `97,302,385 B`，SHA-256 `8644CB871D01C0DDFD28C7E4ED80620865EA2E6FB2B471EE8EA6823F1E96FED6`。两者已重新上传到现有 `v29fix-platforms`，Release 说明、GitHub 首页也已更新。Assets API 下载回读的两份文件大小和 SHA-256 均与本地一致；直接 release 下载域名当时连接超时，API octet-stream 下载成功。
4. 验证：BOM/Syntax、`GameManager.ps1 -SelfTest`、`_verify_layout_match.ps1`、`_verify_release.ps1`、`_verify_android_package.ps1`、`_gui_controls_test.ps1`、`git diff --check` PASS；Release standalone launch 45 秒仍存活。工作目录 `touchHLE\touchHLE_sandbox` 未被构建/测试写入，SelfTest 显示真实存档金币 `140586` / 脑子 `4410` 且只读。新截图显示 Android 夜间模式，但本次 MuMu 未连接，因此没有做 APK 新默认主题的设备端启动验证。
5. GitHub `master` 为 `3cae4df063a6ab95cc499f5ffbe1f6f6695b2050`；包含本批代码与 README 更新的 tree `abf3e979bf801cd6ec65c98d1ee172d235310396`。`process.md` 最新批次 #30。

## 27. 交接后追加（2026-10-07，Windows 日夜图标绘制居中）

1. 主人指出之前的 `TextAlign=MiddleCenter` 并未让 Segoe MDL2 Assets 太阳字形视觉居中。现清空按钮文字，`Paint` 事件用 `TextRenderer.DrawText` 配合 `HorizontalCenter | VerticalCenter | NoPadding | SingleLine` 在 `ClientRectangle` 画 Tag 中的太阳/月亮字形；换主题后显式 `Invalidate()`。不要恢复为 Button.Text 绘制。
2. 日间窗口实拍 `_analysis\dumps\windows-day-icon-centered-review.png`，图标在边框客户区内目视居中。`GameManager.ps1 -SelfTest` 与 `_analysis\_gui_controls_test.ps1` PASS；重建 Release 后 `_analysis\_verify_release.ps1` 运行 45 秒通过，布局匹配 PASS。截图前将 `launcher_night_mode.txt` 字节快照，临时日间取图后原字节写回。
3. Windows ZIP 重建后 42 个文件且不含 sandbox/save，`95,056,542 B`，SHA-256 `92C6D2B2D541B3C332DA1427DF4D8A447B89309B481A0446F5726A91D7F4D477`。已替换 `v29fix-platforms` 的 Windows 附件并更新 Release body 哈希；GitHub Assets API 下载回读大小和哈希完全匹配。Android 附件未改。
4. 本节代码、说明及 Windows ZIP 已同步到 GitHub：`master` 已包含按钮绘制修复，`v29fix-platforms` 使用上述新 ZIP；`process.md` 最新 #31。真实游戏 sandbox 未读写。

## 28. 交接后追加（2026-10-07，月牙光学中心补偿）

1. 主人指出月亮虽然轮廓居中，视觉上仍偏。按夜间实窗截图对按钮客户区的 glyph 色彩权重采样：旧月牙重心在 `(928.66, 62.72)`，客户区中心 `(927, 61.5)`，偏右 `1.66 px`、偏下 `1.22 px`。太阳色心 `(926.99,61.48)` 已居中。
2. 只对月牙 glyph (`U+E708`) 按 `Graphics.DpiY / 96` 应用 `(-1.65,-1.20)` px 光学补偿。新截图 `_analysis\dumps\windows-night-icon-optically-centered.png` 的月牙色心为 `(927.10,61.36)`，距离中心 `(0.10,-0.14) px`；可见轮廓边距左/右为 `8/11 px`，由于月牙开口形状不对称，判断以色心而非包围框为准。日间太阳继续保持边距 `9/9 px`、色心偏差 `(-0.01,-0.02) px`。
3. `_analysis\_ensure_bom.ps1`、`GameManager.ps1 -SelfTest`、`_analysis\_gui_controls_test.ps1`、`_analysis\_build_release.ps1`、`_analysis\_verify_release.ps1`、`_analysis\_verify_layout_match.ps1` 均通过；空 sandbox、Release 45 秒 standalone 正常。重新打 Windows ZIP 42 个文件，无 sandbox/save；最终 `95,057,453 B` / SHA-256 `84DE88543BF3D302657E6681F72E28D77F7E3EA5063995A1ECDBCB30B72F4461`，应替换 §27 记载的旧 ZIP。
4. 最终 ZIP 已替换 `v29fix-platforms` 同名附件：`95,057,453 B` / SHA-256 `84DE88543BF3D302657E6681F72E28D77F7E3EA5063995A1ECDBCB30B72F4461`；Assets API 下载回读字节与本地一致。源码已同步 GitHub `master`；`process.md` 最新 #32。真实游戏 sandbox 未读写。
