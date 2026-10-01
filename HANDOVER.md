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

**没有未完成的阻塞项。** 下一步等主人实机反馈。

---

## 1. 目录结构（当前实际状态）

```
touchHLE-zombiefarm/
├── TECHNICAL.md                  ★ 主文档：技术细节 + 血泪教训（11 章，最大的文件）
├── process.md                 ★ 历代改动流水账，一行一个批次（最新 #29）
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

**文档命名口径**（本会话订正过，别再改回去）：

- 本项目跑的是**原版**《僵尸农场》（Zombie Farm）。`ZFR` 是**游戏自己的 bundle 代号**，
  来自 `Payload/ZFR.app/Info.plist`（`CFBundleIdentifier` = `com.playforge.ZombieFarm.ZFR`，
  `zh-Hans` 显示名 = `僵尸农场`，`zh-Hant` = `殭屍農場`）—— **不要把 `ZFR` 展开成任何词**。
- **「Reforged」只指 `actualdoctornerd-ai/Zombie-Farm-2-Reforged`**（另一位粉丝从零重写的
  TypeScript 项目），**不是本项目**。README 与 Release 说明里都有显式辟谣句，别删。
- 配套的**汉化脚本**是主人另一个仓库
  `Ashena1017/zombie-farm-reforged-translation-cn`（Tampermonkey 用户脚本，精翻，
  词库取自原版官方简体中文语言包），在 README 的「想玩原版还是重制版」小节里推荐。

