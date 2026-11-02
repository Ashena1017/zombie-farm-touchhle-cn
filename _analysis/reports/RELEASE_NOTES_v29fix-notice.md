# 僵尸农场 · 启动画面水印与窗口标题

上一版把「免费、开源、官方地址」放进了管理器，但玩家得先打开管理器才看得到——**转卖者拿走的往往是游戏本身**。这一版把声明再往前推一步：**印在游戏标题画面上，每次启动都在**。

## 这一版加了什么

**游戏画面（Windows 与 Android 共用同一份 IPA）**

- 标题界面右上角、logo 右侧那片空天里，加了「本作免费开源 · 请勿购买」和 `github.com/Ashena1017/zombie-farm-touchhle-cn`。
- 改动只在 `Payload/ZFR.app/MainMenuBG.png` 这一张背景图层上，不遮挡 logo、按钮与任何交互区域。
- IPA 内 1086 个成员里**只有这 1 个变了**，其余 1085 个逐字节相同；`Payload/ZFR.app/ZFR` 可执行文件哈希不变（`45D647787CC6256DBE83B041808E5845739A7B331B72DC030C7FD6E9CC04B05B`）。游戏内容、存档格式、存档位置均未改动。

**touchHLE 窗口标题**

- 由 `ZFR (touchHLE …)` 改为 `ZFR · 免费开源 · Ashena1017/zombie-farm-touchhle-cn (touchHLE …)`。
- 改在模拟器源码里（`src/environment.rs`），不是管理器事后改标题——所以不管从管理器启动还是直接跑 `touchHLE.exe`，标题都带出处。截图、录屏、直播默认都会带上它。

**Android**

- `versionCode` 由 `5` 升到 `6`，签名证书与上一版完全相同（`C2:DD:CA:91:…:CA:6F`），可直接覆盖安装，存档不受影响。
- APK 内打包的 IPA 同步更新，`assets/touchHLE_zombiefarm_ipa.sha256` 与实际内容一致。

## 这东西能起什么作用（以及不能）

能做的：让**用我们的包转卖**这件事变得不划算——买家一启动就看见「请勿购买」和官方地址，自然会去退款、去举报；卖家就算自己截图，窗口标题里也带着项目地址。

不能做的：拦不住有人用旧版本（v28 或网上其他包）转卖，也拦不住买家在付款前根本没机会看到启动画面。**它是提高转卖成本的手段，不是防盗版**。真正的解法仍然是让「官方免费」这件事被更多人知道。

## 下载

| 平台 | 下载附件 | 大小 | SHA-256 |
|---|---|---:|---|
| Windows 10/11 x64 | `zombie-farm-windows-x64-v29fix-notice.zip` | 95,976,692 B | `4A9168B5CA8817A8B5BE973CC37440344514824520FAA69C4A7883BD884B1195` |
| Android 5.0+ / ARM64 | `zombie-farm-android-arm64-v29fix-notice.apk` | 97,333,093 B | `7138BD24597C8BF46F4779161A7FF12BB8AB8412C462DC71AAEE69EF2F0E5D7C` |

## 使用与升级

- Windows：解压到新目录，运行 `游戏管理.exe`。已有进度请先用旧管理器备份，再在新目录里恢复。
- Android：直接覆盖安装即可（签名一致，`versionCode 5 → 6`）。
- 两端默认夜间模式；发行包不预置任何玩家存档。

## 验证

- **改动前先取证**：IPA 内 839 张图全部是普通 PNG，没有 PVR/PVRTC 压缩纹理；标题界面不是图集，而是 `MainMenuBG.png`（1024×683 天空+远山）、`MainMenuBGFront.png`（泥土层）、`MainMenuPlayBG.png` 等独立图层。因此只改背景层即可，不涉及解码/重压纹理。
- **屏幕映射**：`--device-family=ipad` + `--scale-hack=1.5`，1024×768 逻辑屏渲染到 1536×1152 客户区，贴图与屏幕 1:1 映射，水印位置可精确计算到像素。
- **真机渲染确认**：用发行版 IPA 只替换那一张图试跑，抓取标题界面截图，确认水印正常显示、不压 logo/按钮，存档正常读回（等级、金币均在）。最终版水印即由该次确认的位置与字号生成。
- **打包内容**：ZIP 为 43 个文件、单一同名顶层目录，无运行日志、无 sandbox 文件；`请勿购买.txt` 在根目录。
- **成品自测**：把 ZIP 解压到临时目录后独立运行 `45.0 s` 通过——窗口正常出现、`iPad device family is chosen`、`CPU emulation begins`、无 panic，sandbox 保持干净。
- **Android 包校验**：`_verify_android_package.ps1` PASS——包内 IPA 的 SHA-256 与仓库文件一致、哈希戳一致、`libc++_shared.so` 与 NDK 27.2.12479018 一致、默认选项仍为 iPhone 原生分辨率 + 捏合缩放；`versionCode=6`，`keytool` 读到的证书 SHA-256 与上一版相同；`lib/arm64-v8a/libtouchHLE.so` 中可检出新的窗口标题字符串。

**验证边界**：本轮**没有**在 Android 设备上重装实测（MuMu 实例当时未运行），Android 侧只做到包级校验；窗口标题与启动水印的实际显示，Android 端沿用上一版已验证的渲染路径，但未截图确认。签名不匹配的警告框仍未用真实重签名包触发过。游戏侧结论与上一版相同：重复入侵、死亡后补队、Android 入侵场景仍未实测。

```powershell
Get-FileHash .\zombie-farm-windows-x64-v29fix-notice.zip -Algorithm SHA256
Get-FileHash .\zombie-farm-android-arm64-v29fix-notice.apk -Algorithm SHA256
```
