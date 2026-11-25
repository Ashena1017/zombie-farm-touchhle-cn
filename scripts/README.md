# 构建与校验脚本

从项目根目录运行。完整的依赖和发版步骤见[维护交接](../HANDOVER.md#构建与核验)。

| 任务 | 脚本 |
|---|---|
| 新检出恢复原生依赖 | [restore_vendor.py](restore_vendor.py)，用 Python 3.12+ 和 Git 恢复锁定的源码及许可证。可用 `--vendor` 指定空目录，`--boost-archive` 复用现有压缩包。 |
| Windows 增量编译 | [`_build_fork_now.ps1`](_build_fork_now.ps1)，安装到 `run/windows/touchHLE/` |
| Windows 管理器 | [build.ps1](../windows/launcher/build.ps1)，用 Cargo 构建内嵌页面的 Tauri EXE，安装到 `windows/游戏管理.exe` |
| Windows 打包 | [`_build_release.ps1`](_build_release.ps1)，构建管理器及 `dist/windows/zombie-farm-windows-x64.zip`；测试包可用 `-OutputDir` 指定独立目录 |
| Android 构建 | [`_build_android_local.ps1`](_build_android_local.ps1) 使用本机工具链，[通用入口](_build_android.ps1) 接受另外配置的工具链 |
| Windows 包校验 | [`_verify_release.ps1`](_verify_release.ps1) 解压并试运行，附 `-LayoutOnly` 时只查布局和哈希 |
| Android 包校验 | [`_verify_android_package.ps1`](_verify_android_package.ps1) 检查应用 ID、管理器入口、版本号、签名证书、IPA、ARM64 库和默认设置。核验历史版本可传 `-ExpectedVersionCode`。 |
| 本机目录校验 | [`_verify_layout.ps1`](_verify_layout.ps1) 核对 Windows 运行目录和 IPA 联接 |
| PowerShell 脚本检查 | [`_ensure_bom.ps1`](_ensure_bom.ps1)，附 `-CheckOnly` 时只读 |

Windows 初始化脚本在 [windows/Initialize-Runtime.ps1](../windows/Initialize-Runtime.ps1)。IPA 工具和专题诊断分别见 [tools](../tools/README.md) 和 [_analysis](../_analysis/README.md)。

Android 正式构建在候选包通过原发布证书校验后替换 `dist/android/` 中的 APK。使用自己的测试证书时，给构建入口传 `-TestBuild`，输出在 `dist/android/test/`。
