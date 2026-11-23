# Windows 早期启动与打包脚本

`start_zf.ps1` 和 `package_zombiefarm_windows_x64.ps1` 原位于 `touchHLE/touchHLE-fork/`，现以文本保存。它们按早期目录布局查找 `target/release/touchHLE.exe` 和 `zombie_farm/ZFR06.ipa`。打包脚本默认使用 `Z:\`，会清除该目录下的同名旧导出。

当前运行、构建与发行步骤见[维护交接](../../../HANDOVER.md)。
