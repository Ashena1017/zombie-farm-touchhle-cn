# touchHLE-zombiefarm

在 Windows 上用 [touchHLE](https://touchhle.org/) 模拟器运行《僵尸农场》（Zombie Farm，
游戏自报的 bundle 代号为 `ZFR`，bundle id `com.playforge.ZombieFarm.ZFR`）中文版，
并对游戏 IPA 做**二进制补丁**：修复崩溃、统一界面字号、改善中文本地化。

本文件是给**新会话**的入口文档。读完它应当能理解：项目在做什么、产物在哪、怎么改、以及踩过哪些坑。

> **这是技术细节与教训的全集**（11 章），查具体问题时再进来。
> **想先了解项目本身，请回 [`README.md`](README.md)。**
>
> **新会话请先读 `HANDOVER.md`**（2026-09-23）：那是更短的交接稿 ——
> 当前状态、关键事实与哈希、常用工作流（改管理器/改模拟器/重建交付包/跑验证）、
> 这台机器的环境坑、文档地图，以及"建议的起手式"。
>
> **要把项目交给一个全新会话？** 直接复制 `交接提示词.md` 里的 prompt 粘贴过去，
> 里面有「完整版 / 极简版 / 只报 bug 版」三种开场白。

### 目录结构

**开发树与交付包 `./Release` 同构**：模拟器相关的一切都在 `touchHLE\` 里，
外面只放游戏管理相关的东西。（2026-09-20 重构；见 `_analysis/_reorg_touchhle.py`。
同日 `zombie_farm\` 改名 `zombie_farm_ipa\`，见 `_analysis/_rename_ipa_dir.py`。）

```
（根目录 = 游戏管理侧）
├── TECHNICAL.md                     ← 本文件
├── process.md                    用户反馈批次的进度清单
├── 游戏管理.exe                  ← 图形化管理界面（推荐入口，双击即可，无黑窗）
├── GameManager.ps1               全部功能：界面 + 设置 + 存档管理 + 金币 + 启动（单文件自带）
├── launcher_selected_ipa.txt     记住上次选的 IPA（自动生成）
├── StartZombieFarmNextHour.ps1   命令行启动器（界面已不依赖它，见下）
├── RestoreTestSave.ps1           测试前还原参考存档
├── SetZombieFarmCurrency.ps1     改金币/资源
├── 运行游戏.bat / 选择跳过时间并启动.bat / 使用教程.txt
├── MSVCP140.dll / VCRUNTIME140*.dll    VC++ 运行库
├── zombie_farm_ipa/              IPA 谱系 + 每代的 report.json（2026-09-20 由 zombie_farm\ 改名）
├── tools/                        活代码：patcher + 反汇编基础设施（28 个模块 + _zt/）
├── _analysis/                    分析/诊断/验证脚本 + 历史输出，见 _analysis/README.md
├── Release/                      交付包（由 _analysis\_build_release.ps1 生成）
│   └── 使用说明.html             ★ 给使用者的说明书（构建产物，源在 _build_release.ps1
│                                    的内嵌模板里）。设置的全部解释都在这里 ——
│                                    管理器界面上没有「?」按钮，见 §1.3。
└── touchHLE/                     ★ 模拟器相关的一切
    ├── touchHLE.exe (+4 个 .backup-* 回滚点) / touchHLE_fork.exe
    ├── touchHLE_dylibs/  touchHLE_fonts/  touchHLE_sandbox/（存档在这里）
    ├── touchHLE_options.txt  touchHLE_default_options.txt
    ├── touchHLE_log.txt  zfr_last_run.log  zfr_last_launch.txt
    ├── touchHLE_time_offset_seconds.txt / zfrpatch_current.dylib / LICENSE
    ├── touchHLE-fork/            模拟器源码（上游 fa3d095，含 ZFR 适配 + 60fps 修复）
    │   └── vendor/               构建依赖（stb/boost/openal-soft/SDL/dynarmic/PVRTDecompress）
    └── _build_tools/             自包含 rust/cmake 工具链与 cargo 缓存（可删）
```

> **`touchHLE-trunk/` 已删除**（2026-09-23）：那是主人下载的上游 trunk 源码，仅作参考、
> **不含 ZFR 适配**，而且里面有两个**针对 AI 的提示注入文件**（`AGENTS.md`、`CLAUDE.md`，
> 谎称 touchHLE 是某种病原体缩写并要求"必读"）。删除前确认过：fork **没有任何代码或脚本**
> 依赖它。
>
> ⚠️ **删除时踩到的坑（已修）**：fork 的 `vendor/{stb,boost,openal-soft,SDL}` 原本是
> **NTFS junction，指向 trunk 的 vendor**（`_build_fork.ps1` 当年为省下载量这么做的）。
> 删掉 trunk 后这四个依赖变成**死链接**，编译立刻挂在
> `lib.c(12): fatal error C1083: 无法打开 ../../../vendor/stb/stb_image.h`。
> 已用 `_analysis\_restore_vendor.ps1` 把它们**重新抓成 fork 自己的真实目录**
> （stb 449 / boost 74085 / openal-soft 498 / SDL 1743 个文件，按上游 pin 的 commit），
> fork 从此**完全自包含**；`_build_fork.ps1` 也改成只做存在性校验，不再创建 junction。

> **为什么 `touchHLE\` 能这么放**：touchHLE 的资源是从**当前工作目录**
> （`src/paths.rs` 在 Windows 上返回 `Path::new(".")`）解析的，**不是** exe 所在目录。
> 所以只要启动时把工作目录设成 `touchHLE\` 就行 —— 这一点 `GameManager.ps1`、
> `StartZombieFarmNextHour.ps1` 与各测试脚本都显式做了（`$script:HleDir` / `$hleRoot`）。
> 反例：工作目录留上一级会 panic
> `Unexpected I/O failure ... "touchHLE_dylibs/libz.1.2.3.dylib"`。

> **脚本里的 `$hleRoot`**：为兼容两种布局，所有脚本都写成
> `$hleRoot = if (Test-Path (Join-Path $root 'touchHLE\touchHLE.exe')) { Join-Path $root 'touchHLE' } else { $root }`。
> 新写脚本**照抄这个模式**，不要硬编码 `touchHLE\`，也不要把模拟器路径直接接在 `$root` 后面。
> 同理：**启动 touchHLE 的 `WorkingDirectory` 必须是 `$hleRoot`**，跑 GUI 的才是 `$root`。

**根目录不要再堆临时脚本和输出** —— 分析脚本放 `_analysis/`，历史输出放
`_analysis/dumps/`。

> ⚠️ **改任何含中文的 `.ps1` 后必须跑 `_analysis\_ensure_bom.ps1`。**
> PowerShell 5.1 会把**无 BOM** 的 `.ps1` 按 GBK 解码，中文里的字节可能被读成
> 引号，导致满屏 `Unexpected token` 假语法错误。`edit` 工具会剥掉 BOM，所以
> 每次编辑后都要跑一次（它同时做语法检查，以及所有启动器动作的验证）。

---

## 一、快速开始

**推荐：双击 `游戏管理.bat`**，用菜单完成所有事情（启动、跳时间、改帧率、
改窗口大小、改金币），不需要记任何参数。

也可以直接用原来的 bat：

```
运行游戏.bat              # 用当前累计时间偏移启动
选择跳过时间并启动.bat     # 输入 HH:MM 快进游戏时间
```

两者都调用 `StartZombieFarmNextHour.ps1`：

```powershell
.\StartZombieFarmNextHour.ps1 -NoSkip                 # 不跳时间
.\StartZombieFarmNextHour.ps1 -Hours 6 -Minutes 15    # 快进 6h15m
.\StartZombieFarmNextHour.ps1 -Hours 1 -Reset         # 重置累计偏移后再加 1h
.\StartZombieFarmNextHour.ps1 -Interactive            # 交互输入
```

脚本第 12 行的 `$game` 决定跑哪个 IPA —— **这是切换版本的唯一开关**。

时间偏移累计写在 `touchHLE_time_offset_seconds.txt`，通过环境变量
`TOUCHHLE_TIME_OFFSET_SECONDS` 传给 touchHLE。

### 图形化管理界面（游戏管理.bat）

双击 **`游戏管理.exe`** 打开一个 WinForms 窗口。它编译为 GUI 子系统程序
（`/target:winexe`），所以**不会出现黑色命令行窗口**——连同下面的"启动游戏"
一起，全程无黑窗（已实测：运行期间控制台窗口数保持 0）。

```
┌─ Zombie Farm 游戏管理 ─────────────────────────────────┐
│ 游戏 │ 存档管理                                          │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 游戏版本 (IPA)                                       │ │
│ │   [Zombie Farm ZFR ...v28fix.ipa        ▾] [浏览…]   │ │
│ │   app id: com.playforge.ZombieFarm.ZFR  可执行文件: ZFR │ │
│ │                                                    │ │
│ │ [启动游戏]  [启动并跳过时间…]                         │ │
│ │                                                    │ │
│ │ 设置                                                │ │
│ │   游戏帧率        60 帧        自定义帧率 [75] 帧      │ │
│ │   滚轮缩放倍率     ×1.1（默认）  自定义倍率 [1.10]     │ │
│ │   窗口大小/分辨率  iPad（平板）▾ ×1.5 ▾ 7/4  窗口 1536 × 1152│ │
│ │   显示模式        窗口模式                            │ │
│ │   高速帧率修复     开启                               │ │
│ │                                                    │ │
│ │ 金币与脑子  金币 [______] 脑子 [______] [写入存档]     │ │
│ └────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

**窗口大小 / 分辨率**是一行两个下拉框：左边选 **iPad（平板）** 或
**iPhone（手机）**（= `--device-family`），右边选放大倍数
（= `--scale-hack`），行尾实时显示这个组合产生的窗口大小。

倍数预置 **×1.25、×1.5、×1.75**（**小数**写法），外加**自定义**
（可填小数 `1.6` 或分数 `7/4`，范围 1.00–3.00）。
默认 **iPad + ×1.5 = 1536 × 1152**。

**滚轮缩放倍率**（= `--zf-wheel-zoom-step`，默认 **1.1**）：鼠标滚轮每格把农场
地图缩放乘以多少。预置 ×1.1 / ×1.2 / ×1.5，外加自定义（1.01–2.00）。

> **界面上没有「?」按钮。** 全部说明文字都在交付包里的 **`使用说明.html`**
> （第二节「设置都是什么意思」逐个设置讲原理与注意事项），
> 由 `_analysis\_build_release.ps1` 的内嵌模板生成。
> 这样管理器只有一个职责，说明可以写得更长、能搜索、能复制。
> `-SelfTest` 里有「没有任何设置定义 `Tip`」的断言，`_gui_tip_test.ps1` 里有
> 「界面上没有 `?` 按钮」+「指南里确实写到了这些设置」的双向断言 ——
> 防止说明文字两边都不见了。

**游戏版本 (IPA)**：下拉框列出 `zombie_farm_ipa\` 里所有 `.ipa`（当前 33 个），
选中即生效并**记住**（存在 `launcher_selected_ipa.txt`），下次打开还是它。
「浏览…」可以选文件夹外的 IPA。

> ⚠️ **换 IPA 可能同时换掉设置和存档。** `zombie_farm_ipa\` 里有 **3 个不同的
> bundle id**：
>
> | app id | 文件 |
> |---|---|
> | `com.playforge.ZombieFarm.ZFR` | 31 个（v2 … v29fix 主线） |
> | `com.playforge.ZFR.LZ54D2GT3D` | `ZFR 1.0.zh-CN-unsigned.ipa` |
> | `com.playforge.ZombieFarmChinese` | `Zombie_Farm_1.181.modified.ipa` |
>
> touchHLE 的 options 文件按 app id **精确匹配**，存档目录也按 app id 命名。
> 所以切到少数派 id 时，**60 帧设置不适用、存档也是另一个目录的**。
> 下拉框会把这些少数派 id 直接标在名字后面提醒。
> 界面下方那行 `app id:` 永远显示当前实际生效的 id。

**存档管理**标签页：

```
当前存档：saveGame.bin2  3885 字节  2026-09-16 20:09:56
[新增备份] [还原所选备份] [删除所选] [刷新]
┌──────────────────────────────────────────────────┐
│ 类型        备份文件                    大小   时间 │
│ 正在使用    saveGame.bin2              3885  09-16 │  ← 绿色加粗
│ 备份        saveGame.bin2.bak-...-pre9 3034  09-16 │
│ ...                                              │
└──────────────────────────────────────────────────┘
[全选备份] [取消选择] [反选]          已选 3 / 14 个备份
```

- 第一行永远是**正在使用的**存档（绿色加粗），它**不可还原、不可删除**
- **支持多选**：`全选备份` / `取消选择` / `反选`，可一次删除多个
- 删除多个时会列出前几个文件名再确认，避免误点"全选"后追悔莫及
- 还原一次只能选一个（还原两个存档没有意义，会提示）
- 还原前会**自动把当前存档另存一份**，所以还原本身也可以反悔

**改动立即保存**，没有"确定/应用"按钮——关掉窗口不会丢失任何修改。

#### 设置存在哪里

存在 **`touchHLE_options.txt`** 里这一行（touchHLE 自带的 per-app 机制）：

```
com.playforge.ZombieFarm.ZFR: --fps-limit=60 --device-family=ipad --scale-hack=1 --non-blocking-zero-timeout-run-loop
```

**只影响 Zombie Farm**，其它行（注释、其它游戏）原样保留。这样设置也适用于
不经本启动器、直接运行 touchHLE 的情况，而且只有一处需要查。

> ⚠️ 启动器**不再传 `--device-family`**。命令行选项优先级高于 options 文件
> （源码 `lib.rs` 里顺序是 default_options → user options → 命令行），
> 以前硬编码的 `--device-family=ipad` 会**静默压掉**界面里的设置。

| 设置 | 取值 | 说明 |
|---|---|---|
| 游戏帧率 | 30 / 60 / 90 / 120 / 不限帧 / **自定义** | 选「自定义」后右侧数字框可填 1–1000 任意帧率 |
| 窗口大小 / 分辨率 | **左**：iPad（平板）/ iPhone（手机）<br>**右**：×1.25 / ×1.5 / ×1.75 / **自定义** | 两个下拉框 = `--device-family` + `--scale-hack`；行尾实时显示窗口大小。默认 iPad + ×1.5 = 1536×1152。自定义可填 `1.6` 或 `7/4`，范围 1.00–3.00 |
| 滚轮缩放倍率 | ×1.1（默认）/ ×1.2 / ×1.5 / **自定义** | = `--zf-wheel-zoom-step`，滚轮每格的缩放乘数，1.01–2.00 |
| 显示模式 | 窗口 / 全屏 | |
| 高速帧率修复 | 开 / 关 | **ZFR 必须开**，否则只有 30 帧 |

> **倍数是小数，但底层存的是分数。** 界面上的 ×1.25 / ×1.5 / ×1.75 原样写进
> options 文件。touchHLE 收到后**约分成分数**参与运算（1.5 → 3/2、1.25 → 5/4），
> 所以窗口与 renderbuffer 仍然严格一致、不会因浮点产生一个像素的偏差。
> 反过来，手写的分数（`13/8`、`7/4`）也照旧接受并在界面上显示为自定义 ——
> 这正是为什么自定义框是文本框而不是数字框：数字框表达不了分数，
> 而把它四舍五入成小数会**悄悄改变窗口尺寸**。

窗口大小这一项的**两个控件**就是 **`--device-family` + `--scale-hack`**：前者定 UI idiom
与模拟屏幕，后者把它放大成窗口（`窗口 = 模拟尺寸 × scale-hack`）。行尾那个
`窗口 1536 × 1152` 是**实时算出来的**，用的算法与模拟器 `options.rs` 的 `scale_dim`
一致（见下文「窗口大小标签」）。

**滚轮缩放倍率**对应本项目给模拟器加的 `--zf-wheel-zoom-step=` 选项：滚轮驱动的是游戏
自己的 `-[ZFFarmTileMap setZoomOutAmount:]`（与双指捏合同一个方法），倍率是**乘法**
（每格 `当前 × 倍率`），所以在任何缩放级别手感一致。默认 1.1 → 从 1.0 到上限 2.0 约 8 格；
原来的硬编码值是 1.08。

### 窗口大小标签（`Get-WindowSizeForScale`）

行尾的 `窗口 W × H` 不是查表，而是按**与模拟器相同的算法**现算的：

- 取向是**横向**（启动器传 `--landscape-right`），所以 `宽 = 设备高 × 倍率`、
  `高 = 设备宽 × 倍率`；
- 倍率按**分数**做精确运算（`1.5` 与 `7/4` 都是精确有理数），四舍五入规则与
  `scale_dim` 的「加半个分母再整除」一致，因此分数倍率不会差一个像素；
- `3/2` 与 `1.5` 这种同一倍率的两种写法必须给出同一个窗口（`-SelfTest` 有断言）。

算出来超过当前屏幕可用区域时标签会**变成琥珀色**（`Update-WindowSizeLabel`），
这是启动前唯一能看出"这个组合放不下"的地方。

### ⚠️ 这游戏是固定分辨率的 —— 只能放大窗口，不能放大画布

**这是本项目踩过的最贵的一个坑，两个看似正确的方案都是错的。**

游戏界面按 **点**（point）排版：iPhone 480×320、iPad 768×1024，图片素材也是固定大小。
实测 IPA 里 **806 张 PNG，最大的只有 1024×768**（主菜单背景 `MainMenuBG.png` 是
1024×683），**宽度中位数仅 88px**。而 `UIScreen.bounds` 是把模拟尺寸**原样**报给游戏的
（`ui_screen.rs`）。所以：

| 做法 | 模拟尺寸（游戏看到的） | 结果 |
|---|---|---|
| ❌ 调大 `--device-size` | 变大（如 1620×1080） | 游戏拿到更大的画布，却仍按原生点数画固定尺寸的 UI，背景图被拉伸铺满 → **UI 缩成一小撮 + 画面被"拉扯"** |
| ✅ 调大 `--scale-hack` | **保持原生** | 排版完全不变，只是渲染分辨率和窗口变大 → **画面正确** |

所以 16:9 那几档（以及任何"把 `--device-size` 调大"的做法）看起来坏掉，**不只是裁切
问题**：即使比例对（3:2），把画布调大仍然会让 UI 变小。**必须用 `--scale-hack`。**

> **补充（后经实测）**：`--device-size` 一旦设定，游戏还会**退回 iPhone 排版**，无论
> `--device-family` 给的是什么。这就是"自定义分辨率"全都不对的第二重原因。因此现在
> **完全不使用 `--device-size`** 来定尺寸。

### ⚠️ 用 iPad 档，不要用 iPhone 档

主人实测反馈：iPhone 档放大后「**画面排布会非常糟糕**」（logo 变小、HUD 挤在一起），
同样倍数换成 **iPad 档就正常**。所以默认档是 **iPad + ×1.5**；iPhone 档仍然保留
（偶尔想对照原版手机排版时有用），但**不推荐**在放大时使用。

> 界面因此把两件事**分开**给使用者选：左边是"模拟哪台设备"（只有 iPad / iPhone 两项，
> 因为 `--device-family` 本身就只有这两个值，没有"自定义"可言），右边才是倍数。
> 两个下拉框 + 行尾的实时窗口大小，读起来仍是"选一个窗口尺寸"这一件事。

### ⚠️ 放大倍数用小数（底层是本项目对模拟器的扩展）

iPad 屏幕是 1024×768，整数倍只有 ×1 = 1024×768 和 ×2 = 2048×1536 —— 而 **×2 放不进
2560×1440 屏幕**（外框约 2070×1592，可用高度只有约 1368），中间是空的。所以本项目的
模拟器给 `--scale-hack` 加了**小数/分数支持**（`1.5`、`1.25`，也接受 `3/2`、`13/8`）。

界面上三档预置统一写成**小数**（×1.25 / ×1.5 / ×1.75），因为"×1.5"比"×3/2"更直观；
写进 options 文件的就是这些小数。之所以用**有理数**而不是浮点：scale-hack 同时决定
窗口大小和 renderbuffer 大小，两者必须严格一致，touchHLE 把小数约分后按整数运算，
不会积累舍入误差（`options.rs` 的 `parse_scale_factor` / `scale_dim`）。

### ⚠️ 放大不等于变清晰

实测把 ×2 的画面缩回 ×1 比对，**像素差仅 1.23/255（0.3%）** —— 也就是说放大**只是把
同样的画面变大**，不会增加细节。游戏素材本身只有 1024×768 级别，放大 1.5 倍以上会开始
发虚。想要真正更精细的画面，只能**替换素材**或**重写游戏**（见 README 末节）。

### 🐛 已修：放大后光源"飘"在屏幕上（framebuffer 感知的 scale-hack）

**症状**：`--scale-hack` 大于 1 时，陵墓门口的绿火、农夫手上的提灯等**发光贴图**与场景
错位，像是浮在屏幕上；用原生 iPad 尺寸（`--scale-hack=1`）打开则完全正常。

**根因**（用 `TOUCHHLE_ZF_GL_TRACE=1` 实测出来的，不是推断）：这游戏每帧都用
**自己的 framebuffer object 做 render-to-texture**。它在 drawable 上设好 viewport，
然后绑定自己的 FBO 继续画，**不再重设 viewport**。而 GL 的 viewport 是**上下文的粘滞
状态**，不属于某个 framebuffer。老实现无条件把所有 `glViewport`/`glScissor` 乘以
scale-hack，于是：

- 绑到 **drawable 的 FBO**（renderbuffer 由 touchHLE 自己按 `逻辑尺寸 × scale` 分配）→ 放大正确；
- 绑到 **app 自己的 FBO**（挂的是它自己 1024×1024 的纹理，touchHLE 无法把它变大）→ 仍旧
  沿用上一个被放大成 1536×1152 的 viewport，**比目标纹理还大**，这一趟 pass 就被裁切／错位。

scale-hack=1 时两个空间恰好重合，所以原生尺寸看不出问题。

**修法**（`gles_guest.rs`）：

1. 记录 guest 请求的 viewport 原始矩形（`zfr_gl_set_guest_viewport`）。
2. 每次 `glBindFramebufferOES` 都**按新渲染目标重新推导** host viewport
   （`apply_guest_viewport`）—— 补偿 viewport 的粘滞性。
3. `zfr_gl_framebuffer_is_scaled` 判断当前 FBO 的颜色附件是谁：
   只有 **touchHLE 自己分配的 drawable renderbuffer**（`eagl.rs` 在
   `renderbufferStorage:fromDrawable:` 里登记）才允许放大；**app 自建的纹理／
   renderbuffer 一律按原尺寸**。答案按 (context, fbo) 缓存，附件一变就失效。
4. `glRenderbufferStorageOES` 也**不再**放大：这条路径只会创建 app 自己要求的
   renderbuffer，drawable 的那个走 `eagl.rs`，本来就不经过这里。

实测决策（`TOUCHHLE_ZF_GL_TRACE=1`）：

```
--scale-hack=1    fbo 1 (drawable) 768x1024 -> 768x1024    scaled true
                  fbo 2 (app tex)  1024x768 -> 1024x768    scaled false
--scale-hack=1.5  fbo 1 (drawable) 768x1024 -> 1152x1536   scaled true
                  fbo 2 (app tex)  1024x768 -> 1024x768    scaled false
```

修完两边都对：drawable 照常放大到 1.5 倍，app 自己的 render target 保持原尺寸。

八档全部用 Win32 取窗口客户区**实测过**（DPI 感知），全部精确匹配：

| 界面上的选择（左 + 右） | 实测客户区 | 实现 |
|---|---|---|
| iPad + ×1.25（预置） | 1280 × 960 | `--device-family=ipad --scale-hack=1.25` |
| iPad + ×1.5（**默认**） | 1536 × 1152 | `--device-family=ipad --scale-hack=1.5` |
| iPad + ×1.75（预置） | 1792 × 1344 | `--device-family=ipad --scale-hack=1.75` |
| iPad + `5/4`（自定义，与 ×1.25 同值） | 1280 × 960 | `--device-family=ipad --scale-hack=5/4` |
| iPad + `3/2`（自定义，与 ×1.5 同值） | 1536 × 1152 | `--device-family=ipad --scale-hack=3/2` |
| iPad + `13/8`（自定义） | 1664 × 1248 | `--device-family=ipad --scale-hack=13/8` |
| iPad（原生，×1） | 1024 × 768 | `--device-family=ipad --scale-hack=1` |
| iPhone（原生，×1） | 480 × 320 | `--device-family=iphone --scale-hack=1` |

> 后三行是**同一倍率的两种写法**：`1.25` 与 `5/4`、`1.5` 与 `3/2` 各产生**完全相同**
> 的客户区。这既证明小数写法确实被 touchHLE 约分后精确运算，也证明自定义框里的
> 分数没有被四舍五入。

脚本 `_analysis/_device_size_e2e.ps1`（八档客户区）、`_analysis/_zoomfix_check.ps1`
（逐档截图：标题 + 农场 HUD + 滚轮放大/缩小）。

> **不再有"遮蔽"问题**：每个设置现在只对应**一个**命令行选项，读取时不再需要
> "取最具体匹配"那套规则。早先版本把 `--device-family` 和 `--scale-hack` 打包成一个
> `device_size` 选项组，原生档的选项集是每个放大档的子集，所以读取必须比较"具体度"，
> 否则一重排就会把 1536×1152 读成 iPad 原生档。
> `_device_size_roundtrip.ps1` 现在直接断言**没有任何 choice 带 `Extra`**（即没有哪个
> 选项会展开成多个命令行 token），以及所有 `Prefix` 互不相同。

自定义帧率实测量过：设 75 帧 → 游戏稳定跑 **75.00 fps**。
⚠️ **别选「不限帧」**，实测会跑到约 1900 帧，纯发热。

滚轮倍率也实测量过（`_zoomfix_check.ps1` + `touchHLE_log.txt` 里的 `ZombieFarm zoom:` 行）：

| 设定 | 实测每格 | 日志 |
|---|---|---|
| 1.1（默认） | ×1.1 | `1.000 → 1.100 → 1.210 → 1.331 …` |
| 1.5（自定义输入） | ×1.5 | `1.000 → 1.500 → 2.000`（到上限）`→ 1.333 → 0.889 …` |

脚本/自动化也可以非交互修改（走的是**同一套** `Save-Settings` 代码）：

```powershell
.\GameManager.ps1 -Set fps_limit=120
.\GameManager.ps1 -Set wheel_zoom=1.5                          # 滚轮每格 ×1.5
.\GameManager.ps1 -Set window_family=ipad,window_scale=1.5     # 窗口尺寸
.\GameManager.ps1 -Set window_scale=7/4                        # 分数也可以
.\GameManager.ps1 -ShowSettings       # 打印当前设置
.\GameManager.ps1 -SelfTest           # 自检（设置 + 存档管理，不需 UI）
```

> ⚠️ **`-Set` 现在会先解析当前选中的 IPA**（`Initialize-CurrentIpa`）。以前它不会，
> 于是 `-Set` 用的是文件顶部那个**占位** app id，写进 options 文件的是**另一行** ——
> GUI 和 `-ShowSettings` 读的是真正选中那行，两边**默默不一致**，改了半天没效果。
> 现在输出会带上 app id：`Saved for com.playforge.ZombieFarm.ZFR: …`。

### 🐛 已修：把「高速帧率修复」关掉后界面又自己变回「开启」

**症状**：把「高速帧率修复」选成**关闭**，options 文件确实去掉了
`--non-blocking-zero-timeout-run-loop`（模拟器也真的会按 30 帧跑），
但**重开管理器，下拉框又显示「开启」**，看起来像是没保存。

**根因**：命令行上的"开关型"选项（`--xxx`，没有 `=值`）在文件里只能表达
**有 / 没有**两种状态。读取器遇到"这一行没有这个 token"时，回退到了
`SettingDefs[key].Default` —— 而 `Default` 的语义是**推荐值**（写进新文件时用哪个），
不是"token 缺席时代表什么"。于是关掉 = 没有 token = 回退到推荐值 `1` = 显示开启。

**修法**（`Get-CurrentSettings`）：**只有当整个 app 行都不存在**时才用 `Default`
（这时还没有任何配置，第一次编辑写入推荐值）；**行存在但不含该 token** 时返回 `'0'`，
因为那正是模拟器看到的运行状态。`-SelfTest` 新增「flag 开/关往返」断言：
写 1 → token 存在且读回 1，写 0 → token 不存在且读回 0。

关于窗口大小：它改变的是**内部渲染分辨率**，窗口也随之变大（上表是 Win32 API
实测的客户区尺寸）。窗口本身**不可拖动缩放**（touchHLE 的 windowed 路径没有调
`.resizable()`）。代价是 GPU 开销约按像素数增长。

⚠️ **本机桌面是 2560×1440、150% 缩放**（注意：非 DPI 感知的进程会看到被虚拟化的
1707×960，别拿那个数当桌面尺寸）。窗口边框另占约 22×56 像素，所以 2160×1440 那一档
的外框约 2182×1496，高度超过可用区（任务栏占一条），下边会被压住；想要满高请用「全屏」。

为了让"选了多大就是多大"，本项目的模拟器把 SDL 的 `SDL_WINDOWS_DPI_AWARENESS` 设为
`permonitorv2`。不设的话 Windows 会按 150% 位图拉伸窗口 —— 选 962×642 实际得到
1443×963（糊），选 1924×1284 实际得到 2886×1926（直接超出屏幕）。该 hint 必须在
`SDL_Init` **之前**设置，否则不生效。

> **量窗口尺寸的工具也必须 DPI 感知**：`SetProcessDPIAware()` 不调用的话，读到的
> 每个窗口都只有真实值的 **2/3**（本机 150% 缩放），而且**连未改动的原生档也一起
> 等比缩小** —— 这种"自洽地错"极易被误判成功能 bug（`_device_size_e2e.ps1` 就
> 踩过，六档全 FAIL，加一行 `SetProcessDPIAware()` 后全 PASS）。

#### 为什么是 .exe 而不是 .bat

`cmd.exe` 本身是控制台程序，**任何 .bat 都会带一个黑窗**，无法在批处理里消除。
所以入口改成了 C# 编译的小程序 `游戏管理.exe`（源码 `_analysis/launcher/Launcher.cs`，
重新编译：`.\_analysis\launcher\build.ps1`）。

同理，`touchHLE.exe` 是**控制台子系统**程序，从无控制台的进程直接调用时 Windows
会为它新分配一个控制台。所以 `StartZombieFarmNextHour.ps1` 增加了 `-Quiet`：
用 `CreateNoWindow` 启动 touchHLE，并把它的输出写进 `zfr_last_run.log`。
GUI 启动游戏时走的就是这条路。

### 测试前先还原存档

游戏**只在正常退出时才写存档**，而且每次入侵/解锁都会消耗状态（比如「待解锁技能」
的池子会越来越小，抽不到东西就没法验证）。所以固定用法是：

```powershell
.\RestoreTestSave.ps1          # 归档当前 saveGame.bin2，再把参考存档换进去
.\RestoreTestSave.ps1 -List    # 看现有存档/备份
```

`Documents\saveGame.bin2.bak` 是参考存档。脚本**先归档再覆盖**，不会丢东西。

> **2026-09-20 起参考存档已不再需要**（主人明确说不用管了）。
> 那个 `.bak` 在本次会话开始前就已不存在；`_analysis\save_backups_safe\saveGame.bin2`
> 只剩 926 B、读不出任务段。**不要再去追查或"恢复"它** ——
> 沙箱里现在是主人的真实进度，测试前按需自行备份即可。
> `RestoreTestSave.ps1` 仍然可用（它会先归档再覆盖），只是缺 `.bak` 时会报错。

---

## 二、当前状态

**当前使用版本：`...fixed-fonts-v29fix.ipa`**（已由启动器指向；主人实测通过，已晋升）

| 版本 | 内容 | 状态 |
|---|---|---|
| `v3` | 基类 `ZFAlertWindow` 13 站点 → 标题 24 / 正文 18 | 已验证可用 |
| `v4` | 修复 codex 的 helper 网络 + 字号 delta 归零（20 站点） | 已验证 |
| `v5` | 14 个专用 `ZFAlertWindow*` 子类纳入 24/18（19 站点） | 已验证 |
| `v6` | 「提前解锁道具」弹窗正文 14 → 18（2 站点） | 已验证 |
| `v7diag`/`v8diag`/`v9diag` | 任务计数哨兵法诊断（仅诊断，勿用作基线） | 已完成使命 |
| `v10fix` | 试图在工厂里调用 `stopListening`；**打错了方法** | 无效 |
| `v11fix` | 重写 `stopListening`；**漏了 r0 交接，启动即崩** | 崩溃 |
| `v12fix` | 重写 `stopListening` + 修正 r0 交接（15 站点） | **已验证可用** |
| `v13fix` | 技能名走 `zfrLoc` 本地化（6 站点） | **弹窗文字消失**（见 7.5） |
| `v14fix` | 修 `getCurrentLanguage`，让 codex 的 CJK 字体分支真正生效（2 站点） | **已验证可用** |
| `v15fix` | 修 3 处乱码本地化 + 修 2 处未本地化道具名（6 站点 + 2 个 .strings 成员） | 部分有效（见 v16） |
| `v16fix` | 修 sub9 stub 的栈位移回归 + 修 `__const` 里硬编码的乱码 CFString（19 站点） | **已验证**（数字恢复正常、`+200金币` 正确） |
| `v17fix` | 修 `%@` 未本地化的入侵券提示（新 r4-safe stub）+ 修第二条经验串 ` +%d经验`（7 站点） | **已验证**（入侵券/经验飘字均正常） |
| `v18fix` | `ZFAlertWindowStorageItem` 标题 20→24、`ZFMarketMenu -checkBoughtItem:` 正文 14→18（4 站点，各改 1 字节） | #6 实测通过；#2 **无效**（那个 20.0 是布局参数） |
| `v19fix` | 修 `Arial-BoldMT.strings` 这张**字体命名字符串表**里的 8 条乱码（施肥飘字） | **已验证**（「蝴蝶僵尸施肥」「+200金币」正常） |
| `v20fix` | #4 工具条 label 右缘左移 4px（`toolName` −56→−60、`toolNameShadow` −54→−58，共 4 池） | **已验证**（`(10)` 不挡；`(9)` 偏左是右锚点正常表现） |
| `v21fix` | #2 仓库物品面板 `title1` 18→24、`body1` 12→18；#8 陵墓按钮 14→17（6 站点，每个 4 字节） | 实测：标题/说明变大 ✅、陵墓变大 ✅；但标题底部被 20px 的 dimensions 盒子裁掉 |
| `v22fix` | #7 zombie 详情页「数值/能力/力量/生命/速度」补 `setColor:(0,0,0)`（sub9 新 stub + 5 个改道点） | 实测：数值/力量/生命/速度 变黑 ✅；能力 仍白（代码里显式设白） |
| `v23fix` | 收尾：标题 dimensions 高度 20→34（新 stub）、能力标签 white→black、陵墓 17→19 | 实测：标题完整 ✅、能力变黑 ✅、陵墓够大 ✅；但标题偏上（位置公式依赖 contentSize） |
| `v24fix` | 标题位置常量 −6.0→−27.0（抵消盒子加高 21px）、陵墓**去粗体**（`AmericanTypewriter-Bold`→`AmericanTypewriter`） | 实测：标题完整但略偏下、陵墓去粗体 ✅ |
| `v25fix` | 标题位置常量 −27.0→−24.0（字顶 +3px，回到视觉中心） | 实测：仍略偏下 |
| `v26fix` | 标题位置常量 −24.0→−22.0（字顶再 +2px） | 实测：仍略偏下 |
| `v27fix` | 标题位置常量 −22.0→−20.0（字顶再 +2px） | **已验证**（标题正中间，#2 收尾） |
| `v28fix` | 把 v11 删掉的 `stopListening` 逐条注销循环**加回来**（任务闪退**根因**） | **已验证**（主人实测通过，见 5.11） |
| `v29fix` | 施肥飘字 `%@施肥` → ` %@施肥啦！`（两个 `.strings` 成员改存 OpenStep 文本） | **已验证**（主人实测通过，见 5.12）**← 当前版本** |

**已知未解决问题**见第七节（7.1、7.2、7.3/7.5 已定位）；用户反馈批次 2 的进度见
`process.md`。

> **已验证 touchHLE 执行的是 sub9（Thumb）那一片** —— 证据：v15 里只有 sub6 打了
> `%@ Used!` 的补丁却无效，而"瞬间成熟"的计数异常只可能由 sub9 stub 的栈位移造成。
> 两个 slice 仍然一起打，但**排查问题时以 sub9 为准**。

---

## 二·五、模拟器：30fps → 60fps（2026-09-19）

**游戏原本只有 30fps，现已修复为 60fps，且游戏内时间不加速。** 详见
`_analysis/reports/fps60-report.md`。

### 根因

不是性能不足，而是 touchHLE 把**零超时的 run loop 调用**实现成了阻塞调用：

- 游戏用 cocos2d 的 `CCFastDirector`，`-preMainLoop`（sub9 `0x213a30`）**每帧调两次**
  `CFRunLoopRunInMode(mode, 0.0, true)`（`0x213abc` 画之前、`0x213ae6` 画之后）
- touchHLE 的 `cf_run_loop.rs` 对 `seconds == 0.0` 走 `run_run_loop_single_iteration`，
  而每圈末尾 `ns_run_loop.rs:480` 睡 `Duration::from_millis(1000/60)` = **16 ms**
- 每帧 **2 × 16 ms = 32 ms** → **30 fps**

`--zfr-profile` 佐证：`run_loop` 5502 次 / `eagl_present_renderbuffer` 2750 次 = **2.0007**。

### 为什么游戏速度不变

`CCDirector -calculateDeltaTime`（sub9 `0x211a90`，`0x211a9e` 调用）解析到的符号是
**`_gettimeofday`**（stub `0x2d0410` → slot `0x343a00`），即 `dt` 来自**真实挂钟**。

### 修复

新增 opt-in 选项 `--non-blocking-zero-timeout-run-loop`（零超时改为让出但不等待）。
默认关闭，**不动上游默认行为**。

### 实测（同机同存档，RTX 4080）

| 配置 | 平均 FPS | 标准差 |
|---|---|---|
| 原 `touchHLE.exe` | 30.19 | 0.244 |
| 重编译版，选项关 | 30.22 | 0.247 |
| 重编译版，选项开 | **60.00** | **0.050** |
| 选项开 + `--fps-limit=off` | **1926** | — |

60fps 只多花 **0.38 % 单核**（1.87% → 2.25%），GPU 32% → 37%。
A/B/C 三组的应用 stdout 与警告**逐条相同**，零 panic。

### 源码与回滚

- `touchHLE/touchHLE-fork/` = 上游 commit **`fa3d095`**（"Fix Zombie Farm action manager corruption"，
  2026-08-19）。**注意它不是 trunk**（两者分叉 66 commit）。上游 `touchHLE-trunk/` **已删除**
  （原因见上文目录说明；它**不含** ZFR 适配，编译出来跑 ZFR 会在 `ns_dictionary.rs` 断言处直接 panic，
  而且带提示注入文件）。fork 的构建依赖现已自包含在 `touchHLE-fork/vendor/`。
- 回滚：`.\_analysis\_install_fps60.ps1 -Revert`
- 旧版备份（都是可回滚的完整 exe，按时间命名）：`touchHLE/touchHLE.exe.backup-*`
  —— `20260827`（最初版）、`fps60-20260919`（60 帧修复）、
  `precrash-20260920`、`zoom-20260923`（滚轮缩放前的最后可用版）

> ⚠️ **不要用 `--fps-limit=off`**，会跑到约 1900fps 白白发热。默认 60 即可。

## 三、IPA 谱系

全部在 `zombie_farm_ipa/`。每一代只在前一代基础上做**等宽原地改写**，所以除了 `complete-final`
之外尺寸都一致（59,564,493 字节）。

```
ZFR 1.0.zh-CN-unsigned.ipa                       58,788,319  ← 未改动的原始基线
  └─ complete-final.ipa                          59,564,496  ← codex 的 V22–V56 补丁阶梯
      └─ .fixed.ipa                              59,564,493  ← 8/28 崩溃修复
          └─ .fixed-fonts.ipa                    59,564,495
              └─ .fixed-fonts-v2.ipa             59,564,493
                  └─ .fixed-fonts-v3.ipa         59,564,493  ← 字号统一：基类
                      └─ .fixed-fonts-v4.ipa     59,564,493  ← helper 修复
                          └─ .fixed-fonts-v5.ipa 59,564,493  ← 字号统一：子类
                              └─ .fixed-fonts-v6.ipa   59,564,493 ← 解锁弹窗字号
                                  └─ .fixed-fonts-v12fix.ipa 59,564,493 ← 任务进度持久化修复
                                      ├─ .fixed-fonts-v13fix.ipa 59,564,493 ← 技能名本地化
                                      │   （**弹窗文字消失**：根因在 v14 才查清）
                                      └─ .fixed-fonts-v14fix.ipa 59,564,493 ← CJK 字体分支修复
                                          └─ .fixed-fonts-v15fix.ipa 59,564,493 ← 乱码本地化 + 道具名本地化
                                              └─ -v16fix → … → -v21fix → -v22fix → -v23fix → -v24fix → -v25fix → -v26fix → -v27fix
                                                  └─ **-v28fix.ipa** 59,564,493 ← 任务闪退**根因**修复（见 5.11）
                                                      └─ **-v29fix.ipa** 59,564,493 ← 施肥飘字还原（见 5.12）
                                                 （#4 工具条左移、#2/#8 字号、#7 详情页改黑，见 process.md）
                                      （v7–v11 为诊断/失败的中间代，v12fix 直接从 v6 重建）
```

> **当前交付版本是 `-v29fix.ipa`**（sha256 `E5951F94…9DED`），
> 管理器默认选中它（`launcher_selected_ipa.txt`），`Release\` 里也是这一份。
> 主人已实测通过（施肥飘字显示 ` %@施肥啦！`）。
>
> **回滚**：每一代都是**新增文件**，不覆盖上一代。要回退就在管理器里选回
> `v28fix`（或更早的 v27fix）；模拟器侧的兜底清理一直有效，选回去也不会闪退。

> **v13fix 只是个中间产物**：它在 sub6/sub9 各占了一段死代码（`0x16d594` /
> `0x10c470`）放 `zfrLocFormat` stub，v15fix 把它的取数寄存器改成 `r3`。
> 单独跑 v13fix 会让解锁弹窗变空白（原因见 7.5）。

每个 `*.ipa` 都有同名 `.report.json`，记录**输入/输出的 SHA256、每个补丁站点的地址与新旧字节、
以及校验结果**。改任何东西之前先读对应 report。

`Zombie_Farm_1.181.modified.ipa` 是更早的英文版，与本条线无关。

---

## 四、目标二进制

补丁对象是 IPA 内的 **`Payload/ZFR.app/ZFR`**：

- FAT Mach-O，**恰好两个 32 位小端 slice**
  - `cpusubtype 6` = ARMv6 → capstone `CS_MODE_ARM`
  - `cpusubtype 9` = ARMv7 → capstone `CS_MODE_THUMB`
- **两个 slice 必须同时改**，否则某个 CPU 上表现不一致。源码相同，改法对称但编码不同。
- 可执行文件里**没有富余空间**：所有 section 首尾相接，`gap_before` 基本为 0。
  所以补丁必须**等宽**，不能插入字节。

沙盒存档：`touchHLE/touchHLE_sandbox/com.playforge.ZombieFarm.ZFR/Documents/`（`saveGame.bin2` 等）。

---

## 五、核心技术知识（血泪换来的，务必先读）

### 5.1 字号是怎么进入 label 的

弹窗文字在 `ZFAlertWindow` 的 ivar 里：`title1` / `body1` / `body2` / `buttonLabel`
（`+0xd0` / `+0xd4` / `+0xd8` / `+0xdc`），每个是 `CCLabel`，字号存在 `+0x190`。

字号经**三条不同路径**到达 label，**没有单点可改**：

1. `-initWithWindow:` 里的字面常量（标题 20.0 / 正文 15.0）—— 被 10 个工厂共用
2. 各工厂自己的常量（如 `alertWindowSlideInInformative:` 用 18/12）
3. `+alertWindowInformative:withMessage:withFontSize:` —— 字号是**调用方传的 int 参数**，
   经 `vcvt.f32.s32` 转换，**没有常量可改**

第 3 条是「v1 静态改常量没效果」的真正原因：改的是第 1 条路径，而实际测试的弹窗走的是第 3 条。

`CCLabel` **没有** `fontSize` / `setFontSize:` / `string` 取值器，只有 `setString:`。
所以想改字号只能改创建常量，或者重新 `setString:` 重建纹理。

### 5.2 浮点常量在两条 slice 里的编码

| | ARM (sub6) | Thumb (sub9) |
|---|---|---|
| 组装 | `mov rX,#0xNN00000` + 后置 `orr rX,rX,#0x40000000` | `movw rX,#低半` + `movt rX,#0x41NN` |
| **改哪里** | `mov` 的立即数 | `movt` 的立即数 |
| 20.0 | `0x1a00000` | `0x41a0` |
| 24.0 | `0x1c00000` | `0x41c0` |
| 15.0 | `0x1700000` | `0x4170` |
| 18.0 | `0x1900000` | `0x4190` |
| 14.0 | `0x1600000` | `0x4160` |

**三个必须知道的坑：**

1. **ARM 的 `mov` 立即数携带浮点的低 25 位，不是 24 位。**
   `0x41a00000 & 0x1FFFFFF = 0x1a00000` —— bit24 是指数的最高位。
   用 24 位掩码会把 **14.0（`0x1600000`，bit24 置位）整个漏掉**。
2. **ARM 立即数是 rotate+imm8 循环右移编码。** capstone 会把补过的值显示成
   `mov r3, #28, #12`（三操作数，imm8 + 显式 ROR）。必须折叠 rotate 才能读回真实浮点，
   否则 24.0 会被误读成 2.0。**每处替换都必须 decode-back 验证**。
3. **Thumb 的 `movt` 掩码是 `0xFBF0`，不是 `0xFBFF`** —— `i` 位（`0x400`）和 imm4（`0xF`）要排除。

### 5.3 交叉引用：朴素做法在这个 binary 上完全失效

**不要**用「搜索目标地址的 4 字节模式」来找引用。这些 slice 用
**索引式文字池**：

```asm
ldr r1, [pc, #imm]     ; 取到的是「增量」，不是地址
...
ldr r1, [pc, r1]       ; 或 add rD, pc, rS —— 基址是这条指令的 PC，不是 ld 的 PC
```

把两者混为一谈会产出**大量看似合理的假引用**。正确做法见 `tools/value_xref.py`
（线性追踪寄存器值，建模了上述惯用法、`add rX,pc,rY`、`ldr rX,[rY,#imm]` 解引用）。

同理，`sl.methods`（来自 `audit_zfr_ipa.py`）**可能不完整** —— 用 `classes_by_name()` +
`all_methods()` 拿到的才是权威的方法列表。

### 5.4 code cave 与 helper 网络（v4 的核心）

codex 把「中文名重建 + 字号加成」的 helper **手写注入**到两个已废弃方法的方法体里，
当代码空间用：

| 方法 | ARM 入口 / 函数体 | Thumb 入口 / 函数体 | delta |
|---|---|---|---|
| `ZFGuiLayer showRateIt` | `0x1b464` / `0x1b46c` | `0x14f6c` / `0x14f70` | +4.0 |
| `ZFGuiLayer showTreeWorldPopUp` | `0x1b688` / `0x1b690` | `0x15110` / `0x15114` | +3.0 |

helper 一次调用干两件事：`fontSize_ += delta`，**以及**用中文名重新 `setString:`。

8/28 的崩溃修复把两个**入口**改成无条件 `bx lr`（崩溃根因：`zfrpatch.dylib` 在 touchHLE 下
**从不加载**，因为 `touchHLE.exe` 只认 `/usr/lib/` 前缀的库，而它是
`@executable_path/Frameworks/`），于是所有 wrapper 的 `bl 入口` 全部空转 ——
**中文名重建和字号加成一起失效**。

v4 的修法：
- **retarget**：cave 内 16 条 `bl 入口` → `bl 入口+8`（Thumb +4）。入口保持 `bx lr`，
  ObjC 派发 `showRateIt` / `showTreeWorldPopUp` 依然安全。
- **delta 归零**：`vadd.f32 s0,s0,s2` → 冗余的 `vldr s0,[r4,#0x190]`（读出来又写回去，
  紧随的 `vstr` 变空操作）。替换编码原样存在于同一 helper 内部，是最强的正确性证据。

**cave 区域（`sub6 0x1b464..0x1b810`、`sub9 0x14f6c..0x151c0`）现在有活代码，
所有新补丁都必须避开它** —— v5/v6 的 patcher 都把它写成 `FORBIDDEN` 守卫。

**v13fix 又新占了两块（也一律禁止再写）**：

| 用途 | sub6 | sub9 |
|---|---|---|
| v11/v12 重写、**v28fix 再次重写**的 `stopListening` | `0x16a5f8..0x16a700`（+池 `0x16a700..0x16a718`） | `0x10a1dc..0x10a29c` |
| v13 `zfrLocFormat` stub | `0x16d594..0x16d5ac` | `0x10c470..0x10c486` |

后两块原本是 `-[ZFQuestMan removeSeasonalQuests]` 的函数序言（死代码，见 5.9）。

### 5.5 「工厂重建」惯用法

有些工厂**不用** `initWithWindow:` 建好的 body label，而是**另建一个**再 `setBody1:` 装回去。
只改 `initWithWindow:` 会被这些路径覆盖掉。已知的有：

- `alertWindowSimple:...withWindow:`（ARM `0xa16fc` / Thumb `0x75788`）
- `alertWindowSimpleChoice:...withWindow:`（ARM `0xa2190` / Thumb `0x75faa`）
- `ZFMarketMenu -unlockItem:`（ARM `0x6a49c` / Thumb `0x4d6f4`）← v6 修的

排查新弹窗字号时，**先确认它是自建 label 还是复用**。

### 5.6 存档格式

- `saveGame.bin2` 是**自定义二进制格式，且是大端序**（踩过：按小端读会全部错位）。
- 任务记录形状：`id, 需求个数, 各需求的进度...`
- `saveGame.preview` 和 `Library/Preferences/*.plist` 是标准 plist。

### 5.7 环境坑

- 控制台是 **GBK**：跑 python 一律加 `PYTHONIOENCODING=utf-8`，并设 `PYTHONDONTWRITEBYTECODE=1`。
- shell 是 **PowerShell**：**heredoc 不可用**，要先写 `.py` 文件再执行。
- capstone 5.0.7 / Python 3.14。**`keystone-engine` 已装**（0.9.2），
  新补丁**优先用 keystone 汇编 + capstone 反汇编回读**，
  不要手算指令编码 —— v28fix 就是这么做的，省掉了整类编码错误。
  注意 keystone 的注释符是 `@`，用 `;` 会被当成语句分隔符而报 `Invalid mnemonic`。
- `md.detail = True` 才拿得到操作数；反汇编方法体时加 `md.skipdata = True`，
  否则遇到文字池会**静默截断**。
- **`md.detail` 下 `push`/`pop` 的寄存器表是「一个操作数一个寄存器」**，
  没有 `.regs` 字段（capstone 5.0.7）。取寄存器表要遍历所有 operand 收 `.reg`，
  别写 `op.regs`（会 `AttributeError`）。
- **没有 `pwsh`**：这台机器只有 Windows PowerShell 5.1。
  跑脚本用 `& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File ...`。
- **`Start-Process` 会崩**：环境里同时有 `NO_PROXY` 和 `no_proxy`，
  PowerShell 重建子进程环境时抛 `Key in dictionary: 'NO_PROXY'`。
  改用 `[System.Diagnostics.Process]::Start($psi)`（`ProcessStartInfo` 直接透传环境块），
  并借 `cmd.exe /c "... > log 2>&1"` 落日志 —— **别用管道**，未读的 64 KiB 管道会把模拟器堵死。
- **中文别写进 `python -c`**：控制台是 GBK，内联的中文字符串会被转码成乱码甚至
  `SyntaxError`。要处理中文一律**先写 `.py` 文件**再执行（和 heredoc 那条同源）。
- 读中文文件的输出也用 `-Encoding UTF8`（`Get-Content` 默认按 ANSI 解，会满屏乱码）。

#### ★ 虚拟地址 ≠ 文件偏移（**全 slice 差 0x1000**）

这是本项目**最容易静默出错**的一条，2026-09-20 有一次调查整段结论因此作废：

```
section            VA          file off    delta
__text          0x00003c68    0x00002c68  0x1000
__cfstring      0x003a3280    0x003a2280  0x1000
__objc_selrefs  0x00393870    0x00392870  0x1000
（所有有文件内容的段一律 0x1000；__bss/__common 无文件内容）
```

所以 **`sl.data[va : va+n]` 是错的** —— 它整体偏 0x1000 去读隔壁数据，
**不报错、不越界**，只是给你一个看起来合法的错误答案。
（实例：把 `CFSTR 0x3a3310` 读成空串，进而推出"表名是空 → 读默认表"，
连带误判 v29fix 改错了文件。真相见
`_analysis/reports/ZFR_施肥飘字_表来源订正.md`。）

**规矩**：

1. 读内存一律 `sl.addr_to_file(va)` 之后再索引 `sl.data`，**永远不要**直接
   `data[va]`。`tools/` 里的基础设施（`audit_zfr_ipa` / `inspect_v3_facts` /
   `patch_zfr_alert_fonts` / `_dis.py` / `value_xref.py`）都遵守这条，所以**历代
   补丁与验证器的地址都是对的**；踩坑的都是临时写的新探针。
2. **反汇编要从「真边界」开始**：方法入口（ObjC 元数据里的 IMP）或已知的
   指令边界。从任意地址起扫，Thumb 是变长指令，**会整体漂 2 字节**，
   于是解出看似合理但完全不同的指令流。
   自检办法：反解出的地址若与 `__cfstring`/`__objc_selrefs` 段扫描出的
   **真实对象地址**对不上，就是相位错了。
3. 顺带记住 `localizedStringForKey:value:table:` 的 ABI：
   **`r0=self r1=_cmd r2=key r3=value [sp]=table`**。
   `r3` 是 **value（回退值）**，不是表名 —— 很容易看错。

### 5.8 改写既有指令时的三个致命陷阱（v10/v11/v13 都差点/确实在这上面翻车）

**① `objc_msgSend` 的返回值会接力。** `autorelease` / `retain` / `self` 这类方法**返回 self**，
所以编译器经常依赖「`r0` 里还是那个对象」直接发起下一次调用：

```asm
0x187dd0  bl   objc_msgSend     ; [obj autorelease] → r0 仍是 obj
0x187dd4  ldr  r1, [sp, #0x4c]
0x187dd8  mov  r8, r0           ; 顺手存一份
0x187ddc  bl   objc_msgSend     ; 接收者又是 r0！
```

把第一条 `bl` 换成返回 void 的方法（如 `stopListening`）后，`r0` 里会残留**上上次调用的结果**
（本例是 `NSNotificationCenter` 实例），于是变成 `[center requirements]` 直接 panic。
**替换任何调用前，先确认它的返回值后面有没有被用。**

**② Thumb 的 `BL` 与 `BLX` 基址不同。**

| 指令 | 编码 | 基址 |
|---|---|---|
| `BL` (T1) | `hw2` bit12=1（基址 `0xD000`） | **`addr + 4`**（不对齐） |
| `BLX` (T2) | `hw2` bit12=0（基址 `0xC000`） | **`Align(addr + 4, 4)`** |

**capstone 对两者都按 `addr+4` 解码**，所以在 `addr % 4 == 2` 的位置上它会给出**错误**的
`bl` 目标 —— 别拿它的 `op_str` 当校验依据。判定方法：二进制里 340 条位于 `≡2 (mod 4)` 的
`BL`，其热点目标解出 `0x280dd8` / `0x26cbbc`，两者都是紧跟 `pop {r7,pc}` 的
`sub sp,#0x20` 函数入口；对齐基址反而给出那个 `pop` 本身和填充字节。

**可靠做法**：编码器要能用**已知的原始指令字节**反向自检（`patch_zfr_questfix_v11.py`
的 `self_test()` 复现了 7 组 BLX + 2 组 ARM BL 的原字节）。

**③ Thumb 的 16 位 `POP` 不能弹 `LR`。** 这条最阴 —— 两种写法**都能反汇编出看起来对的文本**：

| 字节 | 反汇编 | 实际语义 |
|---|---|---|
| `0xbd07` | `pop {r0, r1, r2, pc}` | **弹 PC**，从当前函数返回 |
| `0xbde8 0x4007` (`pop.w`) | `pop.w {r0, r1, r2, lr}` | 弹 LR（唯一能这么写的形式） |

`PUSH` 没这个问题（16 位 `PUSH` 的 bit8 就是 LR，`0xb507` = `push {r0,r1,r2,lr}` 是对的），
只有 `POP` 受限。v13fix 的 sub9 stub 第一版就写成了 `0xbd07`：那会让 stub **直接返回**，
跳过 `objc_msgSend(stringWithFormat:)`，弹窗会拿到错误内容 —— 而且是**静默**的。

**结论**：在 Thumb 里保存/恢复 LR，要么用 `push {rX, lr}` + `pop {rX, pc}`，
要么用 `pop.w {…, lr}`。别写 16 位 `pop {…, lr}`。
对抗办法是让 verifier **逐指令比对期望序列**，而不是做关键词探测
（`_analysis/_verify_v13fix.py` 的 `EXPECTED_STUB` 就是这么做的）。

**④ 16 位 `add rd, pc` 的 PC 基址是 `addr + 4`，不做 4 字节对齐。**
这条是 v17 才查清的，它让 #1 白查了两轮：**所有静态扫描工具都少解析 2 字节，
把大量站点静默丢掉**。

| 指令 | PC 基址 |
|---|---|
| `ldr rD, [pc, #imm]`（字面量池） | `Align(addr + 4, 4)` ← 字对齐 |
| `add rD, pc`（T1，高寄存器 ADD） | **`addr + 4`，不对齐** |

只有 `addr % 4 == 2` 时两者才不同，而那时错的那一方会落到**前一个对象内部**，
结构体 `flags` 校验失败 → 站点消失，没有任何报错。

**判定证据**（`_analysis/_v17_pc.py`）：sub9 里 56353 条已知 delta 且 `addr%4==2`
的 `add rd, pc`，

```
unaligned = addr + 4          → 6629 条正好命中真实 CFString 对象
aligned   = Align(addr+4, 4)  →    0 条
```

**教训**：凡"某字符串没有任何引用"这种否定结论，先怀疑工具。
`_dis.py` / `_b2_all.py` 已按此修正；README 5.8② 里 BL/BLX 基址不同是同一个家族的问题。

> **② 的补充（v21/v22 实测，capstone 5.0.7）：** 上面说"capstone 对两者都按 `addr+4`
> 解码"**已经过时** —— 5.0.7 对 `BLX` 用的是正确的 `Align(addr+4,4)`：
> `0xcf962`（`≡2 mod 4`）的 `00f2f4eb` 被解成 `blx #0x2d014c`（正确目标）。
> 所以**解码结果可以当校验依据**，但编码器仍必须自己算对基址：
> v22 的 `thumb_bl(addr, target, link)` 对 `BL` 用 `addr+4`、对 `BLX` 用 `Align(addr+4,4)`。

**⑤ 想给一个"创建时没设颜色"的 label 补 `setColor:`，用"透传栈参数"的 wrapper stub。**
（v22fix，zombie 详情页五个标签改黑）

被替换的是一次 `blx objc_msgSend`（4 字节），改成 `bl <stub>`。难点是
**`labelWithString:fontName:fontSize:` 的第三个参数在 `[sp]` 上**，而 stub 又要调两次
`objc_msgSend` —— 只要在第一次调用前 `push`，栈参数就错位（v16 踩过这个坑）。

解法：**往下开 8 字节的帧，把栈参数搬到自己的 `[sp]`**，两次调用之间 `sp` 不变：

```
sub   sp, #8                 ; sp 仍然 8 字节对齐，调用方的 [sp] 参数落到 [sp+8]
str.w lr, [sp, #4]           ; 存返回地址
ldr.w r12, [sp, #8]          ; 取出调用方的 fontSize
str.w r12, [sp]              ; 放到内层 objc_msgSend 该看到的位置
blx   objc_msgSend           ; r0 = 新 label（参数与原来完全一致）
str   r0, [sp]
ldr   r1, [pc, #0x10]        ; @selector(setColor:)（cave 里的字面量）
eors  r2, r2                 ; ccColor3B black
eors  r3, r3
blx   objc_msgSend
ldr   r0, [sp]               ; 把 label 当返回值还给调用方
ldr.w lr, [sp, #4]
add   sp, #8
bx    lr
```

只碰 caller-saved 寄存器（r0–r3、r12），`sp`/`lr` 复原 —— 调用方看到的效果和一条
裸 `blx objc_msgSend` 完全一样。注意 16 位 `sub sp, #imm7` 的立即数是**以 4 为单位**
的（`0xb082` 才是 `sub sp,#8`，不是 `0xb088`）。

**⑥ 只想改一个栈参数？用 `bx` 尾调用，别碰 `lr`。**（v23fix，标题被 dimensions 盒子裁掉）

`labelWithString:dimensions:alignment:fontName:fontSize:` 的 `dimensions.height` 在 `[sp]`。
v23 只要把它从 20.0 改成 34.0，**不需要知道返回值**，所以可以尾调用：

```
movw  r12, #0x0000
movt  r12, #0x4208         ; r12 = 34.0
str.w r12, [sp]            ; dimensions.height := 34.0
movw  r12, #0x014c
movt  r12, #0x002d         ; r12 = 0x2d014c (objc_msgSend，ARM)
bx    r12                  ; ★ bx 不改 lr —— objc_msgSend 直接返回到调用方的下一条
```

`bx` 用寄存器 bit0 选状态（`0x2d014c` 是 ARM），**不会写 lr**，于是调用方 `bl stub`
设的返回地址原封不动地穿过 stub 传给了 objc_msgSend。v17 的 `bx ip` 是同一个手法。
代价：stub 不能对返回值做任何事 —— 需要两次调用时改用 ⑤ 的完整 wrapper。
（`bx r12` 的字节是 `0x4760`，bits 6..3 才是 Rm；写成 `0x4764` 会多置 bit2。）

**⑦ 改布局常量前先看它被谁用、以及公式里还有没有别的项。**（v23/v24，标题被裁 + 偏上）

`title1` 的尺寸盒是 200×**20**，而 24pt 的字装不下 → 底部被切。那个 20.0 来自
`0x76aaa movt r5,#0x41a0`，**同一个 r5 还被 `makeWindow:` 的第一个参数用着**，
所以不能直接改常量，只能改栈参数（见 ⑥）。

但改完盒子高度后标题又"偏高" —— 因为工厂随后这样定位它：

```
y = contentSize.height * 0.5 + (-6.0)     ; sub9 0x76d06..0x76d16
[title1 setPosition:(x, y)]               ; sub9 0x76d50
```

label 的 anchor 是 `(0,0)`，字在盒子里**顶对齐**，所以

```
字的顶边 = y + height = 1.5 * height + C
```

**盒子一变高，字就跟着往上跑**：20→34 让顶边上移 21px。要让顶边回到原处，
就得把 C 从 −6.0 改成 −27.0（`1.5*34 − 27 == 1.5*20 − 6 == 24`）。

`vmov.f32 d16, #-6.0` 是**立即数**（不是字面量池），VFP 的 imm8 格式是
`sign:i6:i5i4:i3i0`（值 = (-1)^s × (1 + i3210/16) × 2^(exp-3)，exp 由 i6/i5i4 决定）。
穷举法最省事：**逐位翻转**原指令看哪几位会改变反汇编出来的常量，再在那几位上
暴力搜索目标值，最后用 capstone 反解确认 —— v24 的 `-27.0` = `c3ff1b0f` 就是这么定的。

**⑧ 想去掉一个 label 的粗体？改它传的 CFString，别去动字体表。**
`fontName` 是 `CFString` 对象地址：sub9 用 `movw/movt` + `add rX, pc`（`≡2 (mod 4)`
时基址是 `addr+4`），sub6 用 `ldr rX,[pc,#imm]` 取一个字面量再 `add rX, pc, rX`。
两种都只是**把一个常量改成"另一个 CFString 对象"**：

```
sub9 0x0d28fa  movw r3, #0xae8 -> #0x3718
               0x2d0ae8 + 0x0d2908 = 0x3a33f0 'AmericanTypewriter-Bold'
               0x2d3718 + 0x0d2908 = 0x3a6020 'AmericanTypewriter'
sub6 0x11f1e4  字面量 0x348484 -> 0x34b0b4   （唯一读者 0x11efc0）
```

`__cfstring` 里每个对象 16 字节（`isa,flags,data,len`，flags=0x7c8），全库扫一遍
就能列出所有字体名字符串的地址。

### 5.9 怎么找可用的 code cave（死方法判定）

`__text` 里**没有**任何空闲 padding（各 section 之间的缝隙最多 12 字节，
`__cstring` 尾部也没有富余），要加代码只能占用**绝不会被执行的方法体**。
判定一个方法是不是死的，用三条**可证明**的条件
（`_analysis/_dead.py` + `_analysis/_deadcheck.py`）：

1. **选择器不在 `__objc_selrefs` 里** —— 没有任何 `objc_msgSend` 能发到它。
2. **这个字符串在整个 slice 里只出现 1 次** —— 就是 `__objc_methname` 里那一份。
   只要没有第二份，`NSSelectorFromString:` / `performSelector:` 也构造不出来。
3. **没有任何 `bl`/`b` 指向它的入口**。

三条全中才算死。`-[ZFQuestMan removeSeasonalQuests]`（sub6 `0x16d594` /
sub9 `0x10c470`）就是靠这三条选出来的 —— 顺带解释了为什么季节性任务
从来不会被移除（见 7.2）。

注意：**「名字看起来像在用」不等于在用**。`displayMessage:atPosition:…`、
`fadeOutAllButtons`、`printEvents`、`backupSaveFiles` 这些同样三条全中，
是原版留下的死代码，可以当备用 cave。

### 5.10 已占用的 cave（**后续补丁必须列入 `FORBIDDEN_PRIOR`**）

| slice | 区间 | 用途 |
|---|---|---|
| sub6 | `0x1b464..0x1b810` | v4 codex helper 网络（**活代码**） |
| sub6 | `0x16a5f8..0x16a700` | v28fix `stopListening` 方法体（ARM，见 5.11） |
| sub6 | `0x16a700..0x16a718` | v28fix `stopListening` 自己的字面量池（6 字） |
| sub6 | `0x16d594..0x16d5ac` | v13/v15 stub |
| sub6 | `0x16d5b0..0x16d5e0` | v16 字符串池 |
| sub6 | `0x177534..0x17753f` | v17 字面量 ` +%d经验` |
| sub9 | `0x14f6c..0x151c0` | v4 helper 网络 + `zfrLoc`（**活代码**） |
| sub9 | `0x10a1dc..0x10a29c` | v28fix `stopListening` 方法体（Thumb，见 5.11） |
| sub9 | `0x10c470..0x10c486` | v16 sub9 stub |
| sub9 | `0x10c490..0x10c4c0` | v16 字符串池 |
| sub9 | `0x1138a0..0x1138c5` | v17 stub + 字面量 |
| sub9 | `0x1138c8..0x1138f3` | v22 `setColor:` wrapper stub（40 字节代码 + 4 字节字面量） |
| sub9 | `0x1138f4..0x113909` | v23 dimensions-height stub（22 字节，尾调用 objc_msgSend） |

> cave 里放**字面量**是允许的：字符串只要被 `__cfstring` 的 `data` 字段指着就行，
> 放在可执行的 `__text` 里照样能读（v16/v17 都这么做，实测有效）。

### 5.11 v11→v28：**覆盖整个方法体前，先确认被删掉的每一句都不是必需的**

这是本项目**代价最大的一次自伤**，后续动任何方法体都要先读这一节。

**v11fix 干了什么**：为了修「任务计数归零」，把 `-[ZFQuestNotification stopListening]`
**整个函数体**（sub9 0xc0 字节）覆盖成只剩一句
`[[NSNotificationCenter defaultCenter] removeObserver:self]`，
并在注释里判断「原来那句逐个注销 requirements 的循环是个小泄漏，不是正确性问题」。

**这个判断是错的。** `NSNotificationCenter` 存 observer 用的是**裸指针、不持有**：

* `-startListening` 把每个 `ZFQuestRequirement` 注册为 `incrementCount:` 的观察者；
* v11 把注销它们的循环删了 → requirement 释放后留下**悬空记录**；
* 下次派发时 `incrementCount:` 发到**地址被复用成的别的对象**（`NSString`）上
  → `does not respond to selector "incrementCount:"` → 退出码 `-1073741819`。

**两层修法，都要理解**（这也是「兜底」与「根因」的教科书对比）：

| | 做法 | 能拦什么 | 拦不住什么 |
|---|---|---|---|
| 模拟器侧 | `ns_notification_center.rs` 派发前判 `observer_is_stale` 并清理（iOS 9+ 语义） | 地址被复用成**别的类**的悬空 | 地址被复用成**同类**（isa 相同 → 判不出 → 照常派发，**多记一次计数**） |
| **IPA 侧（v28fix）** | 把 `stopListening` 的逐条注销循环**加回来** | 悬空记录**根本不产生** | — |

**v28fix 的确切写法**（两件事都做，顺序不能反）：

```objc
- (void)stopListening {
    NSNotificationCenter *center = [NSNotificationCenter defaultCenter];
    [center removeObserver:self];                  // v11 的修法，原样保留
    for (ZFQuestRequirement *req in self.requirements)
        [center removeObserver:req];               // 原始二进制本来就有，v28 恢复
}
```

**关键安全论证（恢复循环为什么不会把「计数归零」改回来）**：
`removeObserver:` 按**指针**匹配，而两个集合不相交 ——
`-initWithID:loadSprite:` 自己读 `Quests.plist`、`alloc/init` 出**全新的**
`NSMutableArray`（sub9 `0x109a1e..0x109a48`）和**全新的** `ZFQuestRequirement`
（`0x109b2a` 处 `classref -> ZFQuestRequirement`），存进自己的 ivar `+0x128`。
所以 GameData 那个 throwaway 通知拥有的是**另一组** requirement 对象，
它的循环只能注销自己的那组。v28 恢复的正是**未打补丁的原版行为**。

**为什么不用开 code cave**（上一轮报告曾估错，特此更正）：
v11 把整个函数体填成了 NOP，槽位是**空的**，所以新体原地就塞得下。
原始循环用的快速枚举（`countByEnumeratingWithState:objects:count:`）光准备
state 就要 ~0x40 字节，原体 + 新增的 `removeObserver:self` 会到 ~0xcc > 0xc0；
改用 `count` + `objectAtIndex:`（循环期间数组不变，**语义等价**）只有 0x8a 字节。

**教训（写进检查清单）**：

1. **覆盖整个方法体 = 声明「原方法里每一句都是多余的」。** 下这个结论前，
   必须把原体的每条调用都读一遍，尤其**注销 / 清理 / 释放**这类「看起来只是收尾」的语句 ——
   删掉它们往往**不报错**，而是制造悬空指针、泄漏、重复计数。
2. **「小泄漏，不是正确性问题」这种判断，必须给出机制层面的理由**，
   不能凭感觉。v11 的注释就是这么写错的。
3. **兜底不等于修好。** 模拟器侧的清理能防崩，但同类地址复用判不出来，
   会静默**多记一次计数**。（主人实测症状：v28 之后任务弹窗的图片显示才正常 ——
   弹窗每行读 requirement 的 `spriteFilename` 与 `countCurrent`；
   归因分析见 `_analysis/reports/ZFR_v28fix_任务闪退根因修复.md` 第 7 节，
   那里标注了哪些是实测、哪些是推断。）**能在源头修，就别只加兜底。**
4. **手工汇编方法体时，用「结构验证」而不是「哈希对得上」**：
   v28 的验证器逐条核对 6 次调用是否都指向 `objc_msgSend`、每次调用前 `r1` 载入的是
   哪个槽位（逐寄存器跟踪 `movw/movt`，且任何其它写会作废跟踪值）、循环回边落在哪、
   `bhs` 是否跳到收尾、**除 prologue/epilogue 外没有任何指令碰 SP**。

---

### 5.12 本地化表：`.strings` 不是只能存二进制 plist（v19 曾因此白缩两个码元）

**这是本项目第二次「限制其实不存在，只是没试别的做法」**（第一次是 5.11 的「小泄漏」）。

v19fix 修 `Arial-BoldMT.strings` 的乱码时，要把 `Fertilized by %@!` 还原成
` %@施肥了`，却发现成员被 codex 塞进一个 **189 字节**的 DEFLATE 槽位，
而**忠实文本按二进制 plist 序列化后要 193 字节**。试遍了压缩级别、strategy、
memLevel、wbits、key 排序、手写去重 bplist —— 全是 193。于是把值缩短成 `%@施肥`。

**问题在于：试的全是二进制 plist。** `.strings` 的**经典格式是 OpenStep 文本**
（`{ "key" = "value"; }`），它原始体积大但**压缩率好得多**：

| 序列化格式 | 原始大小 | 最小 DEFLATE | 对 189 槽位 |
|---|---|---|---|
| 二进制 plist | 257 | **193** | 超 4 ← 当年卡这 |
| XML plist | 646 | 328 | 超 139 |
| **OpenStep 文本 + `\U` 转义** | 390 | **182** | **装得下，余 7** |

**游戏读得懂吗？读得懂**，而且不是猜的：

```
-[NSBundle localizedStringForKey:value:table:]
  -> [NSDictionary dictionaryWithContentsOfURL:]   ns_dictionary.rs:559
  -> deserialize_plist_from_file()                 ns_property_list_serialization.rs:133
  -> plist::Value::from_reader(...)                plist crate 1.8.0
```

`plist` 1.8.0 的 `Reader::init` 自动识别编码：binary magic → 二进制；否则先试 XML；
**XML 失败 → 回退 OpenStep/ASCII reader**。`Value::from_reader` 的文档原文就是
*"a plist of **any encoding**"*。已用**同版本 crate 编译探针**实测（v29 一轮）。

**两个必须记住的格式坑**（都实测过）：

1. **大括号是必需的**。裸列表 `"k" = "v";` 会被拒：
   `ExpectedEndOfEventStream { found: String }`。必须写成 `{ "k" = "v"; }`。
2. **不能直接写 UTF-8 字节**。ASCII reader 按 1:1 映射，中文会变 Latin-1 乱码
   （实测 ` %@æ\u{96}½...`）。**非 ASCII 一律写 `\Uxxxx` 转义**。

**验证「值对不对」时不要用中文字面量当期望值** —— PowerShell 写无 BOM 的 UTF-8
会让 Rust/Python 源码里的中文被错误解码，对一个**字节完全相同**的字符串报错
（v29 探针第一版就是这么假阳性的）。改成**逐码点比对**。

**教训**：「装不下」要先问一句**「我是不是只试了一种序列化格式？」**
换格式往往比改内容更划算 —— v29 换格式后，**更长的忠实文本反而更小**（186 < 193）。

**v29fix 实际出货的值是 ` %@施肥啦！`（186 字节，余 3）** —— 主人要求把「了」改成
「啦」并补上感叹号。选**全角 `！`** 是因为游戏自己的 zh-Hans 中文值里全角 `！`
有 **500** 处（ASCII `!` 只有 67 处），而且 `啦！` 这个组合**本来就有**：
`ZOMBIE FARM GOES SOCIAL!` → `僵尸农场更新到社交版啦！`。
要改半角只需动 `tools/patch_zfr_b2_v29.py` 的 `FERT_VALUE` 一个常量（184 字节）。

---

## 六、工具

### 6.1 基础设施（复用这些，别重写）

| 工具 | 作用 |
|---|---|
| `tools/audit_zfr_ipa.py` | `parse_fat(bytes)` → slice 列表（`.subtype/.data/.sections/.methods/.addr_to_file()/.cstr()`） |
| `tools/inspect_v3_facts.py` | `EXECUTABLE`/`ROOT`/`u32`/`classes_by_name`/`all_methods`/`method_starts`；CLI `ivars\|meths\|disasm\|at\|selrefs` |
| `tools/patch_zfr_alert_fonts.py` | ZIP/FAT 机械：`fat_descriptors`/`replace_zip_member`/`outside_ranges_equal`/`sha256`/`write_exclusive`。`parse_zip_layout` 返回**全部** ZIP 记录，`tools/patch_zfr_b2_v15.py` 的 `replace_named_member` 就是在它之上写的「替换任意成员（含 `.strings`）」 |
| `tools/value_xref.py` | **准确的**寄存器值追踪交叉引用（找「谁用了这个地址」） |
| `tools/dump_window.py` | 带 selector / CFString / 类引用解析的反汇编窗口 |
| `tools/ivar_xref.py` | 列出一个 `__objc_ivar` 的全部引用点及归属方法 |
| `tools/_zt/zscan.py` | 符号执行式常量追踪器（已处理 ROR 立即数折叠、`add rX,sp,#imm` 别名） |
| `tools/_zt/c13_final.py` | `ZFAlertWindow*` 字号普查（arity 感知 + 新鲜度过滤） |

### 6.2 历代 patcher 与验证器

每个 patcher 都有配套的**独立验证器**（不复用 patcher 自身的校验代码，从出货文件重新推导）：

| 版本 | patcher（`tools/`） | 验证器（`_analysis/`） |
|---|---|---|
| v3 | `patch_zfr_fonts_v3.py` | —（由 `_zt/c14_v3diff.py` 验证） |
| v4 | `patch_zfr_helper_v4.py` | `v4_verify.py` |
| v5 | `patch_zfr_fonts_v5.py` | `v5_validate.py` + `v5_verify.py` |
| v6 | `patch_zfr_fonts_v6.py` | `v6_verify.py` |
| v12fix | `patch_zfr_questfix_v11.py` | `_verify_v12fix.py` |
| v13fix | `patch_zfr_ability_v13.py` | `_verify_v13fix.py` |
| v14fix | `patch_zfr_lang_v14.py` | `_verify_v14fix.py` |
| v15fix | `patch_zfr_b2_v15.py` | `_verify_v15fix.py` |
| v16fix | `patch_zfr_b2_v16.py` | `_verify_v16fix.py` |
| v17fix | `patch_zfr_b2_v17.py` | `_verify_v17fix.py` |
| v18fix | `patch_zfr_b2_v18.py` | `_verify_v18fix.py` |
| v19fix | `patch_zfr_b2_v19.py` | `_verify_v19fix.py` |
| v20fix | `patch_zfr_b2_v20.py` | `_verify_v20fix.py` |
| v21fix | `patch_zfr_b2_v21.py` | `_verify_v21fix.py` |
| v22fix | `patch_zfr_b2_v22.py` | `_verify_v22fix.py` |
| v23fix | `patch_zfr_b2_v23.py` | `_verify_v23fix.py` |
| v24fix | `patch_zfr_b2_v24.py` | `_verify_v24fix.py` |
| v25fix | `patch_zfr_b2_v25.py` | `_verify_v25fix.py` |
| v26fix | `patch_zfr_b2_v26.py` | `_verify_v26fix.py` |
| v27fix | `patch_zfr_b2_v27.py` | `_verify_v27fix.py` |
| v28fix | `patch_zfr_questfix_v28.py` | `_verify_v28fix.py`（+ `_verify_v28_verifiers.py` 变异测试） |
| v29fix | `patch_zfr_b2_v29.py` | `_verify_v29fix.py`（+ `_v29_loader_probe.ps1` 真加载器探针） |

辅助：`v4_cave_map.py`（cave 带注解反汇编）、`v4_sites.py`、`v5_sites.py`（站点编译 +
decode-back）、`unlock_font_sites.py`（扫方法内的 font 调用点）。
分析用（都在 `_analysis/`，见 `_analysis/README.md`）：
`_dis.py`（带 selref/CFString/类名解析的区间反汇编）、
`_xref.py`（谁调用了这段区间）、`_dead.py` + `_deadcheck.py`（死方法判定，见 5.9）、
`_readsave.py`（读存档任务段）、`_layout.py`（section 布局与空隙）、`_vec.py`（编码自检向量）。

### 6.3 编写新补丁的固定套路

```powershell
python tools\patch_zfr_lang_vX.py --dry-run     # 先干跑，校验每个站点的期望字节
python tools\patch_zfr_lang_vX.py               # 落盘
python _analysis\_verify_vXfix.py               # 独立核验（在哪个目录跑都行）
```

全部验证器一次跑完：

```powershell
Get-ChildItem _analysis\_verify_*.py | ForEach-Object { "{0,-34} {1}" -f $_.Name, (python $_.FullName 2>&1 | Select-Object -Last 1) }
```

patcher 的硬性约束（照抄 v5/v6 的结构即可）：
1. 每个站点写明 `(地址, 期望旧字节, 新字节, 说明)`，**期望不匹配就中止**
2. 等宽检查
3. `FORBIDDEN` cave 重叠守卫
4. 替换指令 **decode-back 成浮点**再接受
5. 打完重新解析 FAT 回读
6. 全可执行文件比对，证明声明站点之外一个字节都没动
7. ZIP 定长槽替换 + `testzip()` 往返
8. 写 `report.json`

补充（v13 起）：
9. 编码器必须带 `self_test()`，用**二进制里已存在的原指令字节**反证编码正确（见 5.8②）
10. 占用的 cave 要写进 `NEW_STUBS` 并在 `report.json` 里公布，供后续补丁列入 `FORBIDDEN_PRIOR`
11. 验证器要**逐指令比对**期望序列，不做关键词探测（见 5.8③）

补充（v28 起）：
12. **验证器必须接受「待验证的字节」作为参数，不许内部重新生成再检查自己。**
    v28 的 `verify_stack_balance()` 初版在函数内部重新 `assemble()` 了一遍，
    于是它检查的永远是「刚生成的好字节」，而**不是即将写盘的那份** ——
    变异测试当场抓到它放过了「栈不平衡」和「sub6 体碰 SP」两个故意改坏的用例。
    凡是校验函数，签名里要有被校验的数据。
13. **写完验证器要跑变异测试**（`_analysis/_verify_v28_verifiers.py` 是模板）：
    故意把产物改坏若干种方式（选错槽位、删掉关键调用、掐断回边、栈不平衡、
    调用目标写错、池字写错、池 load 越界、体超长、输入哈希不符、禁区重叠），
    **要求验证器逐个报错**。一个从不失败的验证器等于没有验证器 ——
    这条比它听起来更重要，v28 就是靠它才发现 12 号那个洞。
14. 手写汇编的方法体，验证要做到**语义级**而不只是「能反汇编」：
    逐条核对调用目标、每次调用前参数寄存器装的是哪个槽位（逐寄存器跟踪 `movw/movt`，
    且任何其它写会作废跟踪值）、循环回边落在哪、条件跳转是否跳到收尾、
    以及**除 prologue/epilogue 外没有任何指令碰 SP**。

补充（v29 起）：
15. **改了资源（`.strings` / plist / 图片）就要用「真加载器探针」验证**，
    不能只证明「文件结构合法」。模板：`_analysis/_v29_loader_probe.ps1` ——
    它**取出货文件里真实的成员字节**，喂给**游戏同一个库的同一个版本**
    （registry 里 vendored 的 `plist-1.8.0`）编译出的探针，比对解出来的值。
16. **探针的期望值不要写成中文字面量**，用**码点**（`vec![0x20, 0x25, ...]`）。
    PowerShell 写出无 BOM 的 UTF-8 会让源码里的中文被错误解码，
    对一个字节完全相同的字符串报 WRONG（v29 第一版就是这么假阳性的）。

---

### 6.4 验证分层的现实（**别把「静态全绿」说成「修好了」**）

本项目的历史教训是：**静态验证可以全绿，游戏内依然是坏的**。分层说清楚：

| 层次 | 能证明什么 | 不能证明什么 |
|---|---|---|
| 结构验证（反汇编逐条核对） | 指令编码正确、语义符合意图 | 这个修法在运行时真的对吗 |
| 独立 verifier（不 import patcher） | 产物确实只改了声明的位置、旧修复没被破坏 | 同上 |
| 变异测试 | 验证器**有**发现问题的能力 | 同上 |
| 启动冒烟（`_analysis/_v28_boot.ps1`） | 手写汇编在**真实执行**时不炸（读档路径会调 `stopListening`） | 目标玩法路径是否正确 |
| **真加载器探针**（`_analysis/_v29_loader_probe.ps1`） | 出货的**真实成员字节**能被游戏**同一个** `plist` crate 版本解出正确内容 | 游戏 UI 会不会把它画出来 |
| **游戏内实测（主人）** | **真的修好了** | — |

**所以汇报时的规矩**：静态全绿就说「静态全绿，游戏内待验证」，
**不许**写成「已修好」。游戏内验证由主人执行 —— 见 6.5。

### 6.5 游戏内验证由主人做，**不要**去折腾模拟点击

主人明确要求：**游戏内容相关的验证由主人执行**。自动化点击在本机**不可靠**，已两次失败：

- 点击坐标算错（`_analysis/_v28_ab.ps1` 用 client `(654,511)`，
  而「开始游戏」按钮实际在 y≈690）→ 游戏一直停在开始界面，
  日志里 `0 observers`、debug hook 一次没触发 → **无效实验**；
- 后台运行时偶发窗口位置是垃圾值（`-31346,-31489`）→ 点击落空。

因此：**别把「自动点击跑通了一轮」当作结论依据。**
要么用不依赖点击的路径（读档时就会调到的函数，见 `_v28_boot.ps1`），
要么老实交给主人，并在报告里**明确标注哪些是实测、哪些是推断**。

另外：**`zfr_last_run.log` 是累积文件**（每次启动往后追加）。
用 `Select-String` 直接搜全文件会把**旧启动**的记录当成这次的证据 ——
我因此误判过一次。正确做法是取**最后一个 `CPU emulation begins now.` 之后**那一段。

---

## 七、已知问题 / 待办

### 7.1 任务进度不持久化（**已解决** — v12fix）

**现象**：入侵成功后任务计数当次正确，**退出重开就回退到 0**，计数永远无法累积。

**真正的根因**（早期几轮猜测全错，以下是三层证据闭环后的结论）：

`GameData -addUserData:` / `+readUserData:intoGameData:withVersion:` 每次存/读档，都会为
**每个任务**造一个一次性的 `ZFQuestNotification`，只为读 plist 里的需求元数据：

```asm
0x186d24  ldr r0, [pc, #0x540]     ; class ZFQuestNotification
0x186d30  bl  objc_msgSend          ; [ZFQuestNotification alloc]
0x186d3c  bl  objc_msgSend          ; [.. initWithID: questID]
0x186d44  bl  objc_msgSend          ; [.. autorelease]
```

`initWithID:` → `initWithID:loadSprite:` 会在 `0x169d8c..0x169dcc` **无条件**注册：

```objc
[center addObserver:self selector:@selector(requirementComplete)
               name:@"kRequirementComplete" object:nil];
[center addObserver:self selector:@selector(requirementUpdated)
               name:@"kRequirementUpdated"  object:nil];
```

`object:nil` 意味着**任意**需求变化都会回调到它，而它用**自己的** `countCurrent`（= 0，因为
从没从存档恢复过）重写**自己的**那条任务字典。这就是清单里「没碰过的任务也被清零」的原因。

**两个反直觉的关键点**（早期分析在此翻车两次）：

1. **`stopListening` 注销的不是这个注册。** 类上有两套互不相干的观察者：

   | 注册者 | 观察者 | 选择子 | 由谁注销 |
   |---|---|---|---|
   | `startListening` | **`ZFQuestRequirement` 对象** | `incrementCount:` | `stopListening` ✓ |
   | `initWithID:loadSprite:` | **通知自己** | `requirementUpdated:` / `requirementComplete:` | **只有 `dealloc`** |

   临时对象从没调用过 `startListening`，所以对它调 `stopListening` 是空操作（v10fix 因此无效）。

2. **`autorelease` 返回 self，`stopListening` 不返回。** 读取路径里 `r0` 一路接力到紧接其后
   的 `objc_msgSend` 当接收者；换成 `stopListening` 后 `r0` 残留成 `NSNotificationCenter`，
   于是 `[center requirements]` → touchHLE panic（v11fix 启动即崩的原因）。

**修复**（v12fix，15 站点，两个 slice）：

- 把 `-[ZFQuestNotification stopListening]` 的方法体重写为
  `[[NSNotificationCenter defaultCenter] removeObserver:self]` —— 即 `dealloc` 在
  `0x169f78` 做却永远没机会做的那件事；单参形式会一次性清掉该对象**所有**注册。
- 工厂侧在原 `autorelease` 调用点改为直接 `bl stopListening`（先 `mov r8/r5, r0` 保存对象），
  并**在两个 `readUserData:` 站点把 `r0` 还原**，保证后续调用的接收者正确。

**验证**（两次实战入侵，读 `saveGame.bin2` 逐任务比对）：

| | 任务 52 `Poppy Power`（*Defeat Goffy five times*） | 其余 11 个任务 |
|---|---|---|
| 测试前 | `[0]` | `[0]` |
| 第 1 次入侵后 | **`[1]`**（写盘成功） | `[0]` 未被牵连 |
| 第 2 次入侵后 | **`[2]`**（正常累积） | `[0]` 未被牵连 |

累积性正是原缺陷的反面（原症状为「第二次入侵仍然 1/3」）。

**注意**：`sub6 0x16a5f8..0x16a700` 与 `sub9 0x10a1dc..0x10a29b` 是这两段被整体重写的方法体，
后续补丁不要再往里写；`sub6 0x16a700..0x16a70b` 的三个字面量 delta 已按新消费点重算。

### 7.2 季节性入侵玩法未接线，6 个季节任务永久卡 0（原版内容删减）

**季节性任务本身是活的，缺的是入侵场地。** 先把机制说清楚：

- `ZFQuestMan -checkSeason`（sub6 `0x16d3dc`）只有 7 条指令，就是 `[self addSeasonalQuests]`。
  调用点只有两处：`ZFQuestMan -restoreQuestsFromSave+0x7c4`（`0x16e340`，每次读档）
  和 `ZFGuiLayer -showDailyEvents+0x2ac`（`0x25afa4`，每日事件弹窗）。
- `ZFQuestMan -addSeasonalQuests`（sub6 `0x16d3f8`）= 枚举 ivar `+0xd4`（即 `Quests.plist` 原始数组），
  逐条 `objectForKey:@"seasonal"` → `boolValue`，为真就 `[self addQuestWithID:<该条下标>]`。
  **全无日期判断** —— `seasonalDate` 这个字符串在整个 `ZFR` 二进制里出现 **0 次**，
  plist 里那些 `5/7/2011` / `6/30/2011` 是纯装饰数据。
- 所以只要 `levelRequired` 满足，季节性任务就会被加进 `currentQuests`。
  **这就是 ID 52 `Poppy Power`（本身 `seasonal=True`）会出现在存档里的原因**，
  也是它刷新后能累积到 `[2]` 的旁证。

**真正的缺陷在入侵场地这一侧。** `Enemies.plist` 只有 8 条，`name` 分别是
`Old McDonnell's Farm` / `Zombies vs Lawyers` / `Zombies vs Pirates` / `Zombies vs Ninjas` /
`Zombies vs Robots` / `Zombies vs Aliens` / `Tree World` / `Zombies vs Circus`。
而下面这些名字在全部 130 个 plist 里**只出现在 `Quests.plist` 自己身上**：

| 名字 | 原始出现处 |
|---|---|
| `Seasonal: Easter` | 仅 `Quests.plist` + `Localizable.strings` |
| `Seasonal : Brain Freeze` | 仅 `Quests.plist` + `Localizable.strings` |
| `Seasonal : Halloween` | 仅 `Quests.plist` + `Localizable.strings` |
| `Red Balloon` | 仅 `Quests.plist` + `Localizable.strings` |

更强的证据：`ZFR` 二进制裸字节搜索

| 字符串 | 二进制内出现次数 |
|---|---|
| `FarmStage` | 18 |
| `Tree World` | 4 |
| `EasterStage` | **0** |
| `Halloween2011Stage` | **0** |
| `IceCreamStage` | **0** |
| `ValentinesStage` | **0** |
| `Easter Badger` / `Dairy King` / `Uberbiss` / `Red Balloon` / `Goffy` | **0** |

美术资源**齐全**（`EasterStage.png`、`Halloween2011Stage.png` + `Halloween2011StageSkeleton.plist`、
`fightBGHalloween2011.png` + `_front.png`、`IceCreamStage.plist`、`blizzard.plist`、
`easterThrowParticle1.plist`、`bunnyActor.plist`、`quest_icon_easter/brainfreeze/halloween2011.png`），
中文文案也**齐全**（`复活节恶獾` / `奶品之王` / `吸血鬼优毕斯` / `恶獾来袭` / `脑子降温` / `万圣节` ……），
但**代码里没有任何加载这三个场地的路径**，`Enemies.plist` 里也没有对应条目
→ 这三个季节性入侵在原版就发不起来。

**后果：6 个任务永久停在 `[0]`**（早先记录的 5 个漏了 `99 Red Balloons`）：

| ID | 任务 | requirement | 死因 |
|---|---|---|---|
| 38 | Badger Badger Badger | `kInvasionSuccessfulNotification` / `Seasonal: Easter` ×3 | 场地不存在 |
| 40 | 99 Red Balloons | `kStageActorDefeated` / `Red Balloon` ×99 | `EasterStage` 载不进，无此 actor |
| 42 | Lactose Intolerance | `kInvasionSuccessfulNotification` / `Seasonal : Brain Freeze` ×3 | 场地不存在 |
| 44 | Survivin' the Blizzard | `kInvasionPerfectGameNotification` / `Seasonal : Brain Freeze` ×1 | 场地不存在 |
| 48 | Down for the Count | `kInvasionSuccessfulNotification` / `Seasonal : Halloween` ×3 | 场地不存在 |
| 50 | Uber Loser | `kInvasionPerfectGameNotification` / `Seasonal : Halloween` ×1 | 场地不存在 |

**不受影响的季节性任务**：`34 Chocoholic` / `35 Have a Heart` / `36 Statuesque` / `39 Egg Hunting` /
`43 Brain Freeze` / `49 Six Feet Under` / `53 Bushwhacked` 要求的道具
（`Chocolate Tile`、`Heart Gravestone`、`Cupid Statue A/B`、`Blue/Pink Easter Egg`、`Egg`、
`Vanilla/Chocolate/Strawberry Cone`、`Coffin 1/2/3`、`Bunnypig/Mosscrab/Cobrahawk Bush`）
在 `Market.plist` / `Drops.plist` 里**全部存在**；`51 Breaking the Spell` / `52 Poppy Power`
用的是真实场地 `Tree World`，52 已实测可累积。

**定性**：原版内容删减（场地没做完就发了），**不是补丁引入的**。
要真修需要同时做三件事：给 `Enemies.plist` 加 3 条场地条目、往二进制里塞
`EasterStage` / `Halloween2011Stage` / `IceCreamStage` 字符串、并让代码走到它们 ——
工作量远超"等宽原地替换"，暂不做。

### 7.3 技能名未本地化（图2）—— 已在 v13fix 修复

**症状**：入侵胜利弹窗显示 `Unlocked a new **ZomBumpkin** ability!`
（中文模板 + 英文技能名），应为「获得了一项新的**南瓜头僵尸**技能！」

**根因**：`ZFFightMan -getRandomAbilityToUnlock` 按技能 `tag` 做 switch，
每个 case 载入一个存着**内部 actor 名**的 `__cfstring`：

```
Zombie, Girl Zombie, ZomBumpkin, Headless Zombie, Garden Zombie, Zyborg,
ZomBeauty, ZomBruiser, Kindlehead, ZomBotanist, Zombot, Amazombie, ZomBrute,
Flamehead, Flower Zombie, ZomGoblin, Robo Zombie, Zombielocks, Zombarian,
Party Zombie, Zombee, Imp Zombie, zombie        ← 共 23 个（22 具名 + 默认）
```

代码只本地化了模板 `localizedStringForKey:@"Unlocked a new %@ ability!"`，
**`%@` 参数直接塞原始 CFString**。而 `zh-Hans.lproj/Localizable.strings` 里
`'ZomBumpkin' = '南瓜头僵尸'` 等 22 条映射**一直都在**，只是没人去查。

**修法（零字符串注入）**：二进制里本来就有一个空指针安全的本地化 helper ——
codex 注入在 cave 里的

```
zfrLoc(s) = [[NSBundle mainBundle] localizedStringForKey:s value:s table:nil]
sub6 0x1b6d0 (ARM)      sub9 0x15140 (Thumb)
```

两条建消息的路径最后都是 `objc_msgSend(r0, stringWithFormat:, r2, r3)`，
`r3` 就是原始技能名。把这两个 `objc_msgSend` 改成先过一遍 stub 即可：

| slice | 站点 | 原名寄存器 | 原指令 |
|---|---|---|---|
| sub6 | `0xb75ac`（CJK 分支）、`0xb76d4`（默认分支） | `r5` | `bl 0x393fe0` |
| sub9 | `0x86112`、`0x86218` | `r4` | `blx 0x2d014c` |

stub 放在 **`-[ZFQuestMan removeSeasonalQuests]` 的函数序言**里 —— 这个方法在两个
slice 里都**可证明是死代码**：选择器不在 `__objc_selrefs` 里（没有任何
`objc_msgSend` 能发到它）、字符串在整个 slice 里只出现 1 次（就是
`__objc_methname` 里那一条，所以 `NSSelectorFromString:` / `performSelector:`
也点不到它）、没有任何 `bl`/`b` 指向它的入口。做法与 codex 当年占用
`showRateIt` / `showTreeWorldPopUp` 完全一致。

```
sub6 @0x16d594 (24 B)                sub9 @0x10c470 (22 B)
  push {r0, r1, r2, lr}                push   {r0, r1, r2, lr}
  mov  r0, r5                          mov    r0, r4
  bl   zfrLoc (0x1b6d0)                bl     zfrLoc (0x15140)
  mov  r3, r0                          mov    r3, r0
  pop  {r0, r1, r2, lr}                pop.w  {r0, r1, r2, lr}   ← 必须 32 位
  b    objc_msgSend (0x393fe0)         push   {r4, lr}
                                       blx    objc_msgSend (0x2d014c)
                                       pop    {r4, pc}
```

细节：sub6 用 `b`（ARM 下 `b` 就是尾调用，不改 LR 也不切状态）；
sub9 必须复用原来的 `blx`，因为 `objc_msgSend` 是 `__symbol_stub4` 里的 **ARM** 代码，
`blx`（T2）带状态切换，而 `b.w` 不会切 —— 直接 `b.w` 会崩。

**占用区间**（后续补丁必须避开）：sub6 `0x16d594..0x16d5ac`、
sub9 `0x10c470..0x10c486`。

**验证**：`_analysis/_verify_v13fix.py`（独立实现，不 import patcher）逐条复算：
差异严格收敛在 6 个区间内、两个 stub 反汇编逐指令符合预期、4 个站点的
参数装载上下文逐字节未变、死代码可达性在新二进制上重新证明、cave 原样。
全部通过。

**风险**：`localizedStringForKey:` 查不到 key 时返回 `value:` 参数，
而 helper 把 `value:` 也设成 key 本身 —— 所以找不到就原样返回英文名，
**任何语言下都不会比现在更差**。

### 7.4 僵尸技能解锁机制（原版行为，非缺陷）

排查「为什么同一个技能会被反复提示解锁」时把这条链路完整读了一遍，记录备查：

- **存储**：`GameData.abilityFlags` 是一个 `ZFBitBank` 对象（不是裸整数），
  位操作走 `-hasFlag:` / `-setFlag:`。它随 `GameData` 一起持久化
  （`-initWithCoder:` / `-copyWithZone:` / `-readUserFlagsData:intoGameData:withVersion:`）。
- **候选**：`+[ZFActorAbility abilitiesToUnlockForTier:]`（sub6 `0x15a588`）分两段：
  1. 遍历 tag `0x10..0x17` 与 `0x1b..0x28`（**故意跳过 `0x18/0x19/0x1a`** ——
     这三个 tag 在 `getRandomAbilityToUnlock` 的 switch 里落到通用名 `zombie`），
     用 `initBasicDataForTag:` 造对象，只留 `[ability tier] == 参数` 的；
  2. **再过滤已解锁的**：逐个 `[gameData.abilityFlags hasFlag:[ability flagBit]]`，
     已置位的丢弃（`0x15a83c: tst r0,#0xff` / `bne` 跳过）。
     结果为空时**返回 nil**。
- **发放**：`ZFFightMan -newAbilityIconClicked:`（sub6 `0xb8c14`）里
  `[[self zfGameData] abilityFlags]` → `setFlag:[item tag]`（`0xb9084`/`0xb9094`）。
  这是**全游戏唯一**的发放路径（另一处 `setFlag:` 在 `ZFCheats -setFlagsCheat:`，
  以及 `readUserFlagsData:` 的还原逻辑）。

**所以「同一个技能又被提示」的正常解释**：弹窗在技能**被抽中时就显示**
「Unlocked a new X ability!」，但**必须点一下弹窗里的技能图标**才会真正置位。
没点（或直接退游戏）就永远不算解锁，下次自然还能再抽到 —— 这是原版行为。

### 7.5 图2 真正的根因：CJK 字体分支从来没生效过（v14fix 修复）

v13fix 把技能名也换成中文之后，弹窗**整段文字消失了**，只剩一个孤零零的图标。
这不是 v13 写错了，而是揭开了一个一直存在的上游缺陷。

**链路（每一环都在二进制里核对过）**

1. 入侵胜利弹窗在 `ZFFightMan -getRandomAbilityToUnlock` 里建两个 label
   （消息 + `tap icon to continue`），代码里有**两条互斥路径**：

   | | CJK 路径 `0xb7530` | 默认路径 `0xb7654` |
   |---|---|---|
   | 模板 | `localizedStringForKey:` → 中文 | 同样 `localizedStringForKey:` → 中文 |
   | 技能名 | v13fix 起 → 中文 | v13fix 起 → 中文 |
   | 建 label | `objc_msgSend [CCLabelTTF **labelWithString:fontName:fontSize:**]` | `objc_msgSend [CCLabelBMFont **bitmapFontAtlasWithString:fntFile:**]` |
   | 字体 | `@"Arial"` + 26.0 | `@"ABD26.fnt"` |

2. 走哪条由这段决定：
   ```objc
   if ([ZombieFarmAppDelegate getCurrentLanguage] isEqualToString:@"zh-Hant"]) goto CJK;
   if ([... isEqualToString:@"zh-Hans"]) goto CJK;
   if ([... isEqualToString:@"ja"])      goto CJK;
   else                                  goto 默认;
   ```
3. 而 `+[ZombieFarmAppDelegate getCurrentLanguage]`（sub6 `0x195004`）是：
   ```objc
   return [[[NSUserDefaults standardUserDefaults]
                objectForKey:@"AppleLanguages"] objectAtIndex:0];
   ```
   **`AppleLanguages` 是全局域里的键，游戏的
   `Library/Preferences/com.playforge.ZombieFarm.ZFR.plist` 里根本没有它**
   （实测导出了该文件，21 个键，没有这一项）→ touchHLE 下返回 **nil**
   → 三次 `isEqualToString:` 全 NO → **永远走默认路径**。

4. `ABD26.fnt` 实测只有 **122 个字形，id 32..282，全是 Latin-1**（bundle 里另外两个
   `.fnt` 也一样，**整个 IPA 没有任何 .ttf/.otf**）。位图字体遇到没有字形的字符
   **静默丢弃**。

**所以：**
- 图2 时代用户只看到 `ZomBumpkin`，因为模板里的中文全被丢掉了
  （用户原话就是「文本仍英文（如 ZomBumpkin）」）。
- v13fix 把名字也变成中文之后，整串没有一个可渲染字符 → **整段空白**。

**同一个缺陷影响 ~30 处。** `getCurrentLanguage` 在 sub6 里有 90 个调用点，
按三连一组分布在 `ZFGuiLayer init / displayMessage: / displayToolTip: /
addToolTipButton: / showWhatsNewInThisVersionMessage`、`ZFFightGUI
initEnrageTimer / updateEnrageTimer / doOrDie`、`ZFZombieMenu`、`ZFAbilityCell`、
`ZFFightAbilityGUI`、`OptionsMenu`、`ZFStorageMenu`、`ZFMausoleumMenu`、
`ZFZombieCell`、`ZFGameCenterDelegate` …… 全部是同一套
「CJK 就走 TTF，否则走位图」的判断，**目前全部走了位图那一侧**。

**v14fix 的修法**：这个 IPA 本来就是 `CFBundleDevelopmentRegion = zh_CN` 的纯中文
包，所以让 `getCurrentLanguage` 直接返回调用方正在比较的那个常量 ——
CFString `@"zh-Hans"`。方法体（sub6 0x44 字节 / sub9 0x4E 字节）比新代码长得多，
**不需要 cave**：

```
sub6 @0x195004                      sub9 @0x12980C
  ldr r0, [pc, #0x38]                 movw r0, #lo16
  add r0, pc, r0                      movt r0, #hi16
  bx  lr                              add  r0, pc
  （其余 NOP，尾部 4 字节放 delta）      bx   lr
                                      （其余 NOP）
```

**验证**：`_analysis/_verify_v14fix.py` 独立复算 —— 差异收敛在这两块内、两个新函数体反汇编后
**逐级解引用得到的确实是 CFString `zh-Hans`**、`0xb74a0` 处两条 `bne` 仍指向 TTF 分支
`0xb7530` 而 `beq` 指向位图分支、以及 v12/v13 注入的代码一字节未动。全部通过。

**风险（必须实测确认）**：TTF 分支要求 `labelWithString:fontName:@"Arial"` 在
touchHLE 下能拿到字体。如果拿不到，那 ~30 处会一起变空白（很好辨认，不只是弹窗）。
真出现这种情况就回退到 `v13fix`/`v12fix`。

**注意**：v14fix 是叠加在 v13fix 之上的，所以它同时包含技能名本地化。

### 7.7 codex 补丁把三条本地化值改成了乱码（v15fix 修复）

**发现过程**：用户报「使用瞬间收获时地块上飘 `+200eE`，本该是 `+200金币`」。
一路查下来**不是代码问题，是数据损坏**。

**证据链**

1. 二进制里 `'+%ig'` / `'+%ixp'` 这些格式串都在，代码引用也正常。
2. 但 `zh-Hans.lproj/Localizable.strings` 里 `'+%ig'` 的**值是 `'+%iėĚ'`**。
   `ė`(U+0117) 和 `Ě`(U+011A) 属于 Latin Extended-A，Arial 画出来就是带小点的 `e`
   和带小勾的 `E` —— 小字号下读作 **`+200eE`**。
3. **拿未改动的基线 `ZFR 1.0.zh-CN-unsigned.ipa` 对比**，原文是
   `'+%i金子'` / `'+%i金子(化肥作用)'` / `'+%i金子(化肥奖励)'`，
   **码元数完全一致** —— 所以是纯等宽替换能修好的。
4. `ZFR 1.0.zh-CN-unsigned.ipa` 里正常、`complete-final.ipa` 里就坏了
   → **codex 的补丁阶梯干的**。它把全文件 40+ 处「金子」批量改成「金币」，
   只有这三条替换出了乱码（`'+%ig'`、`'+%ig (Fertilizer)'`、`'+%ig (Fertilizer Bonus)'`）。
5. 全库扫描确认：**值的层面只有这 3 条坏的**，zh-Hans 和 zh-Hant 各 3 条。
   另外 codex 给 zh-Hans **新增了 336 个 key**，其中 4 个 key 本身是乱码
   （`' +%dĘę'`、`'%dėĉ'`、`'+%iĘę'`、`'-%iėĉ'`），但它们**不可达**
   （游戏不会拿乱码当 key 去查），属于垃圾数据，v15fix 不动它们。
   基线里的 key 一个都没丢。
6. 可执行文件里也有一条同类损坏：`ZFSaleEndDateDay +%dĘę`
   （sub6 `0x3d1c68` / sub9 `0x30dc68`），是**调试日志串**，不进 UI，暂不处理。

**修法**（v15fix）：`Localizable.strings` 是二进制 plist，字符串按 UTF-16BE 存。
三条替换前后码元数相同 → plist 内部字节数不变 → **成员大小不变、IPA 大小不变**，
可以纯原地字节替换。替换时必须**从长到短**（长的以短的为前缀）。

**教训**：以后遇到「中文显示成拉丁字母乱码」，先拿未改动的基线 diff
`Localizable.strings`，再怀疑代码。

### 7.6 其他

- `ZFAlertWindowPromo` 在两个 slice 里**原生就不对称**（sub6 有 6 个 font call，sub9 只有 3 个）。
  动它时必须两个 slice 分别处理。
- `ZFAlertWindowFlurryOffer` **override 了 `initWithWindow:`**，基类站点对它无效（v5 已单独覆盖）。
- `ZFAlertWindowQuestComplete` / `Quest` 等子类自带字号，v5 已覆盖；但仍有一批
  slide-in 家族与 `StorageItem` 用的是另一档设计（正文已是 18.0，标题 19.0），**刻意未动**。

---

## 七·五、能不能重写这个游戏？（重构可行性调研）

> 问题来源：主人问「能否通过完全重构该 IPA 项目…来实现更精细化的画面」，并澄清
> **不是**要超分替换 IPA 内图片，而是想确认**用 Unity 之类重写这个游戏**的可行性。
> 下面是取证结论。**先说要点：素材可以复用，其余基本是从零写一个游戏。**

### 7.5.1 先排除一个看似可行的捷径：引擎自带的 HD 素材机制是死的

引擎是 **cocos2d**，二进制里确实保留了高清素材通路：

| 符号 | 是否存在 | 是否被引用 |
|---|---|---|
| `setContentScaleFactor:` | ✅ 在 `__objc_methname` | ❌ selref 槽位 **0 处引用** |
| `updateContentScaleFactor` | ✅（`CCDirector` 方法） | — |
| `hasSuffix:` | ✅ 在 `__objc_methname` | — |
| `-hd` 字面量 | 有 35 处**子串**，但**没有一个是独立字符串** | ❌ **0 处代码引用** |
| IPA 内的 `-hd` / `@2x` 图 | ❌ **一张都没有**（839 张 PNG 里只有 1 张 `Icon@2x.png`，是应用图标） | — |

也就是说：**cocos2d 的「放 `-hd` 图就自动高清」机制在这个构建里是死代码**，
靠塞入 `-hd` 图提升画质这条路**走不通**。

### 7.5.2 逻辑规模：491 个类 / 9352 个方法

`__text` 段 **2.86 MiB**，反汇编统计：

| 分组 | 类数 | 方法数 |
|---|---|---|
| **ZF\*（游戏自己的逻辑）** | 80 | **2217** |
| CC\*（cocos2d 引擎） | 133 | 1319 |
| 其余（第三方库） | 278 | 5816 |

第三方那 5816 个方法主要是**已死的基础设施**，重写时**不需要**移植：
`InterstitialASIHTTPRequest`（414）、`UA_ASIHTTPRequest`（388）、`FlurrySession`、
`MMGenericAdView`、`FacebookManager`、`SocialTableView*` —— 都是当年接的广告/统计/社交 SDK。

真正要重写的是这 2217 个游戏方法，按系统分：

| 系统 | 类数 | 方法数 | 最大的类 |
|---|---|---|---|
| UI / 菜单 | 15 | 484 | `ZFGuiLayer` **187** |
| 经济（市场/仓库/道具） | 13 | 406 | `ZFMarketMenu` 104 |
| 战斗 | 11 | 347 | `ZFFightMan` **142** |
| 僵尸 / 角色 | 11 | 292 | — |
| 农场 / 地块 | 5 | 212 | `ZFTileManager` 104 |
| 任务 / 成就 | 7 | 175 | `ZFQuestNotification` 43 |
| 社交 / 联网 | 2 | 48 | — |
| 其他 | 16 | 253 | — |

### 7.5.3 内容数据：大量硬编码坐标与数据表

130 个 `.plist`：

- **57 个是图集**，共 **500 帧**，每帧都有硬编码的 `textureRect` / `spriteOffset` /
  `spriteSourceSize`。重写时若改素材尺寸，**这 500 个矩形必须全部重算**（或用工具重新打包）。
- **数据表**：`TileProperties.plist`（576 项）、`ZombieSheet.plist`（115）、
  `Drops.plist`（74）、`UnitStats.plist`（70）、`Attacks.plist`（30）、
  `FarmerSprites.plist`（31）、`stageActors.plist`（15）、`Gifts.plist`（16）…
- **40+ 个粒子 plist**（每个 47–48 项），是 cocos2d 粒子系统格式。
- **4 个 `.tmx` 地图**（`Farm30/40/50.tmx`）、**3 个 `.fnt` 位图字体**、18 个 `.nib` 界面。

这些**数据**是重写中最有价值的部分：数值、掉落、单位属性都能解析出来复用，
但**语义**（每个字段什么意思、各系统怎么用它）需要从 2217 个方法里逆向。

### 7.5.4 联网依赖：服务端没有源码

二进制里 **64 个 URL**，包括：

- `http://api.zombiefarmgame.com/` 与 `/zf/market/` —— **市场/状态服务端**
- Facebook 登录、`promos.theplayforge.com`（发行商活动）
- 一大批**已经关停**的广告 SDK（AdMob、Flurry、Jumptap、Millennial Media、Greystripe、UrbanAirship）

服务端逻辑**不在 IPA 里、也没有源码**。所以重写只能做**离线单机版**（砍掉市场/社交/活动），
或者**自己实现一个后端**并猜出协议。这是重写方案里最大的不可知项。

### 7.5.5 素材可以直接复用（唯一能省的部分）

| 类型 | 数量 | 体积 |
|---|---|---|
| PNG | 839 | 12.9 MiB |
| WAV | 58 | — |
| plist | 130 | — |
| nib / tmx / fnt | 18 / 4 / 3 | — |

IPA 总共 71 MiB。**图片、音效、地图、字体都能直接搬进 Unity**，不用重画 ——
但分辨率是 1024×768 级别（见 §7.5.6），**重写并不能让画面更精细**，除非重新绘制素材。

### 7.5.6 关键：放大 ≠ 更精细（实测）

把 ×2 的截图缩回 ×1 与原图逐像素比对：

```
像素差 mean 1.23/255   ·   差异 >24 的像素占 0.3%
```

**几乎完全一致** —— 说明 `--scale-hack` 放大只是把**同样的画面**放大，
**不产生任何新细节**。素材本身就是 1024×768 级，放大到 1.5 倍以上开始发虚。

所以要真正更精细，只有两条路：**重绘素材**（美工工作量，与引擎无关）
或**重写游戏**（下面这条）。**换引擎本身不会让画面变清楚。**

### 7.5.7 结论

| 方案 | 可行性 | 主要成本 |
|---|---|---|
| 塞 `-hd` 图进 IPA | ❌ **不可行** | 机制是死代码，0 处引用 |
| 超分（AI 放大）替换素材 | ⚠️ 技术可行 | 839 张图要逐张处理 + **57 个图集的 500 个矩形要重算**；AI 放大的画风/文字容易糊，效果存疑 |
| **用 Unity 重写** | ✅ 可行但**工作量巨大** | 重写 2217 个游戏方法 + 重建 500 帧图集坐标 + 逆向数据表语义 + 自建/砍掉服务端；素材可复用 |

**给主人的直白结论**：重写**技术上可行**，但它不是「重构 IPA」，而是**从零做一个新游戏** ——
IPA 里能直接拿来用的只有**素材和数据**，**逻辑一行都拿不走**（只有 ARM 机器码）。
以本项目目前的进度（改字号、修本地化、修任务崩溃这种量级的补丁），重写属于**另一个项目**，
且**画质并不会因为换 Unity 而变好** —— 画质取决于素材分辨率，而素材需要重画。

**如果目标是「画面更好看」，性价比排序是**：① 重绘关键素材（logo/UI/HUD，几十张，收益最直接）
→ ② AI 超分那几十张关键图 → ③ 全量重写（收益/成本比最低）。

## 八、历史文档

全部在 `_analysis/` 下（见 `_analysis/README.md`）：

| 文件 | 内容 |
|---|---|
| `reports/ZFR_v4_v5_报告.md` | v4（helper 修复）+ v5（子类字号）的完整设计与验证记录 |
| `reports/ZFR_v6_与三个新问题.md` | v6（解锁弹窗字号）+ 技能名/计数问题的诊断 |
| `reports/ZFR_图3_任务计数_深挖报告.md` | 任务计数被清零的完整取证（v12fix 的依据） |
| `reports/ZFR_任务闪退_通知观察者.md` | 任务闪退（悬空观察者）的取证与**模拟器侧**兜底修复 |
| `reports/ZFR_v28fix_任务闪退根因修复.md` | v28fix：把 v11 删掉的注销循环加回来（**根因**）；含弹窗图片问题的代码链分析 |
| `reports/ZFR_任务闪退_通知观察者.md` | 任务闪退（悬空观察者）的取证与**模拟器侧**兜底修复 |
| `reports/ZFR_施肥飘字_长度限制复查.md` | 「189 字节装不下」的复查：是**格式**限制，不是硬限制 |
| `reports/ZFR_v29fix_施肥飘字还原.md` | v29fix：`.strings` 改存 OpenStep 文本，还原 ` %@施肥啦！` |
| `reports/ZFR_施肥僵尸_机制取证.md` | 「放僵尸也飘施肥字」的取证：是**园丁僵尸自动施肥**（设计行为），**§2.1 已订正** |
| `reports/ZFR_施肥僵尸_收益效果.md` | 被施肥的**地里僵尸**有什么收益：和作物一样**多拿一份市场价**（无僵尸专属效果） |
| `reports/ZFR_施肥飘字_表来源订正.md` | **订正**：这条飘字读的是 `Arial-BoldMT.strings`；含 VA≠文件偏移的教训 |
| `reports/fps60-report.md` | 帧率修复（30 → 60fps）的完整报告 |
| `archive/` | 前几轮的一次性探针脚本（结论的推导过程，保留） |
| `dumps/` | 仅保留被文档/报告点名的取证产物（`_zfz_*`、`_abil2.out.txt`、`_flags.out.txt`、`_reorg_moves.json`） |
| `perf/` | **空目录**，只作为测试脚本的输出位置（截图与日志已在 2026-09-23 清理） |

> **2026-09-23 清理**：删掉了 126 MB 的过程性产物 —— 旧会话的对话记录存档
> （`_claude_*`、`hist_*`、`history_*`、`session_*`、`analysis_hist_*`）、
> `__pycache__`、一个 19.6 MB 的死胡同构建产物、历代测试的截图与日志
> （`perf/` 218 个），以及无脚本写入的孤儿 dump。
> **判断依据**：这些文件没有任何在用脚本**读取**（引用清一色是写入），
> 且都能由 `_analysis/` 里现存的脚本重新跑出来；
> 被 `README`/`process.md`/技术报告**按文件名引用**的取证产物一律保留。
> `dumps/` 与 `perf/` 作为目录保留，因为多个脚本往里写输出。

跨会话记忆（Claude 侧）在
`C:\Users\<你的用户名>\.claude\projects\<claude-project-dir-mangled>\memory\`：
`zfr-alert-font-architecture.md`、`zfr-crash-fix-killed-localization.md`。

---

## 九、约定

- **回复用中文**（标识符、地址、字节、路径保持原样不翻译）。
- 改 IPA 前先读对应 `report.json`，改完必须跑独立验证器。
- 不碰 cave 区域，除非明确要动 helper。
- **根目录只放运行时和交付物**：新脚本进 `_analysis/`，新输出进 `_analysis/dumps/`，
  活代码进 `tools/`。临时文件用完就挪走，别留在根目录。
- 每个结论区分**逐字节验证**与**推断**；拿不准就说拿不准。
- **改了含中文的 `.ps1` 就跑 `_analysis\_ensure_bom.ps1`**（`edit` 工具会剥 BOM，
  见文件开头那条警告）。改完 `.ps1` 顺手 parse 一遍：
  `[System.Management.Automation.Language.Parser]::ParseFile(...)`。
- **改了 `GameManager.ps1` / `touchHLE.exe` / 交付的 IPA，必须重建 `Release`**：
  `_analysis\_build_release.ps1`，然后跑 `_verify_release.ps1` 与 `_release_e2e.ps1`。
  `Release\GameManager.ps1` 是**副本**，不同步就会出现「开发树好了、交付包还是旧的」。
- **换默认 IPA 要改三处**：`GameManager.ps1` 的 `Get-DefaultIpaPath` fallback、
  `launcher_selected_ipa.txt`、`_analysis\_build_release.ps1` 的 `$ipaName`。
- **动游戏存档前先快照**：跑任何会启动游戏的测试脚本前，
  把 `touchHLE\touchHLE_sandbox` 整个复制到 `$env:TEMP`，跑完再还原
  （现有脚本都这么做）。**主人的存档是真进度，不能被测试污染。**
- **别用 `Select-String` 直接搜 `touchHLE\zfr_last_run.log`** —— 它是累积文件，
  要先切到最后一个 `CPU emulation begins now.` 之后那段（见 6.5）。
- **模拟器路径一律走 `$hleRoot`**（`$script:HleDir`），**别硬编码 `touchHLE\`**；
  启动 touchHLE 时 `WorkingDirectory` 必须是 `$hleRoot`。踩过的坑：
  重构后 `_v28_boot.ps1` 等脚本仍把工作目录设成 `$root`，于是 touchHLE 在
  **根目录**重新建了一个空的 `touchHLE_sandbox\` 与 `touchHLE_log.txt` ——
  不报错，只是悄悄跑在错的沙箱上（**存档看起来"丢了"**）。重构后请检查
  `Get-ChildItem -Force | Where-Object Name -match '^touchHLE|^zfr'` 是否为空。
- **汇报时不许把「静态全绿」写成「已修好」**；游戏内验证由主人做（见 6.4 / 6.5）。
- **读内存一律 `sl.addr_to_file(va)`**，绝不 `data[va]`；**反汇编从方法入口开始**，
  别从任意地址起扫（Thumb 会漂相位）。见 5.7 那条 ★ —— 2026-09-20 有一次
  整段调查结论因此作废。
- **说「装不下 / 做不到」之前，先确认自己试过几种做法**：v19 的「189 字节装不下」
  只是「**二进制 plist** 装不下」，换 OpenStep 文本就装下了（见 5.12）。
  同理 v11 的「小泄漏不是正确性问题」也是没验证的判断（见 5.11）。
- **报告里写「附带修好了 X」之前，先把代码链读出来。** 本次我曾据一个
  低半字（`movw`）匹配就断言「弹窗的勾/叉图由 `countCurrent` 决定」，
  核对后发现那两张图其实是弹窗的**按钮**（target 是 `dismissAlertPositive:` /
  `dismissAlertNegative:`），逐行图另有来源。**扫描 CFString 引用必须配
  `movw`+`movt` 成对匹配**，只看低 16 位会撞出一堆假阳性。
