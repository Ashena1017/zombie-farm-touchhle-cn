# 僵尸农场 · Windows「游戏已经在运行」误报修复

Windows 管理器曾把「有没有一个叫 touchHLE 的进程」当成「游戏在不在跑」。闪退之后，模拟器可能留下一个没有窗口、也看不到界面的残留进程，于是管理器一直提示「游戏已经在运行了」，而任务管理器里又找不到可以关掉的东西；从另一份安装启动的游戏、以及被系统复用的旧 PID，也会造成同样的误判。

现在管理器在启动时记录真正的进程（PID、启动时间、可执行文件路径），每次判断都核对这三项，任何一项对不上就立即清掉记录。崩溃之后不会再被卡住，备份、还原和货币修改都不会再因为一条过期状态被拒。另外：

- 崩溃时不再弹出可能藏在窗口后面的错误对话框，改为在状态栏直接说明退出原因（例如 `0xC0000005 访问冲突`）和崩溃信息首行。
- 游戏窗口消失但进程还在时，管理器会自己回到前台，并询问是否结束这个残留进程。
- 点「启动游戏」发现无窗口的残留进程时，会说明 PID 和成因，并提供「结束它并继续」，不再只是一句拒绝。
- 同一份安装不能同时开两个管理器；不同的安装副本仍可各开一个。
- 新增 `touchHLE\zfr_manager.log`，记录启动、退出、拦截与看门狗判断，便于反馈问题时直接定位。

本页同时提供 Windows 更新包和现有 Android 入侵修复版。Android 端没有这个问题：它的运行状态来自一把真正的文件锁（游戏跑在独立进程，进程结束锁即释放），本次未改动。APK 与上一版逐字节相同（versionCode `4`），已经安装该版的玩家无需重复升级。

| 平台 | 下载附件 | 大小 | SHA-256 |
|---|---|---:|---|
| Windows 10/11 x64 | `zombie-farm-windows-x64-v29fix-running-detect.zip` | 95,955,050 B | `FE942A83D6409C26268F4F637EF51D4A0347E117E6BAE21EDF70B089DD0C69F4` |
| Android 5.0+ / ARM64 | `zombie-farm-android-arm64-v29fix-invasion-fix.apk` | 97,312,084 B | `C10F0E00B4AADA2E47944F41245AB5B64C5142849926FCC538179DD405920B7F` |

## 使用与升级

- Windows：解压到新目录，运行 `游戏管理.exe`。已有进度请先用旧管理器备份，再在新目录的管理器中恢复；保留旧目录，避免覆盖自己的进度。
- Android：首次安装可使用本页 APK；更新时覆盖安装即可，签名保持一致。内置 v29fix IPA，其他 IPA 可按需导入。
- 两端默认夜间模式，发行包不预置玩家存档；首次进入游戏后自行创建进度。
- 如果仍看到「游戏已经在运行了」：请确认用的是本页的新包。新版本在遇到无窗口残留时会给出 PID 并允许直接结束；`touchHLE\zfr_manager.log` 记录了当时的判断依据。

## 验证与源码

管理器自检新增 5 项运行状态用例（活动记录被采信、PID 复用被拒、已消失的 PID 被拒、退出码解码、崩溃信息提取），全部通过；脚本语法与 BOM 检查、布局与设置往返检查同样通过。重建的 Windows 发行包独立运行实际 `45.0 s` 通过，包内 sandbox 为 0 文件。

另有一份端到端探针 `_analysis\_probe_launch_state.ps1`：在 `%TEMP%` 的发行包副本里真实启动游戏，验证记录写入、PID 与路径正确、正常退出（`code=0`）与强制结束（`code=-1`）两种路径下记录都在 1 秒内清除。测试全程未接触玩家真实存档。

ZIP 内有 42 个文件、单一同名顶层目录，无 sandbox 存档与运行日志；包内管理器与本次 Git 源码逐字节一致，SHA-256 为 `C8DF5046DD39DE0CFF0A23E6375134653666CE6581BC67D96AA89B59BCA82F40`。

管理器源码见本次 tag [`v29fix-running-detect`](https://github.com/Ashena1017/zombie-farm-touchhle-cn/tree/v29fix-running-detect)。两端 touchHLE 原生程序沿用源码 commit `2a478424b50591360f91790ee760f34b78072987` 的入侵分配器修复；Windows `touchHLE.exe` 为 `28,878,848 B`，SHA-256 `D48D903494AEC412386472637282AA8A1ACC4F0789E1A16921585EE702C1041D`。IPA 仍为 v29fix。

验证边界：看门狗那条分支（窗口消失后管理器主动回来询问）尚未被一次真实的闪退触发过，目前由强制结束进程的探针覆盖；Android 本次没有改动，也没有在手机上跑这条判定。此前稳定闪退的单次 Windows 海盗入侵已由用户确认完成；重复入侵、死亡后补队和 Android 入侵场景仍未实测，详见[入侵修复说明](https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/tag/v29fix-invasion-fix)。

```powershell
Get-FileHash .\zombie-farm-windows-x64-v29fix-running-detect.zip -Algorithm SHA256
Get-FileHash .\zombie-farm-android-arm64-v29fix-invasion-fix.apk -Algorithm SHA256
```
