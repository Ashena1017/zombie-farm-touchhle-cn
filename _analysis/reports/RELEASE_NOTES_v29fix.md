# Zombie Farm 中文版 · 开箱即用包（v29fix）

解压后**双击 `游戏管理.exe`** 就能玩。不需要安装 Python、Rust 或任何运行库 —— 模拟器、
管理器、字体、依赖库和游戏本体都已经在包里。

> **这个包是什么**：在 Windows 上用 [touchHLE](https://touchhle.org/) 模拟器运行
> 《僵尸农场》（Zombie Farm，bundle 代号 `ZFR`）中文版，并做了三件事 —— 修好崩溃、把界面文字统一放大到看得清、
> 修掉中文缺字与乱码。游戏本体是 2011 年前后的 iPhone 老游戏，原分辨率只有 480×320。

> **想玩原版，还是想玩现代化重制版？**
> 这游戏的开发 / 发行方早已解散、游戏已从商店下架，所以社区做了各种粉丝版本。
> 想玩**原版那一版游戏**（原美术、原数值、离线单机）就用本页这个包；
> 想玩**从头重写的现代化版**（浏览器 / 桌面直接跑，联机、云存档、好友、黑市，不依赖 touchHLE）
> 则去看 [**actualdoctornerd-ai/Zombie-Farm-2-Reforged**](https://github.com/actualdoctornerd-ai/Zombie-Farm-2-Reforged)
> —— 在线即玩 <https://zombiefarmreforged.com>，也有 Windows 离线包。
> **注意：Reforged 原生只有英文**，想玩中文请再装上配套的
> [**纯汉化脚本**](https://github.com/Ashena1017/zombie-farm-reforged-translation-cn)
> （Tampermonkey 用户脚本，词库取自原版官方简体中文语言包，**精翻，不是浏览器机翻**，
> 连 Canvas 里画出来的游戏文字也能翻；只翻译，不改游戏行为）。
> 本页这个包则**开箱即中文**，不需要额外装东西。
>
> **注意**：「Reforged」是**那个**项目的名字，**不是本包** —— 本包跑的是原版《僵尸农场》游戏本体。

---

## 下载与使用

| 步骤 | 说明 |
|---|---|
| 1 | 下载本页附件 `touchHLE-zombiefarm-v29fix.zip`（约 90 MB） |
| 2 | 解压到任意目录（路径**不要**含特殊符号；中文路径没问题） |
| 3 | 双击 **`游戏管理.exe`** |
| 4 | 在界面里点「启动游戏」 |

包内结构：

```
touchHLE-zombiefarm-v29fix/
├── 游戏管理.exe          ← 双击这个
├── GameManager.ps1       管理器的脚本主体
├── 使用说明.html          ★ 全部设置的中文说明（双击用浏览器打开）
├── 使用教程.txt           上手步骤
├── MSVCP140.dll / VCRUNTIME140*.dll    VC++ 运行库（管理器需要）
├── zombie_farm_ipa/
│   └── Zombie Farm ZFR ... fixed-fonts-v29fix.ipa    游戏本体（已打好补丁）
└── touchHLE/
    ├── touchHLE.exe      模拟器（本项目维护的 fork）
    ├── touchHLE_options.txt      当前生效的设置
    ├── touchHLE_dylibs/          模拟运行所需的 iOS 动态库
    ├── touchHLE_fonts/           中日韩字体
    └── touchHLE_sandbox/         存档位置
```

> `使用说明.html` 只在**下载包**里有 —— 它是构建交付包时生成的，
> 仓库里没有这个文件（内容是 `_analysis/_build_release.ps1` 的内嵌模板）。

---

## 这一版做了什么

**v29fix 相对原版游戏 + 原版 touchHLE 的全部改动：**

| 类别 | 内容 |
|---|---|
| **修崩溃** | 升级后完成任务瞬间闪退（悬空通知观察者）—— 根因修复 + 模拟器侧兜底 |
| **界面字号** | 弹窗标题 20→**24**、正文 15→**18**；仓库面板、陵墓按钮、僵尸详情页等逐个修正 |
| **中文显示** | 修 CJK 字体分支从未生效导致的缺字；修 `+200eE`、`+1Ee`、`施肥` 丢空格等乱码 |
| **本地化遗漏** | 「已使用 Invasion Voucher!」、`Insta-Grow` 等未翻译文案 |
| **60 FPS** | 原版被锁在 30fps（模拟器把零超时 run loop 实现成阻塞），已修复为 60fps，**游戏内时间不加速** |
| **滚轮缩放** | PC 上没有触摸屏，改用鼠标滚轮驱动游戏自身的缩放（等价于双指捏合） |
| **大窗口** | 默认 1536×1152（iPad 档 ×1.5），可选 ×1.25 / ×1.5 / ×1.75 或自定义；修好了放大后光源错位与窗口尺寸虚标 |
| **中文说明** | 管理器界面无任何 `?` 按钮，全部说明在 `使用说明.html` |

管理器的其他能力：快进游戏时间、备份/还原/批量删除存档、直接读写金币与脑子。

> 界面里**看不到「?」按钮是刻意设计** —— 说明统一放在 `使用说明.html`，
> 能搜索、能复制，也便于写得更详细。

---

## 校验信息

| 项 | 值 |
|---|---|
| 文件名 | `touchHLE-zombiefarm-v29fix.zip` |
| 大小 | 95,050,820 字节（90.6 MB） |
| SHA-256 | `39601F129B20E53C641E1D6D37D22057B8B9D578E36E75B22060919C5ADA8841` |
| 游戏 IPA sha256（前 16 位） | `E5951F945D23E88F` |
| 模拟器 sha256（前 16 位） | `75A0F9DD97BF0C27` |

校验命令（PowerShell）：

```powershell
Get-FileHash .\touchHLE-zombiefarm-v29fix.zip -Algorithm SHA256
```

---

## 系统要求

- Windows 10 / 11（x64）
- 需要 OpenGL 3.3 以上的显卡驱动（老机器可能需更新驱动）
- 约 300 MB 磁盘空间
- **高 DPI 缩放（如 150%）已适配** —— 选的窗口大小就是实际像素大小

---

## 常见问题

**Q：画面能不能更清晰？**
不能。游戏素材本身最大只有 1024×768，宽度中位数 88 像素；把放大后的画面缩回去比对，
像素差仅 0.3%。**放大只是把同样的画面变大，不增加细节**，这是素材限制，不是设置问题。

**Q：窗口选多大最合适？**
默认的 **1536×1152（iPad ×1.5）** 是推荐值。预置三档 ×1.25 / ×1.5 / ×1.75 都放得进
2560×1440 桌面。**不要自己把「模拟屏幕尺寸」调大** —— 那会让 UI 变小、画面被拉伸。

**Q：滚轮缩放倍率改多少好？**
默认 1.1（每格 ×1.1）。想快速拉远拉近可以调到 1.5，范围 1.01–2.00。

**Q：我的存档在哪？**
`touchHLE\touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents\saveGame.bin2`。
管理器「存档管理」页可以直接备份、还原、批量删除（**正在使用的存档不可删除**）。

**Q：杀毒软件报警？**
包里有一个未签名的 `游戏管理.exe`（5 KB，只是个 GUI 宿主）和模拟器 `touchHLE.exe`。
源码就在仓库里，可以自己核对或自行编译。

**Q：能不能在 macOS / Linux 上跑？**
本包是 Windows x64 构建。touchHLE 本身支持多平台，源码在仓库里，但管理器是 WinForms 写的，
只适用于 Windows。

---

## 免责声明

- 本项目是**非官方的粉丝作品**，与 Zombie Farm 的开发商 / 发行商无任何关系。
- **原版已无处可买**：开发与发行方已解散，游戏已从应用商店下架，官方服务端亦已停运 ——
  这也是社区会去做补丁与重制（如
  [Zombie Farm 2 Reforged](https://github.com/actualdoctornerd-ai/Zombie-Farm-2-Reforged)，
  以及配套的[纯汉化脚本](https://github.com/Ashena1017/zombie-farm-reforged-translation-cn)）的原因。
  若权利方日后重新上架，请优先购买正版。
- 本包内包含的**游戏本体版权归其原权利人所有**，此处仅为方便「下载即可玩」而附带，
  **请仅用于个人学习与备份**。
- 模拟器 [touchHLE](https://github.com/touchHLE/touchHLE) 采用 MIT 许可；
  本项目对其的改动同样以 MIT 发布。本项目自己的代码与文档亦为 MIT。
- 源码、补丁工具链与全部技术文档见仓库：
  [Ashena1017/zombie-farm-touchhle-cn](https://github.com/Ashena1017/zombie-farm-touchhle-cn)
