# 项目维护交接

核对日期为 2026-11-23。旧交接的 §0–§50 保存在 [历史交接](docs/HANDOVER_HISTORY.md)，其中的路径和构建命令对应迁移前的环境。玩家下载和安装见 [README.md](README.md)。

## 当前发行

[v29fix-maintenance](https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/tag/v29fix-maintenance) 包含管理器设置保存、备份恢复、启动校验和高倍率合成修复。Android `versionCode` 为 17，沿用正式签名。两端共用带标题水印的 v29fix-notice IPA。两份附件的完整 SHA-256 及下载地址见 [Release 页面](https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/latest)。

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

以下命令从仓库根目录运行。当前 fork 基于上游 `fa3d09511d471f505e41abed7c535e4dfbd7c59c`。新环境需准备 Rust、CMake、平台工具链，以及 fork 的 `vendor/` 依赖。现有 Windows 增量脚本使用本机的 Visual Studio 2022 Community 和 `touchHLE/_build_tools/`。上游依赖布局见 [fork 的 .gitmodules](touchHLE/touchHLE-fork/.gitmodules)，本机补齐部分依赖的旧脚本见 [_restore_vendor.ps1](_analysis/_restore_vendor.ps1)。

### Windows x64

1. 修改含中文的 PowerShell 脚本后，用 `scripts/_ensure_bom.ps1` 检查编码和语法，再执行管理器自检。
2. 修改 Rust 后关闭本地游戏，运行增量构建。脚本将成功构建的 EXE 安装到 `run/windows/touchHLE/touchHLE.exe`。用其 SHA-256 更新 `windows/GameManager.ps1` 的 `$script:PinnedExeSha256`。
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

使用 JDK 17、Gradle 8.11.1、Android SDK Platform 31、NDK 27.2.12479018 和 Rust Android ARM64 工具链。本机用 `_build_android_local.ps1`，其他环境配置好工具链后可直接调用 `_build_android.ps1`。Gradle 读取 Windows 打包使用的同一份 `zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa`。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_build_android_local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_verify_android_package.ps1
```

产物在 `dist/android/touchHLE-zombiefarm-android-arm64-fixed.apk`。正式更新需提高 `versionCode` 并使用原发布证书签名。Gradle 读取 `ANDROID_KEYSTORE_PATH`、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS` 和 `ANDROID_KEY_PASSWORD`，缺少签名配置时使用本机 debug 密钥。打包脚本通过 Android SDK 的 `apksigner` 和 `aapt` 核对候选包的实际证书、应用 ID、启动入口、版本号与 ABI，再替换发行文件。使用其他测试证书时传 `-TestBuild`，APK 单独写入 `dist/android/test/`。设备验证从官方包覆盖安装、启动与读档开始。

### 准备发行

1. 按改动选场景实测。菜单相关覆盖冷启动设置、帮助滚动与返回、头像页选择与返回。渲染相关记录 Android 设备、系统版本和 GPU，区分 MuMu 与真机结果。涉及共用适配时记录两端各自的验证范围。
2. Windows ZIP 使用单一顶层目录，记录两端最终附件的大小和 SHA-256。更换 IPA 时同时核对 Windows 管理器的 `$script:PinnedIpaSha256`、两端的包内内容和标题水印。
3. 使用个人 `git-hosting` 技能核对提交范围，并把 tag 指向与附件对应的源码提交。上传后回读校验两个资产，公开后核对 `releases/latest` 和 README 下载链接。发布证据的目录结构可参照 `_analysis/dumps/release-help-profile-20261121/`。

## 后续维护

- 优先把本机 Windows 构建脚本中的 Visual Studio 路径、Android 快捷脚本中的工具链目录参数化，再在干净检出中验证依赖准备流程。
- 保留两端最近一次实测的版本、设备与场景。Android 的界面或渲染修复尽量在报告问题的真机复测，尤其是昼夜 FBO、商店空文字纹理和列表裁剪。
- 维护当前发行信息时更新本页和 README 下载区。历史根因与长日志按对应问题补进 `_analysis/reports/`，旧交接的编号继续用于查档。
