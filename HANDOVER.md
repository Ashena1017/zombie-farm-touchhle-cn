# 项目维护交接

核对日期为 2026-11-25。旧交接的 §0–§50 保存在 [历史交接](docs/HANDOVER_HISTORY.md)，其中的路径和构建命令对应迁移前的环境。玩家下载和安装见 [README.md](README.md)。

## 当前发行

[v31fix-appearance](https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/tag/v31fix-appearance) 提供 Windows x64 ZIP 和 Android ARM64 APK（`versionCode` 20）。继续使用 v31 内置 IPA。

Windows 游戏管理改用 Tauri 和 WebView2，缩短打开管理器的等待时间。WebView2 无法启动时会打开兼容界面。Windows 和 Android 都新增「外观」，可跟随系统、选浅色或深色，并选用七种预设强调色或自定义颜色。

Windows 修复损坏的额外 IPA 误用内置游戏存档的问题，并加快设置保存和批量删除备份。Android 减少导入 IPA 时的重复读取，内部版本号为 20，可直接覆盖安装旧版。

- Windows ZIP 共 98,397,748 字节，SHA-256 为 `95ED1A7EF57F0A5BB311D2D671F05656E36583148DA0E471C9651C4725C0AF2E`。WebView2 与兼容界面均通过实测，解压后游戏独立运行 45 秒。
- Android APK 共 97,379,758 字节，SHA-256 为 `AE811884151E0B819E0DDBADFF711FE19B5615E079F72662C130EE076EE2F191`。MuMu Android 15 上通过 64 项设备检查，覆盖安装前后存档哈希一致。

## v31 关于与内置 IPA 校验

[v31fix-notice](https://github.com/Ashena1017/zombie-farm-touchhle-cn/tree/v31fix-notice) 当时提供 Windows x64 ZIP 和 Android ARM64 APK（`versionCode` 19）。两端内置 `内置中文版·v31fix·开源免费.ipa`，SHA-256 为 `cfa750f4cba8d5acf0923c595ca3c257b0617c2cafed7d4ee08f4bc37d689e65`。

- 启动图在原加载时间内显示「本整合版免费 · 请勿购买」。首页头像的农场选择页在停服说明下指向「设置 → 关于」。首页「关于」在设置画面上显示原游戏创建的单按钮 `UIAlertView`。上半区使用游戏传入的标题、版本、作者和工作室署名，「中文整合与维护」单列社区整合版的免费开源声明、项目地址和 QQ 群。点框内原确认按钮回到设置的原滚动位置。进入农场后的「设置 → 帮助」仍可查看原帮助。
- 两端单独校验内置 IPA 的固定文件名与 SHA-256，允许额外安装和选择其他 IPA。缺失或被替换时提示可能为改版。Android 还检查已安装 APK 的内置资产，可从通过校验的资产恢复本地副本。原始 IPA、v30 与 v31 的补丁和恢复方法见 [IPA 记录](zombie_farm_ipa/README.md)。
- 原 IPA 使用 iPhone OS 5.1 SDK，最低系统版本为 3.0。「关于」原文和 `Ok` 取自游戏创建的提示框，深色面板、社区分栏及按钮外观由本项目绘制，尚无原机同页截图可用于外观比对。Windows（iPhone、iPad 画幅）和 MuMu Android 15 已验证框外触摸被拦截、确认后恢复原设置位置、重复开启和退出；实图见本机 `_analysis/dumps/splash-v31/about-alert-iphone-dialog.png`、`about-alert-ipad-dialog.png` 与 `android-alert-open.png`。

- Windows x64 ZIP 共 95,585,585 字节，SHA-256 为 `3CC579B37FBFE32596239FB55B3AF0E7C91BA6BB8F8FCCF443B4A2610ABE4706`。解压后独立启动 45 秒通过。
- Android ARM64 APK 共 97,370,611 字节，SHA-256 为 `B75116E5B3D4B55F7E89650820D987F530C8A2B2A12BA274162F690160144E9D`。正式签名、设备升级与存档核对通过。Android 管理器通过 50 项设备检查，共用模拟器通过 70 项 Rust 库测试。

## 上一版记录

[v30fix-notice 源码](https://github.com/Ashena1017/zombie-farm-touchhle-cn/tree/v30fix-notice) 对应 Android `versionCode` 18。这一版裁小三张位图字体，去掉仓库出售详情的重复正文绘制，并在查询 IPA 文件属性时直接读取目录。[IPA 补丁记录](zombie_farm_ipa/README.md)

- Windows ZIP 的 SHA-256 为 `3B3DDBB73ACE535133768D37C50130E081565932421280801B117CBE43462178`。
- Android APK 的 SHA-256 为 `FC68ED878A77D135977A67787141CEBED91E77D07741CF4D76863A2C609DEDD2`。

- Windows Release 的 `Image::from_bytes` 对三张字体的 PNG 字节执行 RGBA 解码和像素预乘。同进程交替测量，预热 4 轮，每版取 40 组三张合计耗时的中位数，v29 为 51.294 ms，v30 为 3.782 ms。计时不包含磁盘、ZIP 解压、纹理上传或游戏绘制。三张图的 366 个字形均逐像素相同。
- Windows ZIP 已通过解压独立启动和管理器自检。69 项 Rust 库测试和使用 v30 IPA 的列表回归通过。MuMu Android 15 从 v17 覆盖安装 v18 后，首次启动前的存档 SHA-256 一致，39 项设备检查全部通过。
- 两端均实测打开仓库「瞬间成熟」详情，显示完整三行正文和两个按钮。点「卖出」进入 10 金币确认框，取消后库存仍为 ×2。

## v29 记录

[v29fix-maintenance 源码](https://github.com/Ashena1017/zombie-farm-touchhle-cn/tree/v29fix-maintenance) 包含管理器设置保存、备份恢复、启动校验和高倍率合成修复。Android `versionCode` 为 17。两端共用带标题水印的 v29fix-notice IPA。

- Windows ZIP 的 SHA-256 为 `7B5DCD5972A378B36B5A4930EAF9CBD94CC7F90ED09CAEDB431601C43CD795F4`。新 EXE 的指纹已同步到管理器。解压包通过独立启动，两个不同 app ID 的设置切换和无效倍率输入通过 WinForms 实测。
- Android APK 的 SHA-256 为 `519D40BC0BAA57AA1D3A77A8589406083EB51E1EBA91EDCA2AB848D6E4095979`。MuMu Android 15 从 v16 覆盖升级后，首次运行前的存档 SHA-256 与升级前一致。已实测进入农场、返回管理器和跨日快进预览。39 项设备回归通过。API 21 的排序兼容性通过 DEX 检查，待旧系统真机复测。
- 共用模拟器通过 68 项库测试和使用实际 IPA 的列表回归。Windows iPad ×6、限 60 帧、同一测试档的画面提交次数，标题阶段每秒约 9.8 提至 16.6，进入农场后约 8.5 提至 12.9。性能日志、设备截图与测试输出在 `_analysis/dumps/maintenance-v17/`。

## 前序修复

- 两端包含最高 ×6、15 脑子购买九种农场主、变异与入侵队列滑动修复，以及僵尸相机拍照后的免费开源声明。
- 本版修复冷启动主菜单「设置」、游戏内帮助闪退和农场主头像页卡住。帮助页先显示声明、项目地址和 QQ 群 `1185712984`，往下可读原帮助。头像页可选择本地农场并返回，原「其他农场」联网服务已停运。
- Android 新安装默认 iPhone ×3（1440×960）。商店异常黑框曾由受影响玩家实测确认修复，未解锁物品的黑色剪影是原游戏表现。
- 离线版暂无游戏内农场改名入口。Windows 可在启动管理器的环境中设置 `TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME` 覆盖显示名。存档仍保存原名称。

上一版 `v29fix-help-profile` 的场景实测在本机 `_analysis/dumps/help-profile-20261121/`。公开归档见[历史交接 §50](docs/HANDOVER_HISTORY.md#50-交接后追加2026-11-21帮助与农场主界面修复发布)。

## 源码入口

| 涉及范围 | 文件或目录 |
|---|---|
| Windows 管理器 | [GameManager.ps1](windows/GameManager.ps1)。根目录的 [Play-Windows.bat](Play-Windows.bat) 启动管理器，无控制台宿主的源码与重建脚本在 [windows/launcher/](windows/launcher)。 |
| Android 管理器 | [org.touchhle.android](touchHLE/touchHLE-fork/android/app/src/main/java/org/touchhle/android)，从 `ManagerActivity.java`、`ZfStorage.java`、`ZfIpa.java`、`ZfSave.java` 查起。打包配置在 [app/build.gradle.kts](touchHLE/touchHLE-fork/android/app/build.gradle.kts)。 |
| 共用模拟器与游戏适配 | [touchHLE-fork/src/](touchHLE/touchHLE-fork/src)。ZFR 的 Objective-C 消息处理从 [zombie_farm.rs](touchHLE/touchHLE-fork/src/objc/messages/zombie_farm.rs) 进入，相机、购买、菜单分别在 [zombie_farm/](touchHLE/touchHLE-fork/src/objc/messages/zombie_farm)。 |
| IPA 补丁与水印 | [IPA 工具](tools/README.md)、[IPA 文件和补丁记录](zombie_farm_ipa/README.md) 与 [_build_notice_ipa.py](tools/_build_notice_ipa.py)。 |
| 构建和发行校验 | [scripts/](scripts/README.md)。 |
| 专项验证和取证 | [_analysis/README.md](_analysis/README.md)、[专项报告](_analysis/reports)、[技术参考](TECHNICAL.md)、[变更记录](process.md)。 |

正式游戏 bundle ID 是 `com.playforge.ZombieFarm.ZFR`。Windows 测试存档在 `run/windows/touchHLE/touchHLE_sandbox/com.playforge.ZombieFarm.ZFR/Documents/saveGame.bin2`，偏好文件在 `run/windows/`。管理器读取 `zombie_farm_ipa/`，模拟器通过 `run/windows/zombie_farm_ipa` 下的 NTFS 目录联接读取同一批文件。更换 IPA 的 bundle ID 会同时切换设置和存档目录。

本机已有运行环境。新检出或移动项目目录后，用一份与当前校验值对应的 Windows ZIP 初始化，再双击 `Play-Windows.bat`。初始化会修正项目迁移后指向旧位置的 IPA 联接。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Initialize-Runtime.ps1 -ZipPath "C:\path\to\downloaded-release.zip"
```

## 构建与核验

以下命令从仓库根目录运行。当前 fork 基于上游 `fa3d09511d471f505e41abed7c535e4dfbd7c59c`。新检出先用 Python 3.12 或更新版和 Git 运行 `python scripts/restore_vendor.py`，脚本按提交或 SHA-256 恢复六组原生依赖。已有 Boost 源码归档时可传 `--boost-archive <tar.gz>`。目标目录需为空，可用 `--vendor <目录>` 异地验证。本机已安装依赖的工作区可直接构建。[依赖来源与校验值](scripts/restore_vendor.py)

2026-11-25 在独立检出中恢复完整原生依赖后，Windows x64 成功编译，便携包解压后进入游戏窗口，CPU 仿真运行 45 秒。Android ARM64 测试 APK 完成 43 项 Gradle 任务，通过包内 IPA、ABI、NDK 运行库、默认设置、应用 ID、版本和签名检查。新编译的 SDL 库使用 NDK 27 的非阻塞传感器轮询接口 `ALooper_pollOnce`。

### Windows x64

1. 修改含中文的 PowerShell 脚本后，用 `scripts/_ensure_bom.ps1` 检查编码和语法，再执行管理器自检。
2. 修改 Rust 后关闭本地游戏，运行增量构建。脚本识别已配置的 x64 开发者终端，或用 `vswhere` 查找带 C++ 工具链的 Visual Studio。也可用 `-VsDevCmd` 指定入口。成功构建的 EXE 安装到 `run/windows/touchHLE/touchHLE.exe`。确定用于 Windows 打包的 EXE 后，用其 SHA-256 更新 `windows/GameManager.ps1` 的 `$script:PinnedExeSha256`。
3. 打包脚本使用 `windows/touchHLE_options.txt`、空 sandbox 和共用 IPA 生成便携 ZIP。它在临时目录核验 `SHA256SUMS.txt` 并启动解压后的游戏，验证通过后把 ZIP 写入 `dist/windows/`。说明书模板在打包脚本里。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_ensure_bom.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File windows\GameManager.ps1 -SelfTest
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_build_fork_now.ps1
Get-FileHash -Algorithm SHA256 -LiteralPath run\windows\touchHLE\touchHLE.exe
# 校验值同步后再打包。仅改管理器可直接打包。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_build_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_verify_layout.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_verify_layout_match.ps1
```

在其他 Windows 开发机上，可从已配置 MSVC 的 x64 开发者终端进入 `touchHLE/touchHLE-fork/`，运行 `cargo build --release --locked --bin touchHLE`。将默认目标目录下的 `target/release/touchHLE.exe` 安装到本机运行目录，再更新校验值。

### Android ARM64

使用 JDK 17、Gradle 8.11.1、Android SDK Platform 31、NDK 27.2.12479018 和 Rust Android ARM64 工具链。本机用 `_build_android_local.ps1`，可通过 `-AndroidSdk`、`-Jdk` 和 `-Gradle` 指定工具路径。其他环境配置好工具链后可直接调用 `_build_android.ps1`。Gradle 和 Windows 打包脚本共用 `release.json` 指定的内置 IPA。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_build_android_local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_verify_android_package.ps1
```

产物在 `dist/android/touchHLE-zombiefarm-android-arm64-fixed.apk`。正式更新需提高 `versionCode` 并使用原发布证书签名。Gradle 读取 `ANDROID_KEYSTORE_PATH`、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS` 和 `ANDROID_KEY_PASSWORD`，缺少签名配置时使用本机 debug 密钥。打包脚本通过 Android SDK 的 `apksigner` 和 `aapt` 核对候选包的实际证书、应用 ID、启动入口、版本号与 ABI，再替换发行文件。使用其他测试证书时传 `-TestBuild`，APK 单独写入 `dist/android/test/`。设备验证从官方包覆盖安装、启动与读档开始。

### 准备发行

1. 按改动选场景实测。菜单相关覆盖冷启动设置、帮助滚动与返回、头像页选择与返回。渲染相关记录 Android 设备、系统版本和 GPU，区分 MuMu 与真机结果。涉及共用适配时记录两端各自的验证范围。
2. Windows ZIP 使用单一顶层目录，记录两端最终附件的大小和 SHA-256。更新[发行清单](release.json)中的 IPA 文件名、大小、哈希、版本和累计补丁参数，然后核对两端的包内内容、签名和标题水印。清单随新的 Windows 便携包分发。
3. 使用个人 `git-hosting` 技能核对提交范围，并把 tag 指向与附件对应的源码提交。上传后回读校验两个资产，公开后核对 `releases/latest` 和 README 下载链接。发布证据的目录结构可参照 `_analysis/dumps/release-help-profile-20261121/`。

## 后续维护

- 保留两端最近一次实测的版本、设备与场景。Android 的界面或渲染修复尽量在报告问题的真机复测，尤其是昼夜 FBO、商店空文字纹理和列表裁剪。
- 维护当前发行信息时更新本页和 README 下载区。历史根因与长日志按对应问题补进 `_analysis/reports/`，旧交接的编号继续用于查档。
