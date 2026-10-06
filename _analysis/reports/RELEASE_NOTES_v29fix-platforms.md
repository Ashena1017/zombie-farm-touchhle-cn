# Zombie Farm 中文版 · Windows / Android（v29fix-platforms）

原版《僵尸农场》中文版现提供 Windows x64 与 Android ARM64 两种独立下载。两个版本使用同一份已修复的 v29fix 游戏 IPA；根据设备选择对应附件。

| 平台 | 附件 | 大小 | SHA-256 |
|---|---|---:|---|
| Windows 10/11 x64 | `zombie-farm-windows-x64-v29fix.zip` | 95,057,453 B | `84DE88543BF3D302657E6681F72E28D77F7E3EA5063995A1ECDBCB30B72F4461` |
| Android 5.0+ / ARM64 | `zombie-farm-android-arm64-v29fix.apk` | 97,302,304 B | `99F896A3E157E4BAD8C099FF8DE825EC9A97AC09E9F3EDB374D53968B932ABB8` |

## Windows

解压 ZIP 后运行 `游戏管理.exe`。管理器支持 IPA 版本切换、iPhone/iPad 设备与窗口倍率、帧率、鼠标滚轮缩放、启动时跳过游戏时间、金币/脑子修改和存档管理。新建备份会同时保存累计跳过时间；没有时间元数据的旧备份仍可恢复并保留当前累计时间。

## Android

安装 APK 后打开 **Zombie Farm 游戏管理**。APK 内置最新 v29fix IPA，首次启动时会校验并安装到应用数据目录；无需手动复制游戏文件。其他 IPA 可用系统文件选择器导入。管理器提供启动/跳过时间、iPhone/iPad、渲染倍率、帧率、帧率修复、金币/脑子及存档备份、恢复、导入、导出和删除。

首页状态标记已调整到标题下方，长应用名称不会再与状态标记重叠。

两个版本首次启动管理器时都默认使用夜间模式。Android 默认横屏、iPhone 原生画面、60 FPS；触屏缩放使用游戏原生两指捏合，不采用 Windows 滚轮选项。此 APK 为 arm64-v8a，最低 Android API 21。

Windows sandbox 不预置人物存档；玩家首次进入游戏后会生成自己的存档。APK 仅内置 IPA，不包含任何 sandbox 存档。

## 验证

- Windows 交付包：42 个文件；sandbox 为空且不含任何人物存档；独立启动验证通过。
- Android APK：内置 IPA 的大小为 59,564,493 B，SHA-256 为 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`；包结构、默认参数和 arm64 native libraries 静态校验通过。
- Android 管理器 instrumentation 30 项通过；MuMu Android API 35 上验证管理器启动、启动游戏进入中文开始菜单及存档备份/恢复。该验证不等于已在所有 Android 手机型号上实测。

PowerShell 校验：

```powershell
Get-FileHash .\zombie-farm-windows-x64-v29fix.zip -Algorithm SHA256
Get-FileHash .\zombie-farm-android-arm64-v29fix.apk -Algorithm SHA256
```
