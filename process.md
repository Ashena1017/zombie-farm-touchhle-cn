# 待办清单（用户反馈批次 2）

> **2026-10-07 Android 首页状态标记对齐（#34）**：应用标题改长后，「准备就绪」仍绝对定位在标题行右侧，和标题文字重叠导致视觉偏斜。现把状态胶囊移入标题、副标题后的纵向布局，标题变化不再影响状态标记位置。`_analysis\_build_android_local.ps1` 构建及 APK 静态校验 PASS；APK `97,302,304 B` / SHA-256 `99F896A3E157E4BAD8C099FF8DE825EC9A97AC09E9F3EDB374D53968B932ABB8`。源码已推送 `master`（`7e8922914eb79710e8b32b5c9e2e1acb615be389`）；APK 和 Release 正文已更新至 `v29fix-platforms`，附件下载回读哈希一致、正文逐字节编码往返后逐字符一致。未启动游戏或访问 sandbox。详见 `HANDOVER.md` §30。
> **2026-10-07 Android 应用名称（#33）**：桌面标签、管理器标题栏与首页标题改为「Zombie Farm 游戏管理」，首页标题 20sp 避免与状态标记重叠。APK `97,302,247 B` / SHA-256 `1FDCAD2AE4F0474EB14A86E24202E19851E317F4DD176CC40872D0F76773160F`，内置 IPA 校验不变。Android APK 静态校验通过；GitHub `master` 和现有 `v29fix-platforms` Release 已更新，附件通过 API 下载回读校验。未启动 MuMu，未访问或写入 sandbox。详见 `HANDOVER.md` §29。
> **2026-10-07 双平台默认夜间 + 发行包清空存档（#30）**：Windows 日夜按钮明确居中；Windows 无主题状态文件时默认夜间，Android 新安装偏好默认夜间；README 截图换成 Android 夜间实拍，并分别说明 iPhone 原生 480×320 与 iPad 原生 1024×768、×1.5 后 1536×1152。发现 `_build_release.ps1` 曾把开发机 `touchHLE_sandbox\...\saveGame.bin2` 当作 starting save 复制进公开 Windows ZIP；现改为空 sandbox，游戏首次进入后自行创建存档，Release 校验器强制检查 sandbox 无文件；APK 校验器也拒绝打包 sandbox/save。Windows 42 文件 ZIP、Android APK 均已重建，通过 Release 独立启动、SELFTEST、UI 控件回归、Android 包静态校验；GitHub 原附件已替换，API 下载回读 SHA-256 相同。Release ZIP `95,055,963 B` / `0FC4DC8E3EF544C3945651F04434D883181586120E836E6953BBE374FBA49924`；APK `97,302,385 B` / `8644CB871D01C0DDFD28C7E4ED80620865EA2E6FB2B471EE8EA6823F1E96FED6`。源码已同步 `master`（远端 `3cae4df063a6ab95cc499f5ffbe1f6f6695b2050`）。开发机真实 sandbox 未被构建或测试修改。详见 `HANDOVER.md` §26。

> **2026-10-07 Windows 日夜图标视觉居中追加（#31）**：主人指出仅设置按钮文字 MiddleCenter 后，日间太阳字形仍看起来偏位。改为空按钮文字，在 Paint 中以 TextRenderer `HorizontalCenter | VerticalCenter | NoPadding | SingleLine` 按客户区居中绘制太阳/月亮，主题切换时显式 Invalidate。日间真实窗口截图 `_analysis\dumps\windows-day-icon-centered-review.png` 目视确认，GUI 控件回归与 Release standalone launch 45 秒通过；主题偏好测试前后字节恢复。Windows ZIP 仍为 42 文件、sandbox/save 条目为 0，已替换 GitHub 同名附件并通过 Assets API 下载回读哈希相同。新 ZIP `95,056,542 B` / `92C6D2B2D541B3C332DA1427DF4D8A447B89309B481A0446F5726A91D7F4D477`。详见 `HANDOVER.md` §27。

> **2026-10-07 日夜图标光学中心复核（#32）**：主人指出月亮观感仍偏。路径轮廓居中后，对实窗截图中的可见字形采样：太阳色心偏差 `(-0.01,-0.02) px`；月牙色心原偏 `(1.66,1.22) px`。为月牙按 DPI 加光学偏移，最终夜间截图色心偏差 `(0.10,-0.14) px`；当前可见轮廓边距左/右 `8/11 px` 是月牙轮廓非对称，色心则已在中心。最终逻辑位于 `_analysis\dumps\windows-night-icon-optically-centered.png`；SELFTEST、控件回归、空 sandbox Release 45 秒独立运行均 PASS。42 文件 Windows ZIP 无 sandbox/save，更新包 `95,057,453 B` / `84DE88543BF3D302657E6681F72E28D77F7E3EA5063995A1ECDBCB30B72F4461`，已替换同名 GitHub 附件，Assets API 下载回读哈希一致；源码已同步 `master`。

> **2026-10-07 Windows 系统标题栏配色**：DWM 标题栏现在跟随管理器日夜模式；夜间采用深色背景/浅色文字，日间恢复系统默认浅色标题栏。Windows 11 23H2 两种主题均已实窗截图确认；日夜切换控件回归与 Release 独立启动验证通过。旧 Windows 对自定义 caption color 的支持依系统版本而定。详见 `HANDOVER.md` §25。

> **2026-10-07 夜间模式控件收尾**：设置页组合框系统边框与箭头分隔线改为主题绘制，消除实测单像素纯白线；存档列表末列铺满宽度，清除右侧系统白块，夜间分隔线同步压暗。开发版三页实窗核验、控件回归与 Release 包验证通过，Release 已重建同步；未写入真实存档。详见 `HANDOVER.md` §24。

> **2026-10-07 Windows 启动异常复核**：截图报 `Visual Style handle creation operation did not succeed`，未展开 `Details`，没有调用栈。开发版与 Release 的 exe 均能打开界面，日夜按钮自动来回切换未复现；已发现并修正 Release 脚本落后开发版 4,336 B，重建后包内运行验证通过。根因仍未证实；若新版仍报错需展开 `Details`。详见 `HANDOVER.md` §23。
> **2026-10-07 Windows 管理器重构追加**：主人反馈旧版只是把设置移到右边；现为「游戏 / 设置 / 存档」三个独立页面，窗口按页面内容收缩，银白/灰紫/夜蓝/古金配色。游戏页实窗截图 `_analysis/dumps/windows-manager-redesign.png`（976 × 467）；`GameManager.ps1 -SelfTest`、布局/分辨率检查及控件回归通过。真实存档仅读取。详见 `HANDOVER.md` §22。此前 Windows 双栏与酒红版、Android 首轮主题记录见 §21，最终颜色和 Windows 结构按 §22。

> **2026-10-06 Android 全屏追加已完成**：顶部状态栏常驻的运行窗口为 `FORCE_NOT_FULLSCREEN`；Android `MainActivity` 在启动、恢复焦点和 SDL 重设窗口时保持沉浸式全屏，API 30+ 使用 `WindowInsetsController`，旧版保留 immersive-sticky 兼容。MuMu API 35 实测开始菜单/选择形象页顶部游戏像素由 `y=72` 变为 `y=0`，切桌面返回仍隐藏状态栏，边缘滑动可临时显示并自动收起；存档快照还原后 4 个文件哈希一致。APK `97270814` B / SHA-256 `00122762D11ADE481550E95953CAB836B594867D5B4B7349FC71F07457697A67`，内置 IPA 未变；详细证据、当前包与固定环境见 `HANDOVER.md` §18。

> **2026-10-06 Android 管理器追加已完成**：启动首页现为「ZF游戏管理」，内置 v29fix；其余 IPA 可通过系统文件选择器按需导入。版本/设备/倍率/FPS/帧率修复/跳过时间/货币/存档管理均进入原生管理页。隔离 instrumentation 30 项全过；MuMu API 35 最终包进入游戏开始菜单、完整备份并恢复，sandbox 四文件 SHA-256 与测试前快照相同。最终 APK `97298603` B / SHA-256 `CAE397A0901A1DCAE069834E6421D856819DAF84995298FFE0F8D9E61DBB7167`，内置 IPA `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`；固定工具路径及未测边界见 `HANDOVER.md` §19。

> **2026-10-06 Windows 备份恢复累计时间已修**：每个新 `saveGame.bin2.bak*` 备份有隐藏 `.zf-offset` 伴随元数据；恢复会回写备份时累计秒数，并先把当前存档与当前时间一起存成 `pre-restore`。旧备份没有元数据时只恢复存档、保留当前时间。删除/批量删除同时清理 sidecar。隔离自检覆盖往返恢复、旧备份兼容、损坏元数据拒绝及 sidecar 删除；全套 `GameManager.ps1 -SelfTest` PASS，真实 sandbox 5 个文件与 `%TEMP%` 快照逐字节一致。Release 已按构建脚本同步说明；细节见 `HANDOVER.md` §20。

> 基线：`fixed-fonts-v14fix.ipa`（sha256 `216A3339…9C51`），已验证可行 —— 图1/图2 确认
> 技能名已是中文，说明 Arial TTF 可用、CJK 分支生效。
> 本文件按顺序记录每一项的「现象 → 根因 → 修法 → 站点 → 验证」，做完一项标一项。

## 进度总览

| # | 图 | 问题 | 类型 | 状态 |
|---|---|---|---|---|
| 1 | 图3 | 底部信息框「已使用 Invasion Voucher!」道具名未翻译 | 本地化 | **v17 已修，实测通过**（显示「已使用立即入侵券！」） |
| 2 | 图4/图7 | 仓库物品详情面板标题/说明字号偏小 | 字号 | **全部收尾 ✅**（v21 变大 + v23 修裁切 + v24/v25/v26/v27 修位置；v27 实测通过，标题正中间） |
| 3 | 图5/图6 | 「瞬间成熟」使用后名字变回英文 `Insta-Grow` | 本地化 | **v15 已修好**（名字中文） |
| 4 | 图5 | 「瞬间成熟(10)」右括号被道具图标挡住 | 布局 | **v20 已修，实测通过**（`(10)` 不挡；`(9)` 偏左是右锚点的正常表现，非 bug） |
| 5 | 图8/图9 | 飘字 `+200eE` / `+1Ee` | 数据损坏 | **v16 + v17 已修，实测通过**（图1 显示 `120金币` `+2经验`） |
| 6 | 图10 | 商店购买确认框字号 | 字号 | **v18 已修，实测通过** |
| — | 图1 | 施肥时飘字乱码 | 数据损坏 | **v19 已修，实测通过**（「蝴蝶僵尸施肥」「+200金币」正常） |
| 7 | 图12 | 僵尸详情页文字改黑色 | 颜色 | **v22 + v23 已修，实测通过**（能力确认变黑） |
| 8 | 图12 | 陵墓按钮字号 +3 | 字号 | **全部收尾 ✅**（v21/v23 变大实测通过 → v24 去粗体实测通过） |
| — | 图2 | 「瞬间成熟 (2967885)」数字异常 | **我的回归** | **v16 已修**（实测正常；「翻地没文字」是石像工具本身不给飘字，非 bug） |
| 9 | 任务闪退 | 升级后完成任务瞬间闪退：`Object 0x… (class "_touchHLE_NSString") does not respond to selector "incrementCount:"`，退出码 -1073741819 | **我们自己的回归（v11 IPA 补丁删掉了 requirements 注销循环）** | **两层都已修，主人实测通过**：① 模拟器侧 `NSNotificationCenter` 清理悬空观察者（iOS 9+ 语义）；② **v28fix** 把 `stopListening` 的逐条注销循环加回来（根因）。主人另外反馈**任务弹窗的图片显示也正常了**（弹窗每行读 requirement 的 `spriteFilename` 与 `countCurrent`，与悬空观察者多投递一次 `incrementCount:` 同源；机制分析见报告第 7 节，**未做对照截图**）；详见 `_analysis/reports/ZFR_v28fix_任务闪退根因修复.md` 与 `_analysis/reports/ZFR_任务闪退_通知观察者.md` |
| 10 | 图1 | 施肥飘字丢了前导空格和语气词（`%@施肥`） | **v19 自我缩限（格式判断错误）** | **v29fix 已构建，主人实测通过 ✅**（` %@施肥啦！` 正确显示）；已晋升为默认版本、已进 `Release`。详见 `_analysis/reports/ZFR_v29fix_施肥飘字还原.md` |
| 11 | 目录 | 开发树结构混乱，与 `./Release` 不一致 | 维护性 | **已完成**：模拟器相关全部移入 `touchHLE\`（见文末「目录重构」） |
| — | 游戏机制 | 「放僵尸/施肥」的疑问：不只种植物，往地上放僵尸也飘施肥字；被施肥的僵尸有什么效果？ | 机制取证（非缺陷） | **查清，结论：设计行为**。① 施肥是**园丁系僵尸自动触发**（按 `UnitStats.plist` 的 `fertilizeChance` 4%~12% 掷骰），走的是"放置单位"这条**与种植物共用**的路径；`%@` 是**施肥者**的名字不是被施肥对象。② **被施肥的僵尸地块和作物收益完全一样**：收获时**再发一份市场价**（= 双倍金币）+ 粒子特效；**没有僵尸专属效果**，因为收获结算代码**不区分 plant/zombie**（僵尸在数据模型里就是 `category='crop'`）。详见 `_analysis/reports/ZFR_施肥僵尸_机制取证.md` 与 `_analysis/reports/ZFR_施肥僵尸_收益效果.md` |
| — | 工具 | 一份新写的调查把**虚拟地址当文件偏移**用（差 `0x1000`），导致整段结论作废 | **工具级坑** | **已订正**：该 slice 的 VA 与文件偏移**全段差 0x1000**，`data[va]` 会静默读到隔壁数据。已写进 README 5.7 ★ 专节与第九节约定；订正见 `_analysis/reports/ZFR_施肥飘字_表来源订正.md`。**历代补丁/验证器未受影响**（`tools/` 全部走 `addr_to_file`） |
| 12 | 目录 | `zombie_farm\` 改名 `zombie_farm_ipa\`（根目录与 `Release\` 同步），管理器等引用同步 | 维护性 | **已完成**：`_analysis\_rename_ipa_dir.py` 一次性字节级替换（保 BOM，幂等，235 个文件），排除历史封存区（`archive\`/`reports\`）与 touchHLE 源码模块名（`zombie_farm.rs` 等）。功能面：`GameManager.ps1`（根+Release）SELFTEST PASS、IPA 下拉切换 PASS、布局/Release 校验 PASS。附带加固：SELFTEST 新增 **real save untouched** 守卫（测试前后对真实存档做 sha256 比对，跑测试前要先关游戏）——起因是主人看到 GUI 金币框显示 SELFTEST 的测试值 123456/654321 虚惊一场；核实为**输入框可编辑**（下方灰字「当前存档：…」才是真实读数），真实存档从未被动过（金币 135086/135261、脑子 4409 逐字节核实） |
| 13 | 文档 | `使用说明.txt`（Release 发给用户的运行说明）改成 HTML，看着更舒服 | 体验 | **已完成**：`Release\使用说明.html`（单文件、内联 CSS、系统字体、UTF-8 BOM，双击浏览器打开）。信息架构与措辞不变，只换载体：文件清单改成表格、路径/文件名等宽高亮、提示/警告用色块。源头在 `_analysis\_build_release.ps1` 的内嵌模板（Release 说明是**构建产物**不是源文件，直接改 Release 会被下次构建覆盖），同步更新 `_verify_layout_match.ps1` 的生成物清单；顺手修了原文档章节号笔误（两个「五、」→ 帧率/电脑要求/说明顺次为五/六/七）。验证：重建 Release PASS、`_verify_release.ps1`（含启动 45s）PASS、`_verify_layout_match.ps1` PASS、README 声明核验 PASS；渲染效果经无头 Edge 截图逐屏核对。新增 `_analysis\_html_preview.ps1` 一键预览工具（注意：无头 Edge 在这台机器上打不开非 ASCII 的 `file://` 路径，预览走 `%TEMP%` 英文副本，正式文件保持中文名） |
| 14 | 管理器 | 「启动并跳过时间」输入框：HH:MM 单框（要自己打冒号）→ 小时/分钟**两个数字框**，只填数字；并**记住上次数值**，下次打开预填 | 体验 | **已完成**：`NumericUpDown`（小时 0–9999、分钟 0–59，自带上下箭头、强制纯数字、数字居中显示）。记忆存 `launcher_skip_memory.txt`（根目录，与 `launcher_selected_ipa.txt` 并列，纯文本 `H:MM`；新增 `Read-SkipMemory`/`Save-SkipMemory` 读写辅助，损坏文件静默回退默认 6:00）。根目录与 `Release\GameManager.ps1` 已同步（hash 一致）。验证：记忆读写探针 `_skip_memory_test.ps1`（往返/边界/损坏 6 项全 PASS）；GUI 端到端截图 `_skip_dialog_shot.ps1`（预置 `6:15`→点按钮→对话框两框预填 6/15，实测通过）；SELFTEST PASS、布局校验 PASS（`launcher_skip_memory.txt` 登记为运行时状态）。**踩的坑**：① WinForms 控件类名是 `WindowsForms10.BUTTON.app.0.xxx` 不是裸 `Button`；② 模态对话框的按钮点击必须 `PostMessage`（异步），`SendMessage(BM_CLICK)` 会同步阻塞到对话框关闭、永远走不到截图 |
| 15 | 模拟器 | 游戏本身有双指捏合缩放，但 PC 上没有触摸屏，无法操作；希望**鼠标滚轮**控制放大缩小 | 体验 | **已实现，主人实测通过**：改的是 touchHLE 模拟器（`touchHLE-fork`），**不动游戏 IPA**。路线：滚轮 → 调用游戏自己的 `-[ZFFarmTileMap setZoomOutAmount:]`（游戏捏合手势走的就是这个 setter），因此瓦片/角色/粒子/相机全部由游戏原代码重排，等价于捏合而非硬缩放图层。改动 4 个文件：`window.rs`（新增 `Event::ZombieFarmZoomStep(i32)` + `E::MouseWheel` 捕获，**同一帧的多个滚轮刻度先累加再合成一个事件**，因为该 setter 在自身 0.01s 动画未结束时直接 return 不存储，快滚会丢刻度）、`objc/messages/zombie_farm.rs`（`zombie_farm_zoom_step`）、`objc/messages.rs` + `objc.rs`（导出）、`frameworks/uikit.rs`（事件分发）。步长乘性 `×1.08/刻度`（与游戏捏合一致，任意缩放级别手感相同；从默认 1.0 放大到上限 2.0 约 9 格、缩小到下限 0.2 约 21 格），范围钳制 0.2–2.0。**取证要点**：`zoomFactor`（ivar +0xd4）= 传给 CCScaleTo 的节点缩放，故值越大越「放大」；`-resetCamera` 传 `1.0`（`0x3f800000`）即中性值；setter 的钳制上限**随设备变**（iPhone 尺寸 1.0 / iPad 尺寸 2.0，下界 `0.9-width*0.01` 在 iPad 上为负、不生效），所以自留 0.2 下限防止地图缩没。**踩的坑**：fork 的 `vendor\{stb,dynarmic,openal-soft,SDL,boost}` 是指向 `touchHLE-trunk\vendor` 的 Junction，目录重构后路径少了一层 `touchHLE\` 全部失效 → 构建报 `vendor/openal-soft ... does not contain CMakeLists.txt`；用 `rmdir` 删掉失效 reparse point 再 `mklink /J` 重建即修复。构建基线 `_build_fork_now.ps1` 增量约 1m20s |
| 16 | 模拟器/管理器 | 分辨率选项不合适：想要 **2560×1440 / 1920×1080 / 1600×900 / 1280×720** 四个 16:9 档，并**保留** iPhone / iPad 原档，但**去掉它们的 scale 档**（iPhone×2、iPad×2、iPad×3） | 体验 | **已完成，实测通过**：模拟器新增 `--device-size=WIDTHxHEIGHT` 选项（`options.rs` 解析 + `Options.device_size`，尺寸归一化为短边在前、按当前朝向交换，仍乘 `--scale-hack`，1–8192 校验）。`window.rs` 新增 `size_for_orientation_or_override()`（窗口尺寸唯一入口）与 `logical_size()`（`Window::logical_size()`），并同步 `viewport()` / `size_unrotated_unscaled()`；三处 UIKit 上报屏幕尺寸的地方（`ui_screen.rs` 的 `UIScreen.bounds`、`ui_application.rs` 的 `statusBarFrame`、`zombie_farm.rs` 的 `getZEye`）改走 `logical_size()`，否则 app 会按错误 bounds 排版。**为什么必须新增选项**：窗口尺寸原本只能是 `设备尺寸 × scale-hack`，而 iPhone 基准 320×480（3:2）、iPad 768×1024（4:3），**任何组合都乘不出 16:9**。`--device-family` 仍保留，因为它同时决定 iPhone/iPad 的 UI idiom（`ui_device.rs` 的 `userInterfaceIdiom`），所以四个新档都配 `--device-family=ipad` + `--device-size=…` + `--scale-hack=1`。管理器 `device_size` 选项组重排为 4 个 16:9 + iPhone 480×320 + iPad 1024×768（默认 ipad-1），删掉 iPhone×2/iPad×2/iPad×3。验证：`_analysis\_device_size_e2e.ps1` 用 Win32 实测客户区，**1280×720 / 1600×900 / 1920×1080 / 2560×1440 全部精确匹配**，且 ipad=1024×768、iphone=480×320 未回归；`_analysis\_device_size_argtest.ps1` 确认非法值（bogus / 1280 / 0x720 / 99999x99999）全部拒绝；`_device_size_roundtrip.ps1` 6 档读写往返全 PASS；`GameManager.ps1 -SelfTest` PASS（**顺手修了它仍引用已删除的 `iphone-2` 的失效断言**，并新增「全部 device_size 档位往返」检查）。`OPTIONS_HELP.txt` 补了选项说明。dev 与 `Release\` 已同步（`touchHLE.exe` sha256 `D109B02A…`、`GameManager.ps1` sha256 `24E3EFBB…`）。**踩的坑**：`_build_fork_now.ps1` 只更新 `touchHLE_fork.exe`，E2E 却跑 `touchHLE.exe` → 首次实测 4 个新档「窗口没出现」，装上新二进制后才通过；另 `_device_size_argtest.ps1` 以仓库根为 CWD 跑，touchHLE 把 `touchHLE_log.txt` 写到了根目录，被布局校验抓出（已删） |
| 17 | 模拟器 | **DPI 缩放导致分辨率虚标**：本机桌面 2560×1440 / 150% 缩放，但选 1280×720 实际得到 1920×1080（正好 1.5 倍），画面被 Windows 位图拉伸变糊；选 2560×1440 实际 3840×2160，直接超出屏幕 | 正确性 | **已修，实测通过**：根因是 SDL 默认让进程 **DPI-unaware**，Windows 于是按缩放比位图拉伸窗口。修法：在 `window.rs` 里设 `SDL_WINDOWS_DPI_AWARENESS=permonitorv2`（`#[cfg(target_os = "windows")]`）。**关键顺序**：该 hint 必须在 `sdl2::init()`/`video()` **之前**设置 —— 我第一次写在 `sdl2::init()` 之后，重编后实测**完全没变**（仍 1.5 倍），移到最前才生效。修复后 Win32（DPI 感知）实测客户区**精确等于请求值**：1280×720→1280×720、1600×900→1600×900、1920×1080→1920×1080、2560×1440→2560×1440（前两档原来分别是 1920×1080 / 2400×1350）。2560×1440 档外框 2582×1496，比 2560×1440 屏幕各多 11px，故仍算略微超出（边框所致，非 bug），管理器提示已注明可改用全屏。**顺带纠正一个此前的错误结论**：README 里曾写「本机桌面 1707×960、2560×1440 超出桌面」，那 1707×960 是**非 DPI 感知进程看到的虚拟化值**（2560÷1.5=1707），真实桌面就是 2560×1440；已用 `_analysis\_dpi_probe.ps1`（先 `SetProcessDPIAware()` 再取 `GetSystemMetrics`）核实并改正 README |
| 18 | 管理器 | 分辨率下拉框按**从大到小**排：2560 → 1920 → 1600 → 1280 → iPad → iPhone | 体验 | **已完成，实测通过**：仅重排 `device_size.Choices` 顺序 + 同步调整 `Tip` 文案顺序。**重排暴露一个真隐患**：iPad 档的选项集（`--device-family=ipad --scale-hack=1`）是每个 16:9 档选项集的**子集**，而 `Read-OptionsFile` 原来取「第一个 Extra 全部命中」的选项 —— 旧顺序（16:9 在前）只是**碰巧**安全，一旦重排就会把 2560×1440 读成 iPad。已改为取**最具体**匹配（选项数最多者，并列取先出现者），彻底消除对顺序的依赖。验证：`_analysis\_res_order_check.ps1` 直接对**运行中的 GUI** 用 Win32 `CB_GETCOUNT`/`CB_GETLBTEXT` 读出下拉项，确认顺序为 `2560 × 1440 / 1920 × 1080 / 1600 × 900 / 1280 × 720 / iPad 1024 × 768 / iPhone 480 × 320`（PASS）；`_device_size_roundtrip.ps1` 新增两条断言 —— 「UI 顺序」与「无遮蔽」（遍历所有档对，确认任一行读回都是它自己）；`SelfTest` PASS。**踩的坑**：① 下拉弹出列表是独立窗口，`PrintWindow` 抓不到，所以改用读控件项来取证（截图只能证明默认值 iPad）；② `Add-Type` 的 C# 用到 `Bitmap` 必须加 `-ReferencedAssemblies System.Drawing`，否则报 COMPILER_ERRORS；③ 判断哪个 combo 是分辨率档不能只看「有 6 项」—— `fps_limit` 也是 6 项，得按内容匹配 |
| 19 | 管理器 | **16:9 四档画面被裁**：选 2560×1440 / 1920×1080 / 1600×900 时**底部状态栏（农场主 / 等级 / 金币）看不到**，而 iPad 1024×768 正常。用户问「是不是 ipa 不支持那些自定义分辨率」，并明确**不要黑边**，要求改成 **3:2** | 正确性 | **已改，游戏内待验证**：根因**不是** IPA 不支持 `--device-size`（该选项工作正常，Win32 实测客户区精确匹配），而是**宽高比**。游戏按 **4:3 布局、按宽度缩放**：窗口比 4:3 宽时，装下整个布局所需的高度就超过窗口高度，溢出的正好是底部那条 HUD。算术（布局需要 `768 × (宽/1024)`）：2560×1440 需 1920 实有 1440 裁 480；1920×1080 需 1440 实有 1080 裁 360；1600×900 需 1200 实有 900 裁 300；**iPad 1024×768 需 768 实有 768 —— 严丝合缝，所以它一直是对的**，这条恰好反证了根因。用户拒绝加黑边方案后改为 3:2（iPhone 原生比例，是能完整显示的最宽比例）：**保持原高度、把宽度收到 3:2** —— 2560×1440→**2160×1440**、1920×1080→**1620×1080**、1600×900→**1350×900**、1280×720→**1080×720**。**`--device-family` 必须从 `ipad` 改成 `iphone`**：4:3 的 iPad 布局在 3:2 画布上反而会把宽度撑爆；改档后 2160×1440 = 480×320 × 4.5，正好是 iPhone 基准的整数倍缩放，零溢出。**同时暴露并更新了遮蔽隐患**：子集关系从「iPad ⊂ 16:9 档」翻转成「**iPhone ⊂ 3:2 档**」，`Read-OptionsFile` 取最具体匹配的逻辑照旧正确，但注释与断言里认的还是旧的 iPad 档，已全部改到 iPhone 档。验证：`_device_size_roundtrip.ps1` **6 档往返 + UI 顺序 + 无遮蔽 全 PASS**；`GameManager.ps1 -SelfTest` PASS（**过程中踩到下拉文字长度上限**：`2160 × 1440  (3:2)` 24 字符触发新增的 `longest choice text ≤ 20` 断言 FAIL，去掉数字与括号间的空格、压缩双空格后压到 20 字符）；`_device_size_e2e.ps1` / `_resolution_fit.ps1` / `_device_size_argtest.ps1` / `_device_size_roundtrip.ps1` 里的旧尺寸常量已同步。README 的分辨率表、遮蔽说明、DPI 反例、`-Set` 示例全部改写，并新增一张「16:9 各档裁掉多少像素」的算术表。**注意**：iPhone/iPad 两个原生档**没有变**，`--device-size` 选项本身**一行代码都没动**（纯配置改动，未重编模拟器） |
| 20 | 模拟器 | 改 3:2 后**会不会把滚轮缩放的上限压到 1.0**？（#15 记过 setter 的钳制上限「随设备变」：iPhone 尺寸 1.0 / iPad 尺寸 2.0，而自定义四档刚把 `--device-family` 从 `ipad` 改成 `iphone`） | 正确性 | **已排查，无回归（静态取证）**：`_analysis\_zoom_clamp3.py` 反汇编 `-setZoomOutAmount:` 的分支确认，判据**不是 device family，而是 `winSize.width <= 480.0`**（`0x7e1a` 的 `vldr s0` 取常量 **480.0** → `vcmpe.f32` → `bgt 0x7e36`）：≤480 走 A 支（下界 `0.2`、上界 `1.0`），>480 走 B 支（下界 `0.9 - w*0.01`、上界 `2.0`）。**Windows 尺寸**决定分支，与 iPhone/iPad 无关。自定义四档宽度分别是 1080 / 1350 / 1620 / 2160，**全部 > 480**，所以都走 B 支、上界仍 **2.0**，滚轮放大能力与改档前完全一致；下界 `0.9 - 1080*0.01 = -9.9` 为负、不生效，仍由模拟器自留的 0.2 下限兜底。**顺带纠正 #15 里的表述**：那里把两个分支说成「随设备变」，准确说法是「**随窗口宽度变**」—— 因为 `--device-size` 让窗口宽度与 device family 解耦之后，这两者已经不是一回事了。反例正是 iPhone 原生档（480 宽）与 1080 宽的 3:2 档同样用 `--device-family=iphone`，却落在不同分支 |
| 21 | 分析工具 | `_analysis\_device_size_e2e.ps1` 量出的客户区**全是请求值的 2/3**（1080×720 报 720×480、iPad 原生报 682×512），看起来像 `--device-size` 坏了 | 正确性 | **已修工具，非产品 bug**：该脚本的 `Add-Type` C# **没有** `SetProcessDPIAware()`，所以进程是 DPI-unaware，Windows 把每个窗口都按 150% 缩放虚拟化上报，**×1.5 之后**实测值与请求值**逐个精确吻合**（720×1.5=1080、682×1.5=1023≈1024、320×1.5=480、213×1.5≈320）。连**原生 iPad/iPhone 两档也一起"错"**这一点就是判据 —— 产品若真坏了，不会连未改动的原生档也等比缩水。已在脚本里加 `SetProcessDPIAware()` 并调用，重跑后 **6 档全 PASS**（1080×720 / 1350×900 / 1620×1080 / 2160×1440 / ipad 1024×768 / iphone 480×320）。**教训**：这台机器 150% 缩放，任何读窗口几何的脚本都必须先 DPI 感知，否则量出来的数**自洽地错**（等比缩放不会露馅），极易误判成功能 bug —— #17 的 DPI 事故是同一种坑的另一个方向 |
| 22 | 管理器 | 改成 3:2 后主人实测**仍然不对**：「画面还是被拉扯过似的，似乎这是游戏不支持这么大的分辨率」。截图显示 logo 只占宽度约 16%（iPad 档占 60%）、底部 HUD 缩成一小条、背景被拉满 | 正确性 | **已定位并修，游戏内待验证** —— 主人的判断是对的，**根因和比例无关**。① **取证：游戏素材本身就是小图**。IPA 里 806 张 PNG，**最大仅 1024×768**（`MainMenuBG.png` 1024×683、`Default-LandscapeRight.png` 1024×768），**宽度中位数 88px**，≥1024 宽的只有 6 张（其中 3 张是 2048 的通用图集）。② **机制**：`UIScreen.bounds` 把模拟尺寸**原样**报给游戏（`ui_screen.rs`），所以 `--device-size` 给游戏的是**更大的逻辑画布**；游戏仍按原生点数（iPhone 480×320 / iPad 768×1024）画固定尺寸的 UI、把背景图拉伸铺满 → **UI 变小 + "拉扯"**。**3:2 只解决了裁切，解决不了这个**。③ **决定性 A/B 截图**（`_analysis\_layout_ab2.ps1`）：同为 3:2、同为 iPhone 家族，`--scale-hack=3`（1440×960）**排版完全正确、logo 居中、HUD 完整**；`--device-size=1620x1080` 则 UI 缩成一小撮。结论：**必须调 `--scale-hack`（保持模拟尺寸原生），绝不能调大 `--device-size`**。④ **新方案**：四档改为 `--device-family=iphone --device-size=481x321 --scale-hack={2,3,4}` → 窗口 962×642 / 1443×963 / 1924×1284，外加保留 iPad 1024×768。⑤ **为什么模拟尺寸是 481×321 而不是 480×320**：`-setZoomOutAmount:` 用 **`winSize.width <= 480.0`** 选钳制分支（#20 已反汇编确认常量 480.0），原生 480 会让**滚轮放大被钳死在 1.0、只能缩小** —— 实测 `iphone x4` 时日志正是 `left the zoom at 1.000 (requested 1.080)`。**481 只多 1 个点**，实测滚轮立刻恢复到 1.587，而 1 点在 ×4 下仅 4 个屏幕像素，排版无感。⑥ **验证**：`_zoomfix_check.ps1` 对 ×2/×3/×4 三档各跑一次（标题+农场+滚轮放大+缩小），**三档都比对通过**：窗口 962×642 / 1443×963 / 1924×1284 精确、农场 HUD 完整、滚轮放大全部到 1.587；`_device_size_e2e.ps1` 五档客户区全 PASS；`_device_size_roundtrip.ps1` 5 档往返 + 顺序 + 无遮蔽全 PASS；`SelfTest` PASS。**踩的坑**：① 第一版探针用 `CopyFromScreen` 抓图，但 `SetForegroundWindow` 在非前台进程上会失败（日志 `fg=False`），**抓到的全是浏览器**；改用 `PrintWindow(PW_RENDERCONTENT=2)` 后与 z-order 无关，才拿到真画面。② 探针**不能重定向 stdout/stderr**（管道塞满会卡住游戏），且**绝不能点击**（之前"卡死"的就是会点击的那个探针）。③ **选项文件会盖过命令行**（`lib.rs` 先应用文件、再应用命令行），所以测「原生档」时必须先把文件里的 `--device-size` 摘掉，否则三档测的是同一个尺寸 —— `_device_size_e2e.ps1` 因此也补了「暂存/还原选项文件」，否则两个原生档恒 FAIL |
| 23 | 管理器/模拟器 | 主人实测 **iPhone 档放大后「画面排布会非常糟糕」**（logo 变小、HUD 挤），要求**改用 iPad 档**；同时 **iPad ×2 = 2048×1536 超出 2560×1440 屏幕**，要求换个倍数 | 体验 | **已完成，实测通过**。① **改用 iPad 家族**：实测同样倍数下 iPhone 档排版确实差、iPad 档正常，所以四档自定义尺寸**全部改为 `--device-family=ipad`**，只改放大倍数。② **给 `--scale-hack` 加分数支持**（本 fork 扩展）：iPad 是 1024×768，整数倍只有 ×1=1024×768 与 ×2=2048×1536，而 ×2 外框约 2070×1592 **放不进 1440 高**（可用约 1368），中间档位是空的。现在接受 `3/2`、`5/4`、`13/8`（也接受 `1.5` 这种小数），**约分后存成分子/分母**，`window_size == logical * num / den`。**为什么用有理数而不是浮点**：scale-hack 同时决定**窗口大小**与 **renderbuffer 大小**，两者必须严格一致，整数运算不会积累舍入误差（`options.rs` 的 `scale_dim`/`unscale_dim`/`scale_dim_i`）。改动面：`options.rs`（解析 + `scale_hack_den` 字段 + 三个换算函数）、`window.rs`（`size_for_orientation[_or_override]`、`Window` 字段与全部调用点、`viewport()`）、`eagl.rs`（renderbufferStorage）、`gles_guest.rs`（`glViewport`/`glScissor`/`glRenderbufferStorageOES`/`glGetRenderbufferParameterivOES`，其中 scissor/viewport 用**有符号**换算，因为坐标可为负）、`composition.rs`（合成帧尺寸）。**app_picker 无需改动**（它的快捷按钮只产出整数倍）。③ **新四档**：1664×1248（×13/8）/ 1536×1152（×3/2）/ 1280×960（×5/4）/ iPad 1024×768 / iPhone 480×320，默认推荐 **1536×1152**。④ **验证**：`_device_size_e2e.ps1` 五档客户区**精确匹配**（1664×1248 / 1536×1152 / 1280×960 / 1024×768 / 480×320，DPI 感知）；`_zoomfix_check.ps1` 对 ×13/8、×3/2、×5/4 **逐档截图验证**（标题 + 农场 HUD + 滚轮放大到 1.587 + 缩小），**三档布局全部正确**；`_device_size_roundtrip.ps1` 5 档往返 + 顺序 + 无遮蔽全 PASS；`SelfTest` PASS；构建 `_build_fork_now.ps1` 通过（增量 1m26s，仅原有 warning） |
| 24 | 管理器 | 主人澄清：**不是**要超分替换 IPA 内图片，而是想确认**重构整个游戏**（例如用 Unity 重写）的可行性 | 调研 | **已给结论（见 README「重构可行性」节）**。取证要点：① **逻辑规模**：`__text` 2.86 MiB、**491 个类 / 9352 个方法**，其中 ZF* 游戏类 80 个 / 2217 方法，cocos2d（CC*）133 类 / 1319 方法，其余 278 类（ASIHTTPRequest、Flurry 广告、Facebook、UA 等第三方）5816 方法。按系统分：农场/地块 5 类 212 方法、僵尸/角色 11 类 292、战斗 11 类 347（`ZFFightMan` 单类 142）、任务 7 类 175、经济 13 类 406（`ZFMarketMenu` 104）、UI 15 类 484（`ZFGuiLayer` 单类 187）。② **内容数据**：130 个 plist，其中 **57 个是图集**（共 500 帧，硬编码 `textureRect` 坐标）、其余是**数据表** —— `TileProperties.plist` 576 项、`ZombieSheet.plist` 115、`Drops.plist` 74、`UnitStats.plist` 70，另有 40+ 个粒子 plist（每 47–48 项）、`Attacks.plist`、`FarmerSprites.plist`、4 个 `.tmx` 地图、3 个 `.fnt` 位图字体。③ **素材**：839 张 PNG（12.9 MiB）、58 个 wav、18 个 nib。④ **联网依赖**：二进制里有 **64 个 URL**，含 `api.zombiefarmgame.com`（市场/状态）、Facebook、以及一堆已死的广告 SDK（AdMob/Flurry/Jumptap/Millennial/UrbanAirship）；服务端逻辑（市场、社交、活动）**没有源码**，重写只能做离线版或自建后端。⑤ **引擎机制**：引擎是 **cocos2d**，二进制里保留了 `setContentScaleFactor:`/`updateContentScaleFactor`/`hasSuffix:` 等**高清素材通路**，但 **IPA 里一张 `-hd`/`@2x` 图都没有**（`-hd` 字面量也**没有任何代码引用**），且 `setContentScaleFactor:` 的 selref 槽位 **0 引用** —— 即这套 HD 机制是**死代码**，无法靠"放入 -hd 图"提升画质。⑥ **结论**：这不是"重构 IPA"能解决的，属于**从零重写一个游戏**：需要重建引擎层 + 2217 个方法的游戏逻辑 + 500 帧图集坐标 + 数据表语义 + 服务端替代方案；素材（图/音/地图/字体）**可直接复用**，是唯一能省的部分。**另附实测**：把 ×2 画面缩回 ×1 比对，**像素差仅 1.23/255（0.3%）** —— 放大只是把同样的画面变大，**不增加细节**，所以"更大窗口"永远无法替代"更高分辨率素材" |

| 25 | 模拟器 | 主人实测反馈：**按 scale 放大后光源位置异常** —— 「建筑 陵墓 门口的绿火，还有农民手上提灯，都"飘"在屏幕上，用原来 ipad 的分辨率打开就没这个问题」 | 修复 | **已修（framebuffer 感知的 scale-hack）**。根因靠 `TOUCHHLE_ZF_GL_TRACE=1` 实测得出，非推断：这游戏**每帧用自己的 FBO 做 render-to-texture**（`fbo 2` 挂 app 自建 1024×1024 纹理），它在 drawable 上设好 viewport 后**绑到自己的 FBO 继续画且不重设 viewport**；而 GL viewport 是**上下文粘滞状态**、不属于某个 framebuffer。老实现无条件把 `glViewport`/`glScissor` 乘 scale-hack，于是那趟 pass 继承了放大到 **1536×1152 的 viewport，比它 1024×1024 的目标纹理还大** → 被裁切/错位，发光贴图因而与场景脱节；scale=1 时两个空间重合所以看不出。修法：① 记录 guest 原始 viewport 矩形；② **每次 `glBindFramebufferOES` 按新渲染目标重新推导** host viewport（补偿粘滞性）；③ `zfr_gl_framebuffer_is_scaled` 只对 **touchHLE 自己分配的 drawable renderbuffer**（`eagl.rs` 登记）放大，app 自建纹理/renderbuffer **一律原尺寸**，答案按 `(context, fbo)` 缓存、附件变更即失效；④ `glRenderbufferStorageOES` 不再放大（该路径只创建 app 自己的 renderbuffer）。实测：scale=1 与 3/2 下 `fbo 1`(drawable) 分别 → `768x1024`/`1152x1536` 且 `scaled true`，`fbo 2`(app tex) **两种情况都是 `1024x768`、`scaled false`**。回归：`_device_size_e2e.ps1` 5/5 PASS、`_verify_layout_match.ps1` PASS、`GameManager -SelfTest` PASS、roundtrip PASS |

| 26 | 源码清理 | 主人指示：**「如果不需要 trunk 那就删掉吧，那是作者放着防 ai 的」**（指 `touchHLE-trunk\AGENTS.md`/`CLAUDE.md` 里的提示注入） | 清理 | **已删除 `touchHLE-trunk/`（79029 文件 / 0.82 GB）**，并顺带清掉每个脚本里的死引用。删前确认：① 全仓库**无任何代码/脚本引用** trunk（只搜到文字提及）；② fork 自带 `vendor`/`Cargo.lock`/`build.rs`/`.cargo`，源码 299 个 `.rs`（trunk 288）；③ trunk 里 **0 处** `zombie_farm` 提及（fork 有 1201 处），是纯上游 v0.2.3、无 `.git`、全部文件同一解压时间戳 —— 即**可重新下载的纯净上游**。⚠️ **但删除时踩到坑**：fork 的 `vendor/{stb,boost,openal-soft,SDL}` 是 **NTFS junction 指向 trunk 的 vendor**（`_build_fork.ps1` 当年为省下载量建的），删 trunk 后变死链接 → 编译挂在 `lib.c(12): fatal error C1083: 无法打开 ../../../vendor/stb/stb_image.h`。**我的疏漏**：删前只 grep 了**文本**引用，没检查**文件系统链接**。已修：新增 `_analysis\_restore_vendor.ps1` 把四个依赖**重新抓成 fork 自己的真实目录**（stb 449 / boost 74085 / openal-soft 498 / SDL 1743 文件，boost 复用 `_build_tools\downloads` 里的 133.7 MB 缓存 tar，SDL 按 pin 的 `07d0f51f`），`_build_fork.ps1` 改为只校验存在性、不再建 junction；另删掉 4 个只会编译已删 trunk 的死脚本（`_build_baseline`/`_build_fixed`/`_pin_vendor`/`_fetch_vendor`）和 1.5 GB 陈旧 `_build_tools\target`；`_verify_layout.ps1` 的 trunk 检查项换成 `touchHLE-fork/vendor`。复验：fork 编译通过、游戏内 scale 决策仍正确、`_verify_layout.ps1` PASS、`_verify_layout_match.ps1` PASS |
| 27 | 管理器 + 模拟器 | 主人要求给 `游戏管理.exe` 加两个功能：① **窗口大小/分辨率**——「左边可以选 ipad 形式的还是 iphone 形式的，右侧可以自定义 `--scale-hack` 的大小，要求预置 ×5/4、×4/3、×3/2，然后再来一个自定义选项，默认 ipad + 3/2 倍 scale」；② **自定义滚轮缩放倍率**，「默认 1.1」 | 功能 | **已完成，静态全绿 + 游戏内实测通过**。① **模拟器新增 `--zf-wheel-zoom-step=`**（`options.rs`：`ZF_WHEEL_ZOOM_STEP_DEFAULT=1.1`、`MIN=1.01`、`MAX=2.0`、`parse_wheel_zoom_step`；`zombie_farm.rs` 的 `zombie_farm_zoom_step` 从硬编码 `ZOMBIE_FARM_ZOOM_STEP=1.08` 改为读 `env.options.zf_wheel_zoom_step`），并写进 `OPTIONS_HELP.txt`。② **管理器把原来的 `device_size` 选项组拆成两个独立设置**：`window_family`（`--device-family=`，iPad/iPhone 两项）与 `window_scale`（`--scale-hack=`，×5/4 / ×4/3 / ×3/2 / 自定义，默认 `3/2`），再用新增的 `Row`/`ComboX`/`ComboW`/`CustomX` 布局键让两者**共用一行**，行尾 `LblWindowSize` **实时算出窗口大小**（`Get-WindowSizeForScale`，算法与 `options.rs` 的 `scale_dim` 一致：横向、分数精确运算、四舍五入加半个分母；超出屏幕变琥珀色）。自定义倍率用 **TextBox** 而非 NumericUpDown（NumericUpDown 表达不了 `7/4`，而把它四舍五入成小数会**偷偷改变窗口尺寸**），按 touchHLE 自己的文法校验；每次按键校验，**非法中间态（`1.`、`7/`、`abc`）不写文件**。③ 顺带把 `AllowCustom` 通用化（`CustomKind` = int/scale/decimal、`CustomInitial`、`CustomDecimals`/`CustomStep`/`CustomSuffix`），三个设置共用一套编辑器构造与 `Update-CustomEnabled`。**过程中发现并修掉两个真 bug**（都不是我引入的）：㈠ **「高速帧率修复」关掉后重开界面又变回「开启」**——开关型选项（`--xxx` 无值）在文件里只有"有/无"两态，读取器遇到"行存在但无此 token"时错误地回退到 `Default`（`Default` 的语义是**推荐值**，不是"缺席时代表什么"），于是 关掉 = 无 token = 回退 1；改为**只有整行都不存在**时才用 `Default`，行存在则返回 `'0'`。㈡ **`-Set` 写错 app id**——`-Set` 分支没有调用 `Initialize-CurrentIpa`，于是用文件顶部的**占位** id 写入另一行，而 GUI 与 `-ShowSettings` 读的是真正选中那行，两边**默默不一致**；现在先解析选中的 IPA，且输出带上 app id（`Saved for com.playforge.ZombieFarm.ZFR: …`）。④ **验证**：`GameManager -SelfTest` dev 与 Release **双 PASS**（新增：13 个预置值往返、**flag 开/关往返**、30 条取值校验含分数/除零/尾随字符、**10 组窗口尺寸算术**含 `3/2` 与 `1.75` 同值、以及**「每个选项恰好出现一次且无 `--device-size=` 退役项」**）；`_device_size_e2e.ps1` **六档客户区精确匹配**（1280×960 / **1365×1024** / 1536×1152 / 1664×1248 / 1024×768 / 480×320，DPI 感知）；`_gui_controls_test.ps1` **PASS**（新增窗口行三联测 + 滚轮三预置 + 自定义分数 `7/4` 落盘 + 非法文本不落盘 + 收尾还原推荐配置）；`_res_order_check.ps1` PASS（直接读运行中 GUI 的两个下拉框：`iPad>iPhone`、`×5/4>×4/3>×3/2>自定义`）；`_zoomfix_check.ps1` + `touchHLE_log.txt` 实测滚轮**每格恰好 ×1.1**（`1.000→1.100→1.210→1.331…`），改成 1.5 后**每格 ×1.5**（`1.000→1.500→2.000` 到上限 `→1.333→0.889…`）；`_verify_layout.ps1`/`_verify_layout_match.ps1`/`_verify_release.ps1` 全 PASS；`--zf-wheel-zoom-step` 参数校验实测（1.1/1.5/2.0 通过，1.0/0.5/2.5/abc/空/`3/2` 全部干净报错 `must be between 1.01 and 2`）。⑤ **踩的坑**：㈠ `edit` 会**剥掉 `.ps1` 的 BOM**，每次改完必须跑 `_analysis\_ensure_bom.ps1`（不跑就报一堆 `'30 帧'` 语法错误，因为 PS 5.1 用 ANSI 码页解码无 BOM 脚本）；㈡ PowerShell 变量名**大小写不敏感**，`$rowY` 与 `$script:RowY` 是**同一个变量**，`$rowY = $script:RowY[$row]` 一步就把哈希表毁成整数 → 改名 `$script:RowOffsets`；㈢ PS 5.1 把**弯引号 `“ ”` 当字符串定界符**（即使在双引号串里也是），状态栏文案只能用直引号；㈣ 测试脚本用 `CB_SETCURSEL` **不会触发** WinForms 的 `SelectedIndexChanged`，必须补发 `WM_COMMAND(CBN_SELCHANGE)`，而且**要发给顶层窗体**（发给 GroupBox 不会被转发，设置不会保存）—— 当时"实时标签变了、文件没变"正是这个原因，差点误判成保存 bug；㈤ 我一度把 `OPTIONS_HELP.txt` 复制进 `Release\`，被 `_verify_layout_match.ps1` 抓出——该文件是**运行时自动生成**的（`paths.rs` 里 `if !options_file.is_file()`），不该出现在交付包里；㈥ `_verify_release.ps1` 断言的 `Loading armv7 slice` 来自 `log_dbg!`（只在 `ENABLED_MODULES` 里才打印），**release 构建永远不会出现**，一直是假 FAIL，已换成 release 真会输出的 `iPad device family is chosen` 并改为**缺失即判失败**。另删掉 3 个**改动前就已失效**的脚本（`_device_e2e`/`_device_size_test`/`_window_size_test`，用的是早已移除的 `device_size`/`scale_hack`/`show_fps` 键） |
| 28 | 管理器 + 文档 | 主人两条要求：① **「去掉所有的问号和里面的内容吧，这个不需要了，只要 使用指南.html 里有内容就行」**；② **「窗口大小的 scale 数值弄成小数形式的吧，预设的 ×5/4、×4/3、×3/2 不用了，改成预设 ×1.25、×1.5、×1.75，然后自定义，默认 ×1.5」** | 体验 | **已完成，全部验证通过**。① **删掉 `?` 按钮与全部 `Tip` 文案**：`SettingDefs` 里 5 个设置的 `Tip` 字段（约 120 行中文）全部移除，`Show-SettingTip` 整个函数（86 行，含对话框构造与文本测量）删除，布局循环里的 `$btnHelp` 构造删除。腾出的横向空间给了行尾读数：宽度 116 → **164px**，`1792 × 1344` 这种四位数不再有被裁的风险。**说明文字没有丢，而是搬家**：`_analysis\_build_release.ps1` 的内嵌 HTML 模板新增第二节「设置都是什么意思」，逐项写清**游戏帧率**（含"提高帧率不会让时间走得更快"）、**滚轮缩放倍率**（乘法语义、1.01–2.00 的理由）、**窗口大小 / 分辨率**（左设备 + 右倍数的取值表、为什么倍数是小数而非整数、**为什么绝不能调大模拟屏幕**）、**显示模式**、**高速帧率修复**（CCFastDirector 每帧两次零超时调用）；另把原来重复的第五节「关于帧率」并进去并重排章节号，新增第七节「性能与清晰度小抄」表格。② **倍数改成小数预置**：`window_scale.Choices` 由 `5/4 / 4/3 / 3/2` 改为 **`1.25` / `1.5` / `1.75`**，`Default` 由 `3/2` 改为 **`1.5`**（窗口仍是 1536×1152，一个字都没变）；下拉文字加 `×` 前缀统一观感。**底层不受影响**：touchHLE 的 `parse_scale_factor` 收到 `1.5` 会**约分成 3/2** 再按整数运算，所以小数预置与分数完全等价 —— 由 `_device_size_e2e.ps1` 实测证实（`1.25` 与 `5/4` 都得 1280×960、`1.5` 与 `3/2` 都得 1536×1152）。自定义框仍是**文本框**：数字框表达不了 `13/8`，而四舍五入会**偷偷改变窗口尺寸**；默认值改为 `7/4`（既是分数、又等于预置 ×1.75，两重身份都能演示）。③ **验证**：`-SelfTest` dev+Release 双 PASS，新增两条断言 —— **「没有任何设置定义 `Tip`」**（防止界面又长出没人要的帮助入口）与**「每个预置倍率都放得进当前屏幕」**；`_gui_controls_test.ps1` PASS（含 x1.25 / x1.75 各自落盘且行尾读数跟随、iPhone×1.75=840×560、自定义 `7/4` 落盘）；`_res_order_check.ps1` PASS（`×1.25 > ×1.5 > ×1.75 > 自定义`）；`_device_size_e2e.ps1` **八档客户区精确匹配**；`_gui_tip_test.ps1` **PASS 且断言已反转**（原来是"必须恰好 4 个 `?` 按钮"，现在改成"**必须 0 个**"，并新增"`使用说明.html` 里确实写到了滚轮/设备/预置/帧率"——两边都不见了才会 FAIL）；`_verify_layout.ps1`/`_verify_layout_match.ps1`/`_verify_release.ps1` 全 PASS；`使用说明.html` 经无头 Edge 渲染逐屏核对（7 节 + 5 个子节，约 10.5 KB，无残留的 ×5/4 之类旧档）。④ **踩的坑**：㈠ **截图抓到了上一次运行遗留的窗口** —— `_gui_shot.ps1` 按标题找窗口，而我先前几次测试留下的 powershell 进程还在，于是"改完还有 6 个问号"，看起来像改动没生效；确认新窗口 hwnd 不同后重截才看到正确画面。**教训**：这台机器上做 GUI 截图前必须先确认没有遗留的同名窗口。㈡ `_gui_tip_test.ps1` 是 **ASCII 文件**，里面写字面中文路径会被 ANSI 码页解码成 `浣跨敤璇存槑.html`（mojibake），必须像该文件其它地方一样**用码位拼**（`[char]0x4F7F + …`）。㈢ 同一测试原来读"保存标签页的按钮"作为按钮存在性证据，但 WinForms **不会为没显示过的标签页创建控件句柄**，所以那些按钮在窗口树里根本不存在 —— 改成只查游戏标签页的按钮，保存页的按钮在该测试第三节（真正切到该页之后）才查。㈣ 该测试的"默认档被选中"断言依赖**上次遗留的设置**：`--scale-hack=3/2` 现在不是预置了，界面正确地显示为"自定义"，却被当成失败；已在启动 GUI 前先把推荐配置写一遍，让测试与机器状态无关 |
| 29 | 清理 + 交接 | 主人要求：**「项目内留了很多过往对话记录的文件，将那些不需要的清理干净吧，剩下对未来修改有用的」**，完成后**生成项目交接文本**（本会话过长，要去新会话继续） | 整理 | **已完成，回收 126.4 MB（155.7 → 29.3 MB 的过程性产物），全部验证套件重跑通过**。① **判据**（先取证再动手）：写脚本扫描 `_analysis/` + `tools/` + 全部文档，确认这些文件**没有任何在用脚本读取**（引用清一色是 `open(...,"w")` / `Set-Content` 这类**写入**），且**都能由现存脚本重新跑出来**；被 `README`/`process.md`/技术报告**按文件名引用**的一律保留。② **删除清单**：旧会话对话记录 45 个 / 21 MB（`_claude_assistant.txt`（169 KB 的逐条工具调用回放）、`_claude_human_msgs.txt`、`history_agent_*`、`history_user_text.txt`、`history_font_query*.txt`、`history_ord_*.txt`、`hist_*`、`session_*`、`analysis_hist_*`）；`__pycache__` 3 目录 / 260 个 `.pyc`；死胡同构建产物 `touchHLE_trunk_build_deadend.exe`（19.6 MB，是已删 trunk 的编译尝试）；`_analysis\perf\` 全部 218 个文件 / 75.6 MB（历代测试截图与日志）；`dumps/` 里无脚本写入的孤儿 dump 122 个；`_analysis\*.log` 过期日志（`_build_baseline`/`_build_fixed`/`_pin_vendor`/`_fetch_vendor`/`_fork_fetch` 等，对应脚本早已删除）与 16 张旧 GUI 截图。③ **保留清单**：`dumps/` 只剩被点名的取证产物（`_zfz_*` 施肥机制、`_abil2.out.txt` 13 MB、`_flags.out.txt` 10 MB、`_reorg_moves.json`）；`perf/` **保留为空目录**（`_e2e.ps1`/`_verify_release.ps1`/`_res_order_check.ps1`/`_layout_probe.ps1`/`_game_window_shot.ps1`/`_emitter_*.py` 等 6+ 个脚本往里写输出，删目录会让它们失败）；`reports/` 11 份技术报告；`archive/` 436 个旧探针脚本（**结论的推导过程只在这些脚本里**）；`touchHLE\*.backup-*` 4 个 exe 回滚点（README §2.5 明确列为回滚手段，且逐个哈希确认互不相同）。④ **文档同步**：重写 `_analysis\TECHNICAL.md`（原文大量描述已删内容 —— 它把 `reports/` 说成"历史报告与会话记录"、把 `dumps/` 说成"最大 14 MB"、还引用 `touchHLE-trunk/`）、更新主 README §8 的文件表与新增清理说明、`tidy_finish.py` 加 `HISTORICAL - do not run` 头（它的文件清单已过时，再跑会出错）。⑤ **新建 `HANDOVER.md`**：给新会话的交接稿 —— 当前状态、关键事实与全部哈希、三条常用工作流（改管理器 / 改模拟器 / 重建交付包）、这台机器的 8 个环境坑、当前设置模型表、文档地图（要找什么去哪里）、建议起手式。主 README 开头加了指向它的导语，`_verify_layout_match.ps1` 的 dev-only 清单加了它。⑥ **验证**：`-SelfTest` dev+Release 双 PASS、`_verify_layout.ps1`/`_verify_layout_match.ps1`/`_device_size_roundtrip.ps1` 全 PASS；另写了一次性核对脚本，把 `HANDOVER.md` 里 24 条**事实性声明**逐条对磁盘复核（文件存在性、IPA 字节数、5 个哈希、`perf/` 为空、`__pycache__`/trunk/deadend-exe 已消失、4 个备份、archive 与 reports 数量），**23 PASS**、1 条行数虚报 1 已订正。⑦ **踩的坑**：㈠ 我第一版清理函数命名为 `Kill`，**撞上 PowerShell 内置别名 `Stop-Process`**，于是 `Kill (Get-ChildItem ...)` 被解析成"把文件对象当进程停掉"，7 次报错、**一个文件都没删**（安全失败）——改用 `Remove-These` 后正常。**教训**：PowerShell 里别用 `Kill`/`Where`/`Select` 这类会被别名劫持的名字。㈡ **`Get-Content` 会吞行**：不带 `-Encoding UTF8` 时它按 ANSI 码页解码无 BOM 的 UTF-8 文件，中文尾字节与紧随的 `0x0A` 粘成一个字符，换行消失 —— `process.md` 真实 **1050** 行却只报 **726**、`TECHNICAL.md` 真实 **1776** 行只报 **1100**，我一度以为文档被 my own edit 截断。用 `[System.IO.File]::ReadAllLines($p, UTF8)` 复核才确认文件完好。这条已写进 `HANDOVER.md` §2.4。㈢ `_gui_shot.ps1` 按窗口标题找目标，**旧会话遗留的 manager 进程**会让它抓到旧窗口 —— 本会话早前就被骗过一次（以为问号没删掉）。 | 主人两条要求：① **「去掉所有的问号和里面的内容吧，这个不需要了，只要 使用指南.html 里有内容就行」**；② **「窗口大小的 scale 数值弄成小数形式的吧，预设的 ×5/4、×4/3、×3/2 不用了，改成预设 ×1.25、×1.5、×1.75，然后自定义，默认 ×1.5」** | 体验 | **已完成，全部验证通过**。① **删掉 `?` 按钮与全部 `Tip` 文案**：`SettingDefs` 里 5 个设置的 `Tip` 字段（约 120 行中文）全部移除，`Show-SettingTip` 整个函数（86 行，含对话框构造与文本测量）删除，布局循环里的 `$btnHelp` 构造删除。腾出的横向空间给了行尾读数：宽度 116 → **164px**，`1792 × 1344` 这种四位数不再有被裁的风险。**说明文字没有丢，而是搬家**：`_analysis\_build_release.ps1` 的内嵌 HTML 模板新增第二节「设置都是什么意思」，逐项写清**游戏帧率**（含"提高帧率不会让时间走得更快"）、**滚轮缩放倍率**（乘法语义、1.01–2.00 的理由）、**窗口大小 / 分辨率**（左设备 + 右倍数的取值表、为什么倍数是小数而非整数、**为什么绝不能调大模拟屏幕**）、**显示模式**、**高速帧率修复**（CCFastDirector 每帧两次零超时调用）；另把原来重复的第五节「关于帧率」并进去并重排章节号，新增第七节「性能与清晰度小抄」表格。② **倍数改成小数预置**：`window_scale.Choices` 由 `5/4 / 4/3 / 3/2` 改为 **`1.25` / `1.5` / `1.75`**，`Default` 由 `3/2` 改为 **`1.5`**（窗口仍是 1536×1152，一个字都没变）；下拉文字加 `×` 前缀统一观感。**底层不受影响**：touchHLE 的 `parse_scale_factor` 收到 `1.5` 会**约分成 3/2** 再按整数运算，所以小数预置与分数完全等价 —— 由 `_device_size_e2e.ps1` 实测证实（`1.25` 与 `5/4` 都得 1280×960、`1.5` 与 `3/2` 都得 1536×1152）。自定义框仍是**文本框**：数字框表达不了 `13/8`，而四舍五入会**偷偷改变窗口尺寸**；默认值改为 `7/4`（既是分数、又等于预置 ×1.75，两重身份都能演示）。③ **验证**：`-SelfTest` dev+Release 双 PASS，新增两条断言 —— **「没有任何设置定义 `Tip`」**（防止界面又长出没人要的帮助入口）与**「每个预置倍率都放得进当前屏幕」**；`_gui_controls_test.ps1` PASS（含 x1.25 / x1.75 各自落盘且行尾读数跟随、iPhone×1.75=840×560、自定义 `7/4` 落盘）；`_res_order_check.ps1` PASS（`×1.25 > ×1.5 > ×1.75 > 自定义`）；`_device_size_e2e.ps1` **八档客户区精确匹配**；`_gui_tip_test.ps1` **PASS 且断言已反转**（原来是"必须恰好 4 个 `?` 按钮"，现在改成"**必须 0 个**"，并新增"`使用说明.html` 里确实写到了滚轮/设备/预置/帧率"——两边都不见了才会 FAIL）；`_verify_layout.ps1`/`_verify_layout_match.ps1`/`_verify_release.ps1` 全 PASS；`使用说明.html` 经无头 Edge 渲染逐屏核对（7 节、7212 字节、无残留的 ×5/4 之类旧档）。④ **踩的坑**：㈠ **截图抓到了上一次运行遗留的窗口** —— `_gui_shot.ps1` 按标题找窗口，而我先前几次测试留下的 powershell 进程还在，于是"改完还有 6 个问号"，看起来像改动没生效；确认新窗口 hwnd 不同后重截才看到正确画面。**教训**：这台机器上做 GUI 截图前必须先确认没有遗留的同名窗口。㈡ `_gui_tip_test.ps1` 是 **ASCII 文件**，里面写字面中文路径会被 ANSI 码页解码成 `浣跨敤璇存槑.html`（mojibake），必须像该文件其它地方一样**用码位拼**（`[char]0x4F7F + …`）。㈢ 同一测试原来读"保存标签页的按钮"作为按钮存在性证据，但 WinForms **不会为没显示过的标签页创建控件句柄**，所以那些按钮在窗口树里根本不存在 —— 改成只查游戏标签页的按钮，保存页的按钮在该测试第三节（真正切到该页之后）才查。㈣ 该测试的"默认档被选中"断言依赖**上次遗留的设置**：`--scale-hack=3/2` 现在不是预置了，界面正确地显示为"自定义"，却被当成失败；已在启动 GUI 前先把推荐配置写一遍，让测试与机器状态无关 |



---

# Android ARM64（同步 Windows 修复 + 内置 v29fix IPA）

**需求**：将 Windows touchHLE fork 已启用的 Zombie Farm 修复同步到 Android ARM64 APK，并让 APK 自带当前 v29fix IPA，用户无需手动操作 `data` 文件。

**实现**：① Android Gradle 构建从 `zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa` 生成 APK asset，并同时生成 SHA-256 标记；② Android 启动时将 asset 原子安装到 `touchHLE_apps\Zombie_Farm_v29fix.ipa`，按哈希标记跳过未变化的 IPA，升级时自动更新；③ Android 专用默认 options 采用触屏配置：`--landscape-right --fps-limit=60 --device-family=iphone --non-blocking-zero-timeout-run-loop`，不设滚轮步进或 scale-hack（保留 iPhone 原生倍率），使用游戏已有的两指捏合输入；选项加载顺序保持通用默认 → ZFR Android 默认 → 用户 options；④ Android application id 改为 `org.touchhle.zombiefarm`、version code 为 2，避免未知签名下与旧安装冲突；文档提供构建及 APK 静态校验脚本。

**验证边界（后续实测追加）**：Windows 管理器、设置、布局与 Release 基线全绿。原始 APK（36,121,590 B）保留不覆盖；fixed APK 已成功构建并通过 `_analysis\_verify_android_package.ps1`：内置 IPA `59,564,493 B`，SHA-256 为 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`，默认选项与 arm64 native library 均通过核验。已安装到 MuMu `127.0.0.1:5557` 并启动：中文开始菜单可见，点击「开始游戏」后进程仍运行且游戏逻辑/存档继续，但游戏场景画面变黑；未见 `FATAL EXCEPTION`、`SIGSEGV`、`Panic` 或 `touchHLE crashed!`。因此当前是**切场景后的 Core Animation/GLES 合成输出待修**，不是 APK 闪退，静态结果也不能替代游戏内效果确认。证据与明日检查点已写入 `HANDOVER.md` §12。

**2026-10-06 实测追加**：保留 Android 默认 framebuffer 读回修复并清除临时诊断探针后，重建 APK SHA-256 `152B4E8F59CC136C12269C71A2B6A010728307983417928D0D4C3ED8297037D3`，静态包校验 PASS。MuMu 已可从开始菜单进入欢迎教程与形象选择页，黑屏现象未再出现；形象页头像列表上有稳定的棕色遮挡带，未完成对 Windows 的同 IPA 对照。初步指向 touchHLE Core Animation/UIScrollView 合成，而不是 IPA 缺少头像资源；`composition.rs` 有 `clipping/masksToBounds` 未实现 TODO，根因仍待复现/修复验证。短时取样未捕获闪黑，不代表所有进场时序都已证明稳定。测试后 MuMu force-stop 并干净重装 fixed APK，恢复测试前外部目录；`saveGame.bin2` 870 B 的 SHA-256 `05BD833C4A952C3A38BBFFB78D4071E775EBEB1F49BB326101FE81CA82086BAB` 与快照逐字节一致，应用已停止、无需 root。截图与详细边界见 `HANDOVER.md` §13。


**2026-10-06 形象页修复完成**：稳定页逐 draw 抓帧定位到 `GL_CLIP_PLANE0..3`；MuMu native `glClipPlanef` 存储原方程而未按 modelview 旋转/平移变换，误将列表裁成屏幕右侧约 100px。Android native GLES 现先求逆转置 eye-space plane，再在 identity modelview 下提交并恢复矩阵/mode；同时处理 fixed-point 入口，非 Android 原行为保留。撤销所有无效 offset/z-order/背景隐藏/depth/stencil 实验，删除活源码探针。无探针正式 APK 冷启动和头像列表左右滑动已在 MuMu 实测正常，3 项几何测试、构建/静态包核验 PASS。APK 97,270,439 B / SHA-256 `FAE0C10DBDB71FFCF075030CCEBC759CA35520BC81CF98461E968F457493F9AE`，与设备安装包一致；IPA 哈希未变。`AndroidEnterAvatar.exe` 已修复无控制台输入时的等待按键异常。证据及固定环境补充见 `HANDOVER.md` §16～§17；Windows 未改、未确认形象，真实手机与其它页面尚未覆盖。
# 目录重构（2026-09-20）

**要求**（主人原话）：

> 现在的文件结构有点混乱，将当前文件夹的结构同步成 ./release 里面那样吧。
> touchHLE 相关的内容就放 ./touchHLE 里面，外面放游戏管理相关内容。

**做法**：`_analysis\_reorg_touchhle.py`（同卷 `shutil.move`，秒级完成，幂等）。
移入 `touchHLE\` 的 19 项：`touchHLE.exe`、`touchHLE_fork.exe`、3 个 `.backup-*`、
`touchHLE_dylibs`/`_fonts`/`_sandbox`、两个 options 文件、`touchHLE_log.txt`、
`touchHLE_time_offset_seconds.txt`、`zfr_last_launch.txt`、`zfr_last_run.log`、
`zfrpatch_current.dylib`、`LICENSE`（是 touchHLE 的 MPL-2.0 文本），
以及 `touchHLE-fork`/`touchHLE-trunk`/`_build_tools`。

**留在外面**：`GameManager.ps1`/`游戏管理.exe`、三个辅助 `.ps1`、两个 `.bat`、
`使用教程.txt`、三个 VC++ DLL、`zombie_farm_ipa\`、`tools\`、`_analysis\`、`Release\`。

**为什么能这么放**：touchHLE 的资源按**当前工作目录**解析
（`src/paths.rs` 在 Windows 上返回 `Path::new(".")`），不是 exe 所在目录。
所以只要启动时把工作目录设成 `touchHLE\` 即可 —— `GameManager.ps1` 本来就这么做了
（`$script:HleDir` 早就会自动探测 `touchHLE\` 子目录，所以**管理器一行都不用改**）。

## 路径兼容写法（新脚本照抄）

```powershell
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root      # 旧的扁平布局
}
```

39 个脚本由 `_analysis\_reorg_fix_paths.py` 批量改写（幂等，已有 `$hleRoot` 就跳过）。

## 踩到的三个坑（都写进 README 第九节）

1. **`Start-Job` 作用域**：`_reorg_fix_paths.py` 最初把 `$hleRoot` 定义插在「第一个
   `param()` 块之后」，而 6 个脚本的第一个 `param()` 属于 **`Start-Job` 的 scriptblock** ——
   定义于是落进了 job 内部（那里没有 `$root`），且 `-ArgumentList` 仍传 `$root`。
   由 `_analysis\_reorg_fix_jobs.py` 修正（判据是**使用早于定义**，不是缩进）。
2. **`WorkingDirectory` 回归**：`_v28_boot.ps1` 等脚本把 touchHLE 的工作目录设成
   `$root`。重构后 touchHLE 就在**根目录**重新建了一个**空的** `touchHLE_sandbox\`
   与 `touchHLE_log.txt` —— **不报错**，只是悄悄跑在错的沙箱上（看起来像"存档丢了"）。
   4 个直接跑模拟器的脚本已改为 `$hleRoot`；跑 GUI 的脚本保持 `$root`（正确）。
3. **`_who_calls.py` 里有个游离 BOM**（U+FEFF 在文件中间），本来就编译不过，顺手清掉了。

## 验证

| 项 | 结果 |
|---|---|
| 全部 `.ps1` 语法解析 | 通过 |
| 全部 `.py` 编译 | 通过 |
| `GameManager.ps1 -SelfTest` | **SELFTEST: PASS**（含 "touchHLE.exe found"） |
| `_v28_boot.ps1`（v29fix，新布局） | **RESULT: PASS**；根目录零残留 |
| verifier 全套（22 个） | 全绿 |
| `_build_release.ps1` 重建 | 成功，43 文件 114.9 MB |
| `_verify_release.ps1` | **RESULT: PASS** |
| `_release_e2e.ps1` | **RESULT: PASS** |

## 顺带完成：v29fix 晋升

主人实测确认 ` %@施肥啦！` 显示正确，故按约定晋升：

* `GameManager.ps1` 的 `Get-DefaultIpaPath` fallback → v29fix
* `launcher_selected_ipa.txt` → v29fix
* `_analysis\_build_release.ps1` 的 `$ipaName` → v29fix
* `Release\` 已重建，内含 v29fix

**回滚**：v29 是新增文件，在管理器里选回 v28fix 即可。

> **参考存档已作废（主人 2026-09-20 明确说不需要了）。**
> `RestoreTestSave.ps1` 依赖的 `Documents\saveGame.bin2.bak` 已不存在，
> 全树只剩 `_analysis\save_backups_safe\saveGame.bin2`（926 B，读不出任务段）。
> 沙箱里现在是主人的真实进度（11,259 B，questCount=1，ID 6 = [9,3]），
> `Release\` 的起始存档就是它。**不要再去追查或"恢复"那个 .bak。**

---

# v29fix（#10 施肥飘字：把 v19 缩短掉的两个码元还回来）

**产物**：`...fixed-fonts-v29fix.ipa`，sha256 `E5951F94…9DED`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v29.py`，verifier `_analysis/_verify_v29fix.py`（**全绿**）。
改的是**两个 `.strings` 成员**，可执行文件**一个字节都没动**。

用户指令（本轮输入）：

> 所以你能把没显示的字弄回来？能不能把那个「了」改成「啦」？
> → 可以可以，那感叹号也补上吧

最终值：`Fertilized by %@!` → **` %@施肥啦！`**（前导空格 + 啦 + 全角 `！`）

## 根因：v19 的「189 字节装不下」是**格式**限制，不是硬限制

v19 试的全是**二进制 plist**，忠实文本要 193 字节 > 189 槽位，于是把值缩短成
`%@施肥`。但 `.strings` 的经典格式是 **OpenStep 文本**，压缩率好得多：

| 序列化格式 | 原始 | 最小 DEFLATE | 对 189 槽位 |
|---|---|---|---|
| 二进制 plist | 257 | **193** | 超 4 ← 当年卡这 |
| XML plist | 646 | 328 | 超 139 |
| **OpenStep 文本 + `\U` 转义** | 390 | **182** | **装得下，余 7** |

换格式后**更长的忠实文本反而更小**。游戏读得懂 —— 加载路径是
`localizedStringForKey:` → `dictionaryWithContentsOfURL:` → `deserialize_plist_from_file`
→ `plist::Value::from_reader`，而 plist 1.8.0 的 `Reader::init` 在 XML 解析失败后
**会回退 OpenStep/ASCII reader**（文档原文 "a plist of **any encoding**"）。
已用**同版本 crate 编译探针**、喂**出货文件里真实的成员字节**实测通过。

## 为什么用全角 `！`

用户只说「感叹号也补上」，没指定半/全角。选全角是因为游戏自己的本地化习惯：
`zh-Hans` 的中文值里全角 `！` **500** 处 vs ASCII `!` **67** 处，
而且 `啦！` 这个组合**本来就有**（`ZOMBIE FARM GOES SOCIAL!` →
`僵尸农场更新到社交版啦！`）。要改半角只需改 `FERT_VALUE` 一个常量（184 字节，更宽裕）。

## 两个格式坑（实测，已写进 README 5.12）

1. **大括号必需**：裸 `"k" = "v";` 列表报 `ExpectedEndOfEventStream`。
2. **不能直接写 UTF-8**：ASCII reader 按 1:1 映射 → 中文变 Latin-1 乱码，
   非 ASCII 必须写 `\Uxxxx`。

> 附带教训：**验证「值对不对」不要用中文字面量当期望值**。
> `_v29_loader_probe.ps1` 第一版因 PowerShell 写出无 BOM 的 UTF-8，
> 对一个**字节完全相同**的字符串报了 WRONG。改成**逐码点比对**后立刻通过。

## 验证状态

| 层 | 结果 |
|---|---|
| patcher dry-run + 落盘 | 通过（含 sha256 前置守卫） |
| `_verify_v29fix.py`（独立） | **ALL CHECKS PASSED**（`csize` 保持 189、范围外零字节变化） |
| `_v29_loader_probe.ps1`（真加载器） | **PASS**（两个成员都解出 ` %@施肥啦！`） |
| 启动冒烟 | **PASS**（`panic: False`，存活到结束） |
| **游戏内实测** | **已通过 —— 主人实测确认**（2026-09-20：「字符已经正确显示了」） |

**已晋升**：`Release/`、`GameManager.ps1` fallback、`launcher_selected_ipa.txt`
三处均已指向 v29fix。v29 是**新增文件**，回滚就是在管理器里选回 v28fix。

---

# v18fix

**产物**：`...fixed-fonts-v18fix.ipa`，sha256 `D84A536B…B55CE4`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v18.py`，verifier `_analysis/_verify_v18fix.py`（全绿）。
4 个站点，**每个只改 1 个字节**（immediate 的低位）。

## 字号是怎么编进代码里的

游戏用 IEEE-754 浮点表示字号，而且**放在通用寄存器里当参数传**：

```
ARM    mov  rX, #0x1a00000       ; 低位半字
       orr  rX, rX, #0x40000000  ; → 0x41a00000 = 20.0
Thumb  movs rX, #0
       movt rX, #0x41a0          ; → 20.0
```

v5 那轮真正的全部动作就是 **`20.0 → 24.0`（标题档）** 和 **`14.0 → 18.0`（正文档）**。
所以：**在一个 alert window 工厂里孤立出现的 `20.0` 就是它的标题字号**
（`ZFAlertWindowStorageItem` 每个 slice 里正好只有 1 个 20.0 和 1 个 18.0）。

## #2 仓库物品详情面板

`ZFAlertWindowStorageItem` **自己 override 了整个 slide-in 工厂**
（`alertWindowSlideInInformative:…:slideFromLeft:`），基类 `ZFAlertWindow -initWithWindow:`
的站点对它根本不执行 —— 和 v5 踩到的 `ZFAlertWindowFlurryOffer` 是同一个坑
（README 7.6 记过它，但当时判断为"刻意未动"）。

| slice | 站点 | 字节 |
|---|---|---|
| sub6 | `0x1aae94` `mov r3,#0x1a00000` | `1a36a0e3` → `1c36a0e3` |
| sub9 | `0x139d16` `movt r2,#0x41a0` | `c4f2a012` → `c4f2c012` |

正文那个 label 本来就是 18.0（`CCLabelTTF labelWithString:fontName:'AmericanTypewriter-Bold'
fontSize:18.0`，sub9 `0x139e06`），不用动。

## #6 商店购买确认框

**不是** `-unlockItem:`（v6 已修），而是 `-[ZFMarketMenu checkBoughtItem:]` 里
**另一份同样的"工厂重建"代码**：

```
sub9 0x4e5fa  movt r3, #0x4160      ; 14.0
sub9 0x4e600  add  r2, pc           ; CFSTR 'AmericanTypewriter'
sub9 0x4e606  str  r3, [sp, #0xc]   ; fontSize 槽位
sub9 0x4e610  blx  objc_msgSend     ; labelWithString:dimensions:alignment:fontName:fontSize:
```

**原字节和 v6 的站点一模一样**，这本身就是最强的旁证：

| | sub6 | sub9 |
|---|---|---|
| v6 `-unlockItem:` | `0x6a49c` `1626a0e3`→`1926a0e3` | `0x4d6f4` `c4f26013`→`c4f29013` |
| **v18 `-checkBoughtItem:`** | `0x6b7c8` `1626a0e3`→`1926a0e3` | `0x4e5fa` `c4f26013`→`c4f29013` |

## 仍然待查

- ~~**#4**~~、~~**#2**~~、~~**#7**~~、~~**#8**~~ 见下面的 v21/v22 章节。

---

# v21fix（#2 + #8）

**产物**：`...fixed-fonts-v21fix.ipa`，sha256 `358D2887…C2052`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v21.py`，verifier `_analysis/_verify_v21fix.py`（全绿）。
6 个站点，每个 4 字节。

## #2 仓库物品详情面板 —— v18 为什么白改

先纠正 v18 的误判。`ZFAlertWindowStorageItem` **不自己建标题/说明**，
它的工厂方法第一件事就是调基类：

```
sub9 0x139bd4  blx objc_msgSend  ← 基类 +[ZFAlertWindow alertWindowSlideInInformative:…]
sub9 0x139c5e  getChildByTag:(0xc9) ; 0x139c74 removeChild:cleanup:
sub9 0x139d1a  makeWindow:…       ← 换一个更大的自定义窗体，再 addChild:z:tag: 挂到 0xc9
sub9 0x139e0c  labelWithString:'AmericanTypewriter-Bold' 18.0  ← 这是**礼物按钮**的文字
```

- `0x139d16` 那个被 v18 改成 24.0 的常量，是 `makeWindow:` 的**布局参数**（原来 20.0），
  跟字号无关 —— 所以实测没变化。（本轮**不动它**：值保持 v18 的现状。）
- `0x139e06` 的 18.0 label，字符串取自 `[r7+0x48]`，按 12 参数的 gift 版签名换算正好是
  **`withGiftButtonText`**，即「发送礼物」按钮，不是标题。

真正的标题/说明在基类里（`_analysis/_t2_base.txt`）：

| 角色 | 站点 | 字号 | 备注 |
|---|---|---|---|
| `title1` | sub9 `0x76b7a`（`movt r3,#0x4190`） | **18.0** | 建完立刻 `setTitle1:` + `setColor:(0,0,0)` |
| `body1` | sub9 `0x76de8`（`movt r0,#0x4140`） | **12.0** | `setBody1:` |

**为什么敢改基类**：`_analysis/_t2_users.py` 全库扫描确认，这个基类工厂在**整个二进制里
只有两个调用者** —— `ZFAlertWindowStorageItem` 自己（`0x139bd4`）和
`-[ZFGuiLayer displayAlertSlideInInformative:…]`（`0x18d62`），两个都在仓库面板这条路上。
所以 18→24 / 12→18 只会影响这一个面板，不可能波及别的弹窗。

| slice | 站点 | 变化 |
|---|---|---|
| sub9 | `0x76b7a` `c4f29013` → `c4f2c013` | title1 18.0 → 24.0 |
| sub9 | `0x76de8` `c4f24010` → `c4f29010` | body1 12.0 → 18.0 |
| sub6 | `0x0a31a4` `1936a0e3` → `0735a0e3` | 同上（ARM：`mov r3,#lo` + `orr #0x40000000`） |
| sub6 | `0x0a3464` `0535a0e3` → `1936a0e3` | 同上 |

> ARM 的 `mov rD,#imm` 是**8 位立即数循环右移**，所以 17.0 那种值编码出来是
> `mov r3,#0x1880000` = `62 37 a0 e3`（不是直觉上的 `0x88…`）。
> v21 的 patcher 自己搜索 rotation 并用 capstone 反解回浮点来自检。

## #8 陵墓按钮 +3

`ZFZombieMenu -initLowerMenu` 里 'Mausoleum' 走
`localizedStringForKey:` → `labelWithString:fontName:'AmericanTypewriter-Bold'`，
字号 **14.0**，结果写进 ivar `lowerMenuLabel1`（`+0x124`），紧接着
`setColor:(0,0,0)`（**本来就是黑色**）。

| slice | 站点 | 变化 |
|---|---|---|
| sub9 | `0xd290a` `c4f26010` → `c4f28810` | 14.0 → 17.0 |
| sub6 | `0x11efc4` `1636a0e3` → `6237a0e3` | 14.0 → 17.0 |

（process.md 之前列的三个候选 —— `-initElements+0x44e` 12.0、`-displayPage:+0x326` 15.0、
`ZFMausoleumMenu -initElements+0x43c` 22.0 —— 全部是猜的，实际都不是：前两个是分隔线
/页数 label，第三个是陵墓**页面标题**的位图字体。）

---

# v22fix（#7）

**产物**：`...fixed-fonts-v22fix.ipa`，sha256 `BD99FD79…2EA3`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v22.py`，verifier `_analysis/_verify_v22fix.py`（全绿）。
1 个 stub（sub9 `0x1138c8`，44 字节）+ 5 个改道点（每个 4 字节）。
**sub6 一个字节都没动**（见文末说明）。

## 五个标签为什么是白的

`ZFZombieMenu` 里有一处**语言分叉**（`_analysis/_t2_base.txt` 之外，0xd0480 附近）：

```
if ([[[NSLocale preferredLanguages] objectAtIndex:0] isEqualToString:@"zh-Hant"]) → TTF 分支
if (… isEqualToString:@"zh-Hans"]) → TTF 分支
if (… isEqualToString:@"ja"])      → TTF 分支
否则                                → 位图字体分支（ABD26.fnt）
```

zone 是 zh-Hans，所以走 TTF：五个 caption 都是
`+[CCLabelTTF labelWithString:fontName:'Arial' fontSize:…]`，**全程没有任何 `setColor:`**
→ cocos2d 默认的**白色**。

| 站点 | 归属 | 文字 | 字号 / 缩放 |
|---|---|---|---|
| sub9 `0xcf962` | `-initRightMenu` | STATS → 数值 | 30.0 / 0.46 |
| sub9 `0xcfaf0` | `-initRightMenu` | ABILITY → 能力 | 30.0 / 0.46 |
| sub9 `0xd0582` | `-initStatDisplay` | POWER → 力量 | 26.0 / 0.54 |
| sub9 `0xd05d2` | `-initStatDisplay` | LIFE → 生命 | 26.0 / 0.54 |
| sub9 `0xd061c` | `-initStatDisplay` | SPEED → 速度 | 26.0 / 0.54 |

（`_analysis/_t7_sweep.py` 遍历**所有**类，确认 TTF 分支里
`CFSTR 'STATS'/'ABILITY'/'POWER'/'LIFE'/'SPEED'` 的 label 工厂只有这五处。）

## 修法：透传栈参数的 wrapper stub

五个站点的 `blx objc_msgSend`（4 字节）改成 `bl 0x1138c8`。stub 先照原样完成创建，
再对新 label 发一次 `setColor:(0,0,0)`：

```
sub   sp, #8                 ; 帧开在调用方栈参数**下面**，[sp+8] 还是 fontSize
str.w lr, [sp, #4]
ldr.w r12, [sp, #8]          ; 取出调用方的 fontSize
str.w r12, [sp]              ; 摆到内层 objc_msgSend 该读的位置
blx   objc_msgSend           ; r0 = 新 label
str   r0, [sp]
ldr   r1, [pc, #0x10]        ; @selector(setColor:)（cave 里的字面量 0x2d16e7）
eors  r2, r2                 ; ccColor3B black
eors  r3, r3
blx   objc_msgSend
ldr   r0, [sp]               ; label 当返回值还回去
ldr.w lr, [sp, #4]
add   sp, #8
bx    lr
```

- `labelWithString:fontName:fontSize:` 的**第三个参数在栈上**，所以不能在调用前
  `push`（v16 的回归就是这么来的）。这里反过来往下开帧、把参数搬进自己的 `[sp]`，
  两次调用之间 `sp` 不变 → 调用方看到的效果和一条裸 `blx` 完全一致。
- 只碰 caller-saved（r0–r3、r12），`sp`/`lr` 复原，**不碰 r4–r11**。
- 坑：16 位 `sub sp, #imm7` 的立即数**以 4 为单位** —— `0xb082` 才是 `sub sp,#8`。

## 放哪：`0x1138c8`（紧挨着 v17 的 cave）

`0x1138a0..0x1138c5` 是 v17 的 stub+字面量，它**盖掉的是一个孤立函数的序言**。
既然序言已经没了，这个函数体在任何情况下都不可达 —— 所以从 `0x1138c8` 往后接着用
**不增加任何新风险**。`_analysis/_v21_refs.py 0x1138a0 0x113a40` 也证实：
该区间除了 v17 自己在 `0x54272` 的改道之外，**没有任何分支或 pc 相对引用**。
新增占用：sub9 `0x1138c8..0x1138f3`（已写进 README 5.10 与 FORBIDDEN_PRIOR）。

## 为什么这轮没打 sub6

`bl`+stub 的做法在 ARM 侧要重写一套（寄存器保存布局不同），而
**touchHLE 执行的是 sub9**（README 第二节已证）。为了不让一个高风险的
新代码块同时进两个 slice，本项**只改 sub9**，并让 verifier 断言
"**sub6 这一片逐字节未变**"。如果以后要在真机上跑 sub6，需要补一个 ARM 版 stub。

---

# v23fix（v21/v22 实测后的三个收尾）

**产物**：`...fixed-fonts-v23fix.ipa`，sha256 `4179AF10…4028`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v23.py`，verifier `_analysis/_verify_v23fix.py`（全绿）。
1 个新 stub（sub9 `0x1138f4`，22 字节）+ 4 个站点。

用户实测结论（本轮输入）：
- ✅ #2 仓库面板 标题/说明 正确变大，**但「瞬间收获」四个字下半部分被裁**
- ✅ #7 数值/力量/生命/速度 正确变黑，**但「能力」仍是白的**
- ✅ #8 陵墓按钮正确变大 3 号，**还要再大 2 号**
- 补充：#7 里提到的「力量/生命/速度 旁边的数字」**不存在** —— 那三条是**星星**，
  不是数字，所以没有"数字没显示"这回事（我上一轮的猜测作废）。

## (1) 标题被裁：dimensions 盒子只有 20px 高

`title1` 用的是五参数工厂（`_analysis/_v23_recon.py` 逐指令跟踪）：

```
0x76aaa  movt r5, #0x41a0        ; r5 = 20.0 —— 同时被 makeWindow: 的第一个参数用
0x76b8a  stm.w sp, {r5, fp}      ; [sp] = dimensions.height = 20.0, [sp+4] = alignment = 1
0x76b92  movt r5, #0x4348        ; r5 = 200.0 → 0x76b9c mov r3, r5  (dimensions.width)
0x76b9e  blx objc_msgSend        ; labelWithString:dimensions:alignment:fontName:fontSize:
```

`r5` 的那个 20.0 **被 `makeWindow:` 共用**，所以不能直接改常量（会动到窗体圆角）。
改成 v23 的做法：把 `0x76b9e` 改道到一个新 stub，只重写 `[sp]`：

```
movw  r12, #0x0000
movt  r12, #0x4208        ; 34.0
str.w r12, [sp]           ; dimensions.height: 20.0 -> 34.0
movw  r12, #0x014c
movt  r12, #0x002d        ; objc_msgSend (ARM)
bx    r12                 ; ★ bx 不写 lr → 直接返回到调用方下一条
```

**为什么加高度就够**：cocos2d 的 `labelWithString:dimensions:...` 把文字**顶对齐**画进
这个盒子里 —— 这正是"顶部完好、底部被切"的原因。所以盒子加高后，**底边（原来的裁切线）
不动，字往上长**（20 → 34 正好覆盖 24pt 的实际行高），不会把标题顶出标题栏。

> 站点：sub9 `0x76b9e` `59f2d6ea` → `9cf0a9fe`（`bl 0x1138f4`）。

## (2) 「能力」为什么还是白的

`-initRightMenu` 在创建完 `abilityTabLabel`（ivar `+0x12c`）后，**显式把它设成白色**：

```
0xcfb1a  ldr.w r0, [sl, r8]     ; r8 = 0x12c
0xcfb1e  mvn   r2, #0xff000000  ; r2 = 0x00FFFFFF = white
0xcfb24  blx   objc_msgSend     ; [abilityTabLabel setColor:white]
```

`数值`（`statsLabel`, `+0x128`）没有这一句，所以 v22 直接生效。
v23 把 `mvn r2, #0xff000000`（`6ff07f42`）换成 `mov.w r2, #0`（`4ff00002`）。

> 同一方法里 `0xcf858` 的 `setColor:(0x8fcfdf)` 是分隔线的颜色，与标签无关。

## (3) 陵墓 17 → 19

| slice | 站点 | 变化 |
|---|---|---|
| sub9 | `0xd290a` `c4f28810` → `c4f29810` | 17.0 → 19.0 |
| sub6 | `0x11efc4` `6237a0e3` → `6637a0e3` | 17.0 → 19.0 |

**sub6 这轮只改了这一个站点**；(1)(2) 两个 stub 类改动仍然只在 sub9（理由同上）。

---

# v27fix（v26 实测后：标题再往上 2px）

**产物**：`...fixed-fonts-v27fix.ipa`，sha256 `3D4CA38B…03AAC131`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v27.py`，verifier `_analysis/_verify_v27fix.py`（全绿）。
1 个站点，1 个字节（`16` → `14`），**没有新 stub，sub6 逐字节未变**。

用户指令（本轮输入）：再往上 2px。

| 版本 | C | 字顶 | 相对上版 |
|---|---|---|---|
| v24 | −27 | 24（= 原始高度） | −21 |
| v25 | −24 | 27 | +3 |
| v26 | −22 | 29 | +2 |
| **v27** | **−20** | **31** | **+2** |

盒子高度仍是 34px，不会重新裁切；离 v23 顶出去的 45 还差 14px，方向安全。
站点：sub9 `0x76d0e` `c3ff160f` → `c3ff140f`
（`vmov.f32 d16, #-22.0` → `#-20.0`，capstone 反解确认。）

---

# v26fix（v25 实测后：标题再往上 2px）

**产物**：`...fixed-fonts-v26fix.ipa`，sha256 `E845ABFE…AC49CE`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v26.py`，verifier `_analysis/_verify_v26fix.py`（全绿）。
1 个站点，1 个字节（`18` → `16`），**没有新 stub，sub6 逐字节未变**。

用户实测结论（本轮输入）：v25 的标题"离中间还差一点点，还是偏下了点，再往上调一点"。

## 微调：C = −24 → −22，字顶再上移 2px

同一公式（`字的顶边 = 1.5 × 盒子高度 + C`，盒子仍是 v23 的 34px）：

| 版本 | C | 字顶 | 相对上版 |
|---|---|---|---|
| v23 | −6 | 45（顶出去） | — |
| v24 | −27 | 24（= 原始高度） | −21 |
| v25 | −24 | 27 | +3 |
| **v26** | **−22** | **29** | **+2** |

盒子高度不动，不会重新裁切。站点：sub9 `0x76d0e` `c3ff180f` → `c3ff160f`
（`vmov.f32 d16, #-24.0` → `#-22.0`，capstone 反解确认；
同字段 −16…−28 逐度可调，若仍偏上/偏下，报 px 数继续微调。）

> 教训：`_verify_v26fix.py` 起初是用 PowerShell 字符串替换从 v25 版克隆的，
> 但 `-replace` 把文件按系统默认编码（非 UTF-8）回写，中文期望值全变成
> mojibake，10 条 CFString 检查挂掉。改用 Python（UTF-8）逐条精确替换重建
> 后全绿。以后克隆含中文的脚本一律用 Python 做。

---

# v25fix（v24 实测后的标题微调）

**产物**：`...fixed-fonts-v25fix.ipa`，sha256 `144B1CB8…0E490DE5`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v25.py`，verifier `_analysis/_verify_v25fix.py`（全绿）。
1 个站点，1 个字节（`1b` → `18`），**没有新 stub，sub6 逐字节未变**。

用户实测结论（本轮输入）：
- v24 的标题完整显示了 ✅ 但**有点偏下**（图1 vs 图2：往中间靠）
- 陵墓去粗体 ✅（v24 的第二项一次通过）

## 微调：C = −27 → −24，字顶上移 3px

同一公式（`字的顶边 = 1.5 × 盒子高度 + C`，盒子仍是 v23 的 34px）：

| 版本 | C | 字顶 | 相对 v24 |
|---|---|---|---|
| v23 | −6 | 45 | +21（顶出去了） |
| v24 | −27 | 24（= 原始高度） | 0 |
| **v25** | **−24** | **27** | **+3** |

即往标题栏上沿方向**上移 3px**，回到视觉中心；盒子高度不动，不会重新裁切。

站点：sub9 `0x76d0e` `c3ff1b0f` → `c3ff180f`
（`vmov.f32 d16, #-27.0` → `#-24.0`，capstone 反解确认；
同字段上 −16…−28 逐度可调 —— `_v24_vmov3.py` 方法复用于 v24 基准重测。
如果这次还是偏上/偏下，告诉我差多少 px，我按 1px 一档继续微调。）

---

# v24fix（v23 实测后的两个收尾）

**产物**：`...fixed-fonts-v24fix.ipa`，sha256 `564A7BB2…2DAE`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v24.py`，verifier `_analysis/_verify_v24fix.py`（全绿）。
3 个站点，每个 4 字节，**没有新 stub**。

用户实测结论（本轮输入）：
- 标题完整显示了 ✅ 但**太偏上**，"快顶到标题方框的外面了"
- 能力变黑 ✅
- 陵墓够大了 ✅ → **再去掉粗体即可**
- 「力量/生命/速度 旁边的数字」确认**不存在**（那三条是星星），上一轮的猜测作废

## (1) 标题偏上：位置公式也依赖 contentSize

v23 只把 dimensions 盒子从 20 抬到 34，但工厂随后用**盒子高度**算位置：

```
0x76d0a  vldr s0, [sp, #0xfc]       ; s0 = contentSize.height
0x76d0e  vmov.f32 d16, #-6.0        ; C
0x76d12  vmul.f32 d17, d0, d17      ; height * 0.5
0x76d16  vadd.f32 d0, d17, d16      ; y = height*0.5 + C
0x76d50  setPosition:(x, y)         ; 作用在 title1 上（anchor 已是 (0,0)）
```

label 的 anchor 是 `(0,0)`、字在盒子里**顶对齐**，于是

```
字的顶边 = y + height = 1.5 * height + C
```

- 原始：`1.5*20 − 6 = 24`
- v23 后：`1.5*34 − 6 = 45` ← **上移 21px**，正是用户看到的
- v24：`C = −27` → `1.5*34 − 27 = 24` ✅ 顶边回到原处，盒子够高不再裁切

站点：sub9 `0x76d0e` `c1ff180f` → `c3ff1b0f`（`vmov.f32 d16, #-6.0` → `#-27.0`）。

> `vmov.f32 dN, #imm` 是**立即数编码**（VFP modified immediate），不是字面量池。
> 定值方法：逐位翻转原指令、看哪几位会改变反汇编出来的常量，再在那几位上暴力搜索
> 目标值，最后用 capstone 反解确认。`-27.0` = `c3ff1b0f`。

## (2) 陵墓去粗体

`fontName` 参数就是一个 CFString 对象地址，把 `'AmericanTypewriter-Bold'` 换成
`'AmericanTypewriter'` 即可（不需要动字体表）：

| slice | 站点 | 变化 |
|---|---|---|
| sub9 | `0xd28fa` `40f6e823` → `43f21873` | `movw r3,#0xae8` → `#0x3718`；配后面的 `movt r3,#0x2d` + `add r3,pc`，目标 `0x3a33f0` → `0x3a6020` |
| sub6 | `0x11f1e4` `84843400` → `b4b03400` | 字面量 `0x348484` → `0x34b0b4`（`0x11efdc + word`，唯一读者 `0x11efc0`） |

`__cfstring` 每个对象 16 字节（`isa,flags,data,len`，flags=0x7c8），全库扫一遍就拿到
两个字体名字符串的地址（sub9：`0x3a33f0` / `0x3a6020`；sub6：`0x467460` / `0x46a090`）。

---

# v19fix

**产物**：`...fixed-fonts-v19fix.ipa`，sha256 `760D183F…96E206`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v19.py`，verifier `_analysis/_verify_v19fix.py`（全绿）。
改的是**两个 .strings 成员**，可执行文件**一个字节都没动**。

## 图1 施肥飘字乱码 —— 还有第三张字符串表

之前查漏了一个地方：**以字体名命名的字符串表**。

```
Payload/ZFR.app/Arial-BoldMT.strings
Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings
```

**基线里根本没有这两个成员** —— 是 codex 补丁新建的，8 条值全是乱码，
而且从 v15 到 v18 都没人碰过（只查过 `Localizable.strings` 和可执行文件）：

| key | 乱码 | 正确 |
|---|---|---|
| `Fertilized by %@!` | ` %@ČđĂ` | ` %@施肥了` ← 图1 红框 |
| `Cupid Zombie` | `āčĎĄĊ` | `丘比特僵尸` |
| `Flower Zombie` | `ĒĒĄĊ` | `花花僵尸` |
| `Garden Zombie` | `ćĀĄĊ` | `园丁僵尸` |
| `Green Flower Zombie` | `ĒĒĄĊ` | `花花僵尸` |
| `ZomBotanist` | `ďċĄĊ` | `生态僵尸` |
| `Zombee` | `ĔēĄĊ` | `蜜蜂僵尸` |
| `Zombutterfly` | `ĕĖĄĊ` | `蝴蝶僵尸` |

正确文本**不是猜的**：`zh-Hans/Localizable.strings` 里这 8 个 key 本来就有正确中文
（codex 在那边翻对了，在这边写坏了）。

### 踩到的坑：ZIP 固定槽位装不下

这个成员被 codex 塞进一个 **189 字节**的 DEFLATE 槽位（按它自己那套极好压缩的乱码算的）。
忠实还原需要 193 字节。试遍了：

```
level 1..9 × 5 种 strategy × memLevel 8/9 × wbits ±15   → 全是 193
5 种 key 排序                                            → 193~195
手写去重 bplist（16 个对象而非 17 个）                    → 还是 193
```

最后只能把施肥那条**缩短 2 个码元**：` %@施肥了` → `%@施肥`，降到 **188**，
刚好进槽（余量 1 字节）。代价是少一个前导空格和"了"。

因为长度变了，成员不能再做等宽字节替换，改为**重新序列化 plist** ——
所以 `usize` 字段（本地头 + 中央目录）必须一起改。v15 的 `replace_named_member`
只支持等长，v19 自己带了 `replace_member_resized`。
**压缩槽大小不变 → 归档里没有任何偏移移动 → IPA 仍是 59,564,493 字节。**

---

# v20fix

**产物**：`...fixed-fonts-v20fix.ipa`，sha256 `13320127…E4321`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v20.py`，verifier `_analysis/_verify_v20fix.py`（全绿）。
4 个站点：每个 slice 里 `__text` 字面量池的 2 个浮点（各 4 字节），共 16 字节。

## #4 —— 「瞬间成熟(10)」右括号被图标挡住【根因确认，修法：整体左移】

用户实测：只有 `(10)` 被挡，`(9)` 及更小数字不挡 —— 说明**遮挡只差几个像素**。

### 这段文字到底是什么

红框文字**不是弹窗**，是 `ZFToolsLayer` 的两个 ivar（`_analysis/_t4_tool3.py` 解出）：

| ivar | 偏移 | 内容 |
|---|---|---|
| `toolName` | `+0xd4`（`CCLabel`） | 文字本体 |
| `toolNameShadow` | `+0xd8`（`CCLabel`） | 黑色阴影（偏移 2px） |

`ZFToolManager -toolSelected:`（sub9 `0x20d3c`，sub6 `0x2b4ac`）用格式串
`'%@ (%i)        '`（CFString sub9 `0x3a4680` / sub6 `0x4686f0`，8 个尾空格）
组出 `瞬间成熟 (10)`，经 `-[ZFToolsLayer setToolLabel:]`（sub9 `0xe3154`）
`setString:` 到这两个 label 上。调用链上有 4 个 `setToolLabel:` 调用点
（`toolSelected:` 内 2 个：`0x20fe6` / `0x212e4`；
`onTileClickUp:forTool:` 内 2 个：`0x26da4` / `0x26df8`），但**全都只是换文字**，
没有一个碰位置 —— 所以"加空格"修不了（process.md 之前对 cocos2d 吃尾空格的
判断是对的，空格根本到不了布局）。

### 真正管位置的代码

两个 label 都在 `ZFToolsLayer -init` 里创建：

```
labelWithString:'Multi Tool' fontName:'AmericanTypewriter-Bold' fontSize:20.0
setPosition:(winWidth/2 + xoff, 25.0)
setColor: white
setAnchorPoint:(1.0, 0.5)      ← 右锚点：label 的右缘钉在 x 上
addChild:z: / setOpacity:
```

- sub9：label1（toolName）在 `0xdfbc0`，`xoff = -56.0`（`vldr @0xdfbc8` ← 池 `0xdfac0`）；
  label2（shadow）在 `0xdfcc6`，`xoff = -54.0`（`vldr @0xdfcce` ← 池 `0xdfac4`）。
  y 都是 `movt r3,#0x41c8` = 25.0。
- sub6：label1 `xoff = -56.0`（`vldr @0x130dc0` ← 池 `0x130c98`，y = 25.0
  即 `mov #0x1c80000 | orr #0x40000000` = 0x41c80000）；
  label2 `xoff = -54.0`（`vldr @0x130ec8` ← 池 `0x130c9c`，y = 27.0 = 0x41d80000）。

因为是**右锚点**，`x` 钉的是 label 的**右缘** —— `(10)` 比 `(9)` 宽出来的几个像素
正好顶进沙漏图标。修法：把两个右缘都左移 4px：

| label | 池 | before | after |
|---|---|---|---|
| toolName | sub6 `0x130c98` / sub9 `0xdfac0` | -56.0（`000060c2`） | **-60.0**（`000070c2`） |
| shadow | sub6 `0x130c9c` / sub9 `0xdfac4` | -54.0（`000058c2`） | **-58.0**（`000068c2`） |

全二进制扫描确认每个池常量**只有一个 `vldr` 读者**（verifier 第 4 节逐个断言），
所以改动不可能影响别处。label2（shadow）的 y=27.0 保持和 label1 的 y=25.0 的
2px 差（只动 x）。

> 风险如实说：这是从"只差几个像素"反推的 4px 平移，没有逐像素量过图标位置。
> 如果实测 `(10)` 露出来了但左边空太多 / 还是差 1px，告诉我，我按同一手法微调。

### 后续：`(9)` 比 `(10)` 更靠左一点？—— 不是两个函数，是右锚点的正常表现

用户：v20 之后不挡了，但 `(9)` 和 `(10)` 的位置"不是很同步"，问是不是设置位置的
函数不一样、能不能统一。

结论：**只有一个位置函数，不用统一 —— 右缘已经是对齐的**（`_analysis/_t4_toolpos.py`、
`_t4_msgnames.py` 为证）：

- 全 `ZFToolsLayer` 逐方法扫描 `setPosition:` / `setAnchorPoint:`（sub9）：
  命中只在 `-init`（toolName/toolNameShadow 各一处，即 v20 改的那两处）、
  `updateInvasionLabel:`（顶栏入侵 label，`+0x108` 的 ivar，和工具条无关）、
  `setGiftTime:`（礼物菜单）。**`toolSelected:` 里一个 `setPosition:` 都没有** ——
  4 个 `setToolLabel:` 调用点（`0x20fe6` / `0x212e4` / `0x26da4` / `0x26df8`）全都
  只换文字，不碰位置。
- label 是**右锚点**（anchor 1.0, 0.5）：右缘钉死在 `winWidth/2 − 60`，
  不管几个字，**右缘永远在同一 x 上**。`(9)` 比 `(10)` 窄，所以它的左缘更靠右 ——
  看起来就是"(9) 整体偏左/偏小"，这是右对齐文字的正常行为，不是 bug。
- 反过来想：如果改成左锚点去"统一左缘"，右缘就会随字数伸缩，`(10)` 又会顶进图标 ——
  正是 v20 修掉的问题。所以**保持现状是对的**。

---

# v18fix 的实测结论

- ✅ 商店购买确认框正文变大了（#6 成功）
- ❌ 仓库物品详情面板**没变化** —— 说明 `0x139d16` 那个 `20.0` 不是标题字号，
  而是 `-[ZFMenu makeWindow:corner:bar:file:color:bcorner:bbar:side:]` 的**布局参数**。
  该类里唯一的文字 label 是 `0x139e06` 的 18.0（`AmericanTypewriter-Bold`），
  另一个 10.0（`0x139eea`）经查是**位置计算**（`vadd.f32 d0, d17, 10.0`），也不是字号。
  → 标题/说明到底在哪儿，需要下一轮继续查（面板的文字可能由调用方或 hud 图元绘制）。

---

# v17fix（本轮）

**产物**：`...fixed-fonts-v17fix.ipa`，sha256 `73F434FF…1AA261`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v17.py`，verifier `_analysis/_verify_v17fix.py`（全绿）。
7 个站点：sub9 `0x1138a0` +37（新 stub + 字面量）、sub9 `0x54272` +4（改道）、
4×CFString 的 data/size、sub6 `0x177534` +11（字面量）。

## ★ 工具级 bug：Thumb `add rd, pc` 的 PC 不按 4 对齐

这是本轮最重要的发现，解释了为什么 #1 卡了两轮。

**规则更正**（README 5.8 之前记的是错的）：

| 指令 | PC 基址 |
|---|---|
| `ldr rD, [pc, #imm]`（字面量池） | `Align(addr+4, 4)` ← **字对齐** |
| `add rD, pc`（16 位 T1，高寄存器 ADD） | **`addr + 4`，不做 4 字节对齐** |

`_dis.py` 和 `_b2_all.py` / `_v17_cf.py` 一直用的是 `Align(addr+4,4)`，于是
**凡是位于 `addr % 4 == 2` 的 `add rd, pc`，解析结果都比真实目标低 2 字节** ——
正好落在**前一个 CFString 结构体内部**，`flags == 0x7c8` 检查失败，站点被静默丢弃。

`_analysis/_v17_pc.py` 用统计封死了这件事：56353 个已知 delta 的 `addr%4==2` 站点里，

```
unaligned: 6629 个正好落在真实 CFString 对象上
aligned  : 0
```

修好之后，sub9 的 `'%@ Used!'` 引用**立刻出现**在 `0x5424e`。
（`_dis.py` 已同步修正。）

## #1 —— 真正的站点

```
0x54140  -[ZFMarketMenu alertWindow:dismissedPositive:]
  0x54238  r1 = selref localizedStringForKey:value:table:
  0x5424e  add r2, pc   → CFSTR '%@ Used!'      (KEY)
  0x54256  add r3, pc   → cstring '%@ Used!'    (VALUE)
  0x54258  str.w sl, [sp]                        (table = nil)
  0x5425c  blx objc_msgSend   → r0 = '已使用%@！'
  0x5426a  mov r3, r5         ← 原始道具名 'Invasion Voucher'
  0x54272  blx objc_msgSend   ← ★ 改道到这里
  0x5428c  blx objc_msgSend   → displayToolTip:duration:
```

和 v15 的判断完全一致：**模板本地化了，`%@` 没有**。

### 为什么不能复用 v16 的 stub

v16 的 stub 把返回地址寄存在 **r4**。这里 r4 是**活的**——方法公共出口
`0x5441c` 有 `strb r1, [r4, r0]`（r4 == self），踩了会崩。

新 stub 不碰任何被调用者保存寄存器，用 **`bx` 尾调用**：

```
push.w {r0, r1, r2, lr}      ; 保存实参 + 返回地址
mov    r0, r3                ; 本地化 %@ 参数
bl     zfrLoc                ; 0x15140
mov    r3, r0
nop                          ; 让后面的 32 位指令落在 4 字节边界
movw   ip, #0x014c
movt   ip, #0x002d
pop.w  {r0, r1, r2, lr}      ; sp 回到调用点的值
bx     ip                    ; 尾调用：bx 不改 lr，objc_msgSend 直接返回 0x54276
```

`bx ip`（ip = 0x2d014c，bit0 = 0）和原来的 `blx` 一样切到 ARM 态；
lr 由调用点自己的 `bl` 设成 `0x54277`（Thumb 标记），所以 `bx lr` 能正确回来。

## #5 的第二条字符串（`+1Ee` 的真凶）

v16 修的是 `+%i经验`（`0x3a4e80` / `0x468ef0`），所以 `+200金币` 好了。
但用户读到的 ` +1Ee` **带前导空格**，来自**另一个** CFString：

| | 对象 | 基线内容 | codex 改成了 |
|---|---|---|---|
| sub6 | `0x476190` | `data=0x3d9bc2 size=6 ' +%dxp'` | `data=0x3d1c78 size=8 ' +%dĘę'` |
| sub9 | `0x3b2120` | `data=0x315bc2 size=6 ' +%dxp'` | `data=0x30dc78 size=8 ' +%dĘę'` |

codex 补丁**改的是指针**：它把 `data` 挪到自己刚弄坏的调试串
`ZFSaleEndDateDay +%dĘę` 的尾巴上，于是 ` +%dxp` 变成了 ` +%dĘę`（= ` +%d经验` 的乱码）。
**这条不是 v16 修的对象**，所以用户仍然看不到 `+1经验`。

v17：把正确的 UTF-8 ` +%d经验`（10 字节）放进每个 slice 自己的死代码，
重指 `data` + `size`（6 → 10）。

> 复用同一个字符串还有个好处：调试串 `ZFSaleEndDateDay +%dĘę` 不再被任何 CFString
> 引用，彻底变成死数据。

---

## v15 实测结果与 v16fix

### 意外收获：确认了 touchHLE 跑的是哪个 slice

v15 里 **只有 sub6 打了 `%@ Used!` 的补丁**，结果没生效；而数字异常
`瞬间成熟 (2967885)` **只可能来自 sub9 的 stub**（下面解释）。两条合起来
**证明 touchHLE 执行的是 sub9（Thumb）那一片**。

这解释了为什么 sub6 的那三个 #3 站点看起来"也修好了" —— 实际生效的是 sub9 的
`0x26d90`。

### 数字异常是我引入的回归（v16 修复）

v13 的 sub9 stub 结尾是：

```
push {r0, r1, r2, lr}
...
pop.w {r0, r1, r2, lr}
push {r4, lr}          ← 为了 8 字节栈对齐
blx  objc_msgSend      ← sp 比原调用点低 8 字节
pop  {r4, pc}
```

`stringWithFormat:` 的**第二个可变参数（`%i` 计数）是从 `[sp]` 读的**，而调用点
用 `str r0, [sp]` 把它放在**原来的 sp** 上。多出来的 `push {r4,lr}` 让 sp 下移 8 字节，
被调用方读到了错位的槽 —— 于是打印出一个指针（`2967885` = `0x2D4A0D`）。

sub6 的 ARM stub 没这个问题，因为 ARM 可以 `b objc_msgSend` 尾调用（sp 已还原）。
Thumb 不行：`objc_msgSend` 是 `__symbol_stub4` 里的 ARM 代码，调用要切状态、会毁掉 lr。

**v16 的新 sub9 stub（18 字节）**，让 sp 在 `blx` 时**正好等于**调用点的 sp：

```
push  {r0, r1, r2, lr}
mov   r0, r3
bl    zfrLoc
mov   r3, r0
pop   {r0, r1, r2, r4}    ← 原返回地址进 r4（三个站点的 r4 都已确认是死的）
blx   objc_msgSend        ← sp == 入口 sp
bx    r4
```

> 编码坑：`pop {...}` 写成 `0xBD17` 会**多弹一个 PC**（Thumb POP 的 bit8 是 PC），
> 必须是 `0xBC17`。这是 README 5.8③ 那条规则的第二次踩坑。

### #5 的真正根因（v15 只修了一半）

v15 修的是 `Localizable.strings`，所以 `+200金币(化肥作用)` 那条**确实好了**。
但纯 `+200eE` 来自**可执行文件里硬编码的 CFString**，它们的 UTF-8 数据被 codex
补丁写进了 **`__const` 段**（我之前的扫描只覆盖 `__cstring`，所以漏了）：

| CFString 对象 | 现在 | 应为 |
|---|---|---|
| sub6 `0x468b80` / sub9 `0x3a4b10` | `+%iėĚ` | `+%i金币` |
| sub6 `0x468ee0` / sub9 `0x3a4e70` | `-%iėĚ` | `-%i金币` |
| sub6 `0x468ef0` / sub9 `0x3a4e80` | `+%iĘę` | `+%i经验` |
| sub6 `0x469380` / sub9 `0x3a5310` | `%dėĚ` | `%d金币` |

这四条在 `__const` 里**紧挨着占满 32 字节，没有空余**，无法原地加长。
v16 的做法：把正确的 UTF-8 放进 `removeSeasonalQuests` 死代码里（sub6 `0x16d5b0` /
sub9 `0x10c490`，各 48 字节），再改写每个 CFString 的 **`data` 和 `size`** 两个字段。

> 注意 `size` 是**字节长度**（7/7/7/6 → 9/9/9/8），不是字符数 —— 两个字段都要改。

### #1 仍未解决

sub6 的 `0x7389c` 补丁无效，但 **sub9 里 `'%@ Used!'` 这个 CFString（`0x3a68d0`）
扫遍全段找不到任何代码引用**（CFString 对象只有一个，`_b2_all.py` 的逐方法走查
也确认了）。两条证据互相矛盾，说明还有一处我没找到的机制。

**v16 请重点复测图3**：如果还是英文，下一步换思路 —— 改从
`ZFGuiLayer -alertWindow:dismissedPositive:`（sub6 `0x1a6dc` 附近有 `'Invasion Voucher'`
CFString）或 `ZFStorageMenu -useItemWithIndex:` 入手，而不是继续找 `%@ Used!` 的调用点。

---

## v16fix

**产物**：`...fixed-fonts-v16fix.ipa`，sha256 `D51BE79A…25F4D`，59,564,493 字节。
patcher `tools/patch_zfr_b2_v16.py`，verifier `_analysis/_verify_v16fix.py`（全绿）。
19 个站点：1（sub9 stub）+ 2×48（字符串池）+ 2×4×2（CFString 的 data/size）。

---

## 5. 图8/图9 —— `+200eE` / `+1Ee`【根因已确认：数据损坏，v15fix 已修】

### 结论

**不是代码问题，是 `Localizable.strings` 里的中文值本身是乱码。**

`zh-Hans.lproj/Localizable.strings` 是二进制 plist（`bplist00`，190,993 字节），
字符串按 UTF-16BE 存。三个值被**上一轮 codex 补丁**改坏了 —— 它把「金子」批量
替换成「金币」（全文件 40+ 处都成功了），但有三条替换出了乱码：

| key | 现在（坏） | 应该是 | 码元数 |
|---|---|---|---|
| `'+%ig'` | `'+%iėĚ'` | `'+%i金币'` | 5 → 5 |
| `'+%ig (Fertilizer)'` | `'+%iėĚ(ĆđăĐ)'` | `'+%i金币(化肥作用)'` | 11 → 11 |
| `'+%ig (Fertilizer Bonus)'` | `'+%iėĚ(ĆđĈą)'` | `'+%i金币(化肥奖励)'` | 11 → 11 |

### 证据链

1. **原始文本**从**未改动的基线** `ZFR 1.0.zh-CN-unsigned.ipa` 里读出来了：
   `'+%i金子'` / `'+%i金子(化肥作用)'` / `'+%i金子(化肥奖励)'` —— 码元数完全一致。
2. **损害是 codex 补丁引入的**：基线里这三个值正常，`complete-final.ipa` 里就坏了。
3. **为什么看起来是「eE」**：`ė`(U+0117, e with dot above)、`Ě`(U+011A, E with caron)
   都是 Latin Extended-A，在 Arial 里渲染出来就是带小点/小勾的 `e` 和 `E`，
   小字号下读作 **`eE`**。`+200eE` = `+200ėĚ` ✓
4. **全库扫描**：zh-Hans 里只有这 3 个**值**是坏的（另有 6 个坏的**键**，见下）。
   zh-Hant 同样 3 个值。可执行文件里只有一条坏的调试串
   `ZFSaleEndDateDay +%dĘę`（sub6 `0x3d1c68` / sub9 `0x30dc68`），不进 UI。
5. **使用方**（确认这些 key 真的会被显示）：
   - `'+%ig (Fertilizer)'` ← `ZFTileManager -harvestEntireMap:`（`0x5643c`）、
     `ZFToolManager -popGameActionAndExecute:deltaTime:`（`0x3592c`）
   - `'+%ig (Fertilizer Bonus)'` ← 同一个方法（`0x36120`、`0x36a84`）
   —— 正好对应「瞬间收获」加肥料时的飘字。

### 修法

**等宽原地字节替换**：`'+%iėĚ'` 和 `'+%i金币'` 都是 5 个 UTF-16 码元 → plist 内部字节数
完全相同 → IPA 大小不变。zh-Hans 和 zh-Hant 各改 3 处（zh-Hant 用 `化肥獎勵`）。
替换时**必须从长到短**（长的包含短的前缀）。

### 遗留

图9 用户读作 `+1Ee`，形状指向 `Ęę`（= 经验），但**全库没有任何值是 `Ęę`**，
而 `'+%ixp'` → `'+%i经验'` 是正确的。**修完上面 3 条后让用户复测图9**：
若仍显示 `Ee`，说明走了另一条路径，那时用新证据再查。

### 附带发现（不修，无害）

codex 补丁**新增了 336 个 key**，其中 6 个键本身是乱码（`'+%iĘę'`、`' +%dĘę'`、
`'%dėĉ'`、`'-%iėĉ'`、`'+%iÁªèÈ™å'`、`'%@\n\n+%iÁªèÈ™å'`），在所有 lproj 里都有。
它们**不可达**（游戏不会拿乱码当 key 去查），所以只是垃圾数据。
基线里的 key 一个都没丢（`set(base) - set(cur)` 为空）。

---

## 1. 图3 —— 「已使用 Invasion Voucher!」【v15fix 已修】

**根因**：和 v13fix 修技能名**完全同一个模式** —— 模板本地化了，`%@` 没有。

站点：`ZFMarketMenu -alertWindow:dismissedPositive:` sub6 **`0x7389c`**

```
0x73878  r1 = SEL localizedStringForKey:value:table:
0x7387c  r2 = CFSTR '%@ Used!'        ← 模板，zh-Hans = '已使用%@！'
0x73884  bl objc_msgSend              → r0 = 本地化后的模板
0x73888  r1 = SEL stringWithFormat:
0x7388c  r2 = r0                      ← 格式串
0x73890  r0 = r6                      ← 接收者
0x73894  mov r3, r5                   ← ★ 原始道具名（'Invasion Voucher'）
0x7389c  bl objc_msgSend              ← ★ 已改道到 stub
```

`r5` 从方法入口 `0x73810: mov r5, r0` 来，中间没被写过；它同时还在
`0x7382c` 被传给 `[storageMenu useItemWithName:]` 当**查询键**，
所以**只能改 `r3` 这个参数，不能改 `r5` 本身**。

**sub9 没有对应站点**：sub9 里 `'%@ Used!'` 这个 CFString（`0x3a68d0`）**没有任何
代码引用**。（两个 slice 各自独立编译，这一处结构不同。）

---

## 3. 图5/图6 —— 「瞬间成熟」使用后变英文【v15fix 已修】

| 图 | 站点 | 格式串 | 名字寄存器 | 处置 |
|---|---|---|---|---|
| 图5（中文，本来就对） | sub6 `0x2baf8` `ZFToolManager -toolSelected:` | `'%@ (%i)        '` | `r8`（已本地化） | 不动 |
| 图6（英文，要修） | sub6 `0x3371c` | `'%@ (%i)            '` | `r8`（原始名） | 已改道 stub |
| 图6 第二处 | sub6 `0x33a34` | 同上 | `r8` | 已改道 stub |
| 图6 sub9 | sub9 `0x26d90` | 同上 | `r8` | 已改道 stub |

三处的指令形状一致：`ldr r1,[pc,r1]`（stringWithFormat:）→ `add r2,pc,r2`（格式串）
→ `mov r3, r8` → `bl objc_msgSend`。所以 stub 里 `r0 = r3` 天然可用。

---

## 4. 图5 —— 右括号被图标挡住【待 #3 实测后判断】

格式串 `'%@ (%i)        '` **末尾本来就有 8 个空格**，图标仍然压住 `)` ——
说明 cocos2d 建 label 时按可见宽度算，把尾部空格吃掉了，**"再加空格"很可能无效**。
如果 v15fix 实测后仍然挡，下一步查：
- label 的 anchor / 对齐方式，以及图标相对 label 的定位代码；
- 或者把空格挪到 `)` **前面**（`'%@ (%i )        '`，同样长度可原地改）；
- `__cstring` 里已存在 `'%@ (%i)            '`（12 个尾空格，`0x3be64f`），
  可以把 CFString 的 `data` 指针重定向过去试试。

---

## 2 / 6 / 7 / 8 —— 字号与颜色【待调查】

- **#2 图4/图7**：仓库物品详情面板。README 7.6 记过「`StorageItem` 用的是另一档设计
  （正文 18.0、标题 19.0），刻意未动」—— 现在用户要求并入 24/18。
  要定位面板是哪个类（`ZFStorageMenu`？`StorageItem`？）以及标题/说明两个 label 的
  `setFontSize:` 站点，注意两个 slice 是否对称。
- **#6 图10**：商店购买确认框。v6 修的是
  `alertWindowSimpleChoice:...withWindow:`（`0xa2190` / `0x75faa`）和
  `ZFMarketMenu -unlockItem:`（`0x6a49c` / `0x4d6f4`），这个「确认」框是**另一个工厂**
  —— 见 README 5.5「工厂重建」惯用法。
- **#7 图12**：「数值」「能力」「力量」「生命」「速度」改黑色 → **v22 已修**（见上文）。
- **#8 图12**：「陵墓」按钮字号 +3 → **v21 已修**（见上文）。

---

## 工作约定

- 定位结论写进本节，再动手；改动集中在少数几个版本里。
- 每个版本：`--dry-run` 自检 → 落盘 → 独立 verifier 全绿 → 更新 `report.json` + 本文件。
- 不碰已有 cave：sub6 `0x1b464..0x1b810` / `0x16a5f8..0x16a70c` / `0x16d594..0x16d5ac` /
  `0x16d5b0..0x16d5e0` / `0x177534..0x17753f`，sub9 `0x14f6c..0x151c0` / `0x10a1dc..0x10a29c` /
  `0x10c470..0x10c486` / `0x10c490..0x10c4c0` / `0x1138a0..0x1138c5` /
  **`0x1138c8..0x1138f3`（v22 setColor: stub）** / **`0x1138f4..0x113909`（v23 dimensions stub）**。
- 测试前先跑 `.\RestoreTestSave.ps1 -Force`（非交互模式下 `-Force` 必加）。
