# touchHLE Zombie Farm

[English](README.en.md) | 中文

这个分支用于运行 Playforge 的 Zombie Farm / ZFR。它包含了一些面向 Zombie Farm 的兼容性修复和调试辅助，不保证这些改动适合其他游戏。

## 准备

你需要准备：

- 打包好的 touchHLE 可执行文件。
- 你自己的 Zombie Farm / ZFR IPA 文件。
- `touchHLE_fonts/` 目录中的字体资源。

建议把 touchHLE 放在非中文、路径较短的目录，例如：

```text
D:\Games\touchHLE
C:\touchHLE
```

也建议把 IPA 放在一个固定目录，例如：

```text
.\zombie_farm\ZFR.ipa
```

## Windows 构建

Windows 下需要：

- Rust toolchain
- CMake
- Visual Studio 2022 Build Tools，安装 C++ 构建工具

仓库提供了 Windows 构建脚本：

```bat
.\build_windows.bat release
```

如果只给当前电脑自用，可以开启本机 CPU 极限优化构建：

```bat
.\build_windows.bat release native
```

这个模式会启用 `target-cpu=native`、`opt-level=3`、`codegen-units=1` 和 `lto=fat`，生成的程序可能不适合拿到其他电脑运行。去掉 `native` 参数即可关闭。

如果要给指定 CPU 的电脑分发，可以显式指定 Rust/LLVM 的 CPU 名称：

```bat
.\build_windows.bat release --cpu=raptorlake
.\build_windows.bat release --cpu=znver4
```

例如 Intel Core i9-14900K 可以用 `--cpu=raptorlake`。AMD 机器需要按对方实际架构选择，比如 Ryzen 5000 通常是 `znver3`，Ryzen 7000/9000 通常是 `znver4`/`znver5`。如果不确定对方 CPU 支持什么，优先用兼容性更好的 `--cpu=x86-64-v3`。

查询本机 CPU 型号：

```powershell
Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name
```

查询当前 Rust 工具链支持的 CPU 名称：

```powershell
rustc -C target-cpu=help --target x86_64-pc-windows-msvc
```

调试构建可以运行：

```bat
.\build_windows.bat debug
```

## Windows 启动

在 touchHLE 解压目录打开 Command Prompt 或 PowerShell，然后运行：

```bat
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

如果 IPA 放在其他目录，替换成你的实际路径：

```bat
.\touchHLE.exe "D:\Games\ZombieFarm\ZFR.ipa" --device-family="ipad"
```

部分版本也可以用默认设备模式启动：

```bat
.\touchHLE.exe ".\zombie_farm\Zombie_Farm_1.181.ipa"
```

## 玩家名字

可以用环境变量覆盖 Zombie Farm 当前本地玩家的显示名，不会修改存档，也不会覆盖好友的名字：

```powershell
$env:TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME="你的名字"
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

清除名字覆盖：

```powershell
Remove-Item Env:\TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME
```

## 实验性公开好友农场

该功能默认关闭。只有在设置 `TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL` 后，Zombie Farm 1.0 才会启用公开好友接口，把当前用户名和 `saveGame.bin2` 存档快照上传到指定服务端，并允许查看服务端上的所有公开农场。

此实验接口不使用密码、Cookie、令牌或其他鉴权信息。服务端完全没有鉴权：任何客户端都可以填写任意合法的公开玩家 ID 和用户名、查看所有已上传的农场，并且可以用相同公开玩家 ID 覆盖已有记录。因此不要使用需要保护的用户名，也不要在请求或环境变量中放入任何密码、秘密信息或私人存档。

```powershell
$env:TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL="https://zombiefarm.aeutlook.com"
$env:TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME="你的名字"
$env:TOUCHHLE_ZOMBIE_FARM_PLAYER_ID="your_public_player_01"
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

只需要设置 `TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL` 就会启用在线功能；名字和公开玩家 ID 可以按需设置。`TOUCHHLE_ZOMBIE_FARM_PLAYER_ID` 是公开标识，不是密码；允许 1 到 80 个 ASCII 字母、数字、`-` 或 `_`。如果不设置，touchHLE 会为当前安装生成并持久化一个公开 ID。基础地址支持 `http://` 和使用正常受信任证书的 `https://`；网络请求带有超时兜底，服务不可用时会返回失败而不是无限等待。该功能只对包标识为 `com.playforge.ZFR.LZ54D2GT3D`、版本为 `1.0` 的 Zombie Farm 启用。

关闭在线功能：

```powershell
Remove-Item Env:\TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL
```

## 时间偏移

如果需要让模拟器内时间向未来或过去偏移，可以在 PowerShell 中先设置环境变量。

下面的示例会让模拟器内时间向未来偏移 900 秒，也就是 15 分钟：

```powershell
$env:TOUCHHLE_TIME_OFFSET_SECONDS="900"
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

这个设置只对当前 PowerShell 窗口有效。关闭窗口后会失效。

取消时间偏移：

```powershell
Remove-Item Env:\TOUCHHLE_TIME_OFFSET_SECONDS
```

## Zombie Farm 入侵冷却

如果希望 Zombie Farm 1.0 的机器人入侵冷却始终就绪，可以在启动前设置：

```powershell
$env:TOUCHHLE_ZOMBIE_FARM_NO_INVASION_COOLDOWN="1"
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```

该开关只覆盖界面和入侵资格检查所读取的 `lastInvasionDate` 时间差，不会修改存档中的日期，也不会绕过僵尸数量等其他入侵条件。它只对包标识为 `com.playforge.ZFR.LZ54D2GT3D`、版本为 `1.0` 的 Zombie Farm 生效。环境变量也接受 `true`、`yes` 或 `on`，不区分大小写。

关闭该功能：

```powershell
Remove-Item Env:\TOUCHHLE_ZOMBIE_FARM_NO_INVASION_COOLDOWN
```

## Windows 快捷键

这些快捷键主要用于 Zombie Farm 调试和排查：

- `F9`：仅对 Zombie Farm 生效。按游戏逻辑快速完成当前任务队列中的任务并领取奖励。每次启动后只需要按一次。
- `F10`：开关可视化界面元素检查器。打开后可以用鼠标查看当前 UIKit 元素，再按一次 `F10` 或按 `Esc` 关闭。
- `F11`：把当前界面检查信息输出到日志，适合排查界面层级、表格、控件状态。
- `F12`：请求进入调试器。只有在 touchHLE 已连接调试器时才会真正进入，否则会被忽略。

## Android 版本不受支持

Android 版本目前不受支持，只能作为实验性版本尝试。已知限制：

- 无法使用 `TOUCHHLE_TIME_OFFSET_SECONDS` 时间偏移环境变量。
- 无法保存任务进度。
- 无法使用 `F9` 一键完成任务。

如果仍然需要尝试 Android 版本，可以按下面的方式放置 IPA：

1. 安装 Android APK。
2. 把 IPA 放到应用数据目录下的 `touchHLE_apps` 文件夹。

默认包名的路径通常是：

```text
/sdcard/Android/data/org.touchhle.android/files/touchHLE_apps
```

如果你安装的是带 branding 后缀的 APK，目录中的包名可能不同，请按设备上的实际包名调整。

3. 打开 touchHLE。
4. 在应用里选择 IPA 文件启动游戏。

## 常见问题

### 找不到可执行文件

请确认你已经解压完整的 Windows 版压缩包。`touchHLE.exe` 应该和 README 位于同一个目录。

### IPA 路径包含空格

路径中有空格时，请用英文双引号包住路径：

```bat
.\touchHLE.exe "D:\Games\ZombieFarm\ZFR 1.0.ipa" --device-family="ipad"
```

### iPad 画面或资源不正确

ZFR 通常建议带上 iPad 设备参数：

```bat
--device-family="ipad"
```

完整示例：

```bat
.\touchHLE.exe ".\zombie_farm\ZFR.ipa" --device-family="ipad"
```
