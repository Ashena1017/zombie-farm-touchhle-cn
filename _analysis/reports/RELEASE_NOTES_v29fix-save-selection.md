# 僵尸农场 · Windows 存档选择显示修复

Windows 管理器的存档列表曾把选中和未选中的记录画成同一种颜色。现在选中行有整行高亮和左侧颜色标记，日间、夜间均可清楚区分；焦点移到操作按钮后仍保留高亮，全选、取消和反选会及时更新显示。

本页同时提供 Windows 更新包和现有 Android 入侵修复版。Android APK 与上一版逐字节相同（versionCode `4`），已经安装该版的玩家无需重复升级。

| 平台 | 下载附件 | 大小 | SHA-256 |
|---|---|---:|---|
| Windows 10/11 x64 | `zombie-farm-windows-x64-v29fix-save-selection.zip` | 95,948,563 B | `7A924801C7BA86F853D1D682B674B5955A5E474E44A2451C5E19244805A2A130` |
| Android 5.0+ / ARM64 | `zombie-farm-android-arm64-v29fix-invasion-fix.apk` | 97,312,084 B | `C10F0E00B4AADA2E47944F41245AB5B64C5142849926FCC538179DD405920B7F` |

## 使用与升级

- Windows：解压到新目录，运行 `游戏管理.exe`。已有进度可先通过原管理器备份，再在新目录的管理器中恢复；保留旧目录，避免覆盖自己的进度。
- Android：首次安装可使用本页 APK；更新入侵修复版时可覆盖安装，签名保持一致。内置 v29fix IPA，其他 IPA 可按需导入。
- 两端默认夜间模式，发行包不预置玩家存档；首次进入游戏后自行创建进度。

## 验证与源码

Windows 实际窗口截图与逐列像素采样确认了日间、夜间、单选、失去焦点、全选、取消和反选的显示；取证只使用 TEMP 隔离目录中的虚拟记录。管理器自检、布局及设置往返检查通过，重建的 Windows 发行包独立运行实际 `45.5 s` 通过。ZIP 内有 42 个文件，无 sandbox 存档；包内管理器与本次 Git 源码逐字节一致，SHA-256 为 `0E2C9F78ADACE3B3D2CCF6821F96D62275897BE1FABA8CBDE0C05A42F8644E74`。

管理器源码见本次 tag [`v29fix-save-selection`](https://github.com/Ashena1017/zombie-farm-touchhle-cn/tree/v29fix-save-selection)。两端 touchHLE 原生程序沿用源码 commit `2a478424b50591360f91790ee760f34b78072987` 的入侵分配器修复；Windows `touchHLE.exe` 为 `28,878,848 B`，SHA-256 `D48D903494AEC412386472637282AA8A1ACC4F0789E1A16921585EE702C1041D`。IPA 仍为 v29fix。

此前稳定闪退的单次 Windows 海盗入侵已由用户确认完成；Android 入侵、重复入侵和死亡后补队的组合尚未实测，详情见[入侵修复说明](https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/tag/v29fix-invasion-fix)。本次显示修复没有增加上述游戏场景的验证结论。

```powershell
Get-FileHash .\zombie-farm-windows-x64-v29fix-save-selection.zip -Algorithm SHA256
Get-FileHash .\zombie-farm-android-arm64-v29fix-invasion-fix.apk -Algorithm SHA256
```
