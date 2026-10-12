# 僵尸农场 · Windows / Android 入侵闪退修复

Windows x64 与 Android ARM64 已同步修复 touchHLE 的内存分配器错误：小堆请求对齐后，旧释放逻辑可能错误回收其所在页面，导致后续战斗纹理覆盖仍在使用的游戏对象，引发入侵闪退。本次按分配来源释放内存，并为游戏的 Cocos scheduler/action manager 添加共用可重入同步保护。

游戏 IPA 仍为 v29fix，玩法、本地化和存档格式不变。现有存档可继续使用；升级前可在管理器中创建备份。

| 平台 | 下载附件 | 大小 | SHA-256 |
|---|---|---:|---|
| Windows 10/11 x64 | `zombie-farm-windows-x64-v29fix-invasion-fix.zip` | 95,948,193 B | `8935F65C5A754D5BADB92541AE09551EB3ADB8E98A8F9479A15B7CE02F2D9C67` |
| Android 5.0+ / ARM64 | `zombie-farm-android-arm64-v29fix-invasion-fix.apk` | 97,312,084 B | `C10F0E00B4AADA2E47944F41245AB5B64C5142849926FCC538179DD405920B7F` |

## 使用与升级

- Windows：将 ZIP 解压到新目录，运行 `游戏管理.exe`。已有进度可通过原管理器备份后恢复；保留旧目录，避免直接覆盖自己的存档。
- Android：覆盖安装 APK，应用名称仍为 **Zombie Farm 游戏管理**，安装版本号递增为 `4`，签名保持一致。内置最新 v29fix IPA，其他 IPA 可按需导入，无需手动操作 data 文件。
- Windows 保留桌面窗口倍率和滚轮缩放；Android 默认 iPhone 原生画面、横屏、60 FPS，并使用两指捏合缩放。两端默认夜间模式。
- 两份发行包均不预置玩家存档，首次进入游戏后自行创建进度。

## 本次验证

- 生产库 65 项测试通过，包括真实内存分配器的危险边界、相邻存活数据、外部页面回收与复用、清零及重复释放回归。
- Windows：此前稳定闪退的隔离存档完成单次海盗入侵，用户确认未闪退；诊断未发现原来的位图与对象重叠，战后保存，正常退出码 `0`。发行包独立启动实际运行 `45.5 s` 正常，42 个文件，sandbox 为空。
- Android：ARM64 release 原生库和 APK 重新构建成功；包结构、默认参数、签名和安装元数据校验通过。APK 内置 IPA 为 `59,564,493 B`，SHA-256 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`，不含 sandbox 存档。
- 本次未实测 Android 入侵，也未单独验证重复入侵及死亡后补队的组合；旧版本 Android 管理器实测不作为本次游戏验证。

构建源码 commit：`2a478424b50591360f91790ee760f34b78072987`。Windows 包内 `touchHLE.exe` 为 `28,878,848 B`，SHA-256 `D48D903494AEC412386472637282AA8A1ACC4F0789E1A16921585EE702C1041D`。

```powershell
Get-FileHash .\zombie-farm-windows-x64-v29fix-invasion-fix.zip -Algorithm SHA256
Get-FileHash .\zombie-farm-android-arm64-v29fix-invasion-fix.apk -Algorithm SHA256
```
