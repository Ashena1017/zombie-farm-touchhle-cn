# _analysis

分析、诊断与验证脚本的存放处。**运行时和交付物在项目根目录，这里的东西都不参与游戏运行。**

```
_analysis/
├── *.py  *.ps1     在用脚本 —— 见下表
├── TECHNICAL.md       本文件
├── gui.png         当前 GUI 的样子（供对照）
├── _t2_base.txt    process.md 引用的取证 dump
├── archive/        上一轮的临时脚本（结论的推导过程，**别删**）
│   ├── tools/      `tools/` 里被淘汰的分析脚本 + 旧的子目录
│   └── _advver/  _adv_verify/  _scratch/  _vp/
├── dumps/          只保留被文档点名的取证产物（_zfz_* 等），其余已清理
├── perf/           **空目录**，测试脚本的输出位置（内容已于 2026-09-23 清理）
└── reports/        技术报告（.md），当前状态的事实来源
```

> **2026-09-23 目录重构后**：模拟器相关的一切（`touchHLE.exe`、`touchHLE_dylibs/`、
> `touchHLE_fonts/`、`touchHLE_sandbox/`、`touchHLE-fork/`、
> `_build_tools/`、各种日志与状态文件）都在 **`<root>\touchHLE\`** 里了。
> 本目录的脚本用 `$hleRoot`（PowerShell）/ `_HLE`（Python）来定位它，写法是
> 「有 `touchHLE\touchHLE.exe` 就用子目录，否则退回扁平布局」，两种布局都支持。
> **新脚本照抄这个模式**，别硬编码 `touchHLE\`。
> 详见 `process.md` 的「目录重构」一节与主 README 第九节。

> **2026-09-23 清理了 126 MB 过程性产物**（详见主 README 第八节末尾）：
> 旧会话对话记录（`_claude_*`/`hist_*`/`history_*`/`session_*`/`analysis_hist_*`）、
> `__pycache__`、死胡同构建产物、`perf/` 的全部截图与日志、无写入脚本的孤儿 dump。
> 保留判据是「**有脚本读它**」或「**有文档按名字引用它**」——
> `dumps/` 与 `perf/` 只作为目录保留，因为多个脚本往那里写输出。

所有脚本都用 `__file__` 定位项目根目录，**在哪个工作目录下运行都可以**：

```powershell
python _analysis\_verify_v14fix.py
python _analysis\_dis.py 6 0x195000 0x195060
```

---

## 当前脚本

### 反汇编 / 查询（通用，改补丁时最先用这几个）

| 脚本 | 作用 |
|---|---|
| `_dis.py <sub> <lo> <hi> [ipa]` | **带注解的区间反汇编**：解析 `__objc_selrefs` / `__objc_classrefs` 的 delta 惯用法、CFString（自动解引用到字符串）、以及 `__text` 内的分支归属到哪个 ObjC 方法 |
| `_xref.py <lo> <hi> [ipa]` | 谁 `bl`/`b` 到了这个地址区间（两个 slice 都查） |
| `_who_calls.py` | 用选择器找 `objc_msgSend` 调用点（值追踪，能解 delta 惯用法） |
| `_layout.py` | 两个 slice 的 section 布局 + 空隙（找 code cave 用） |
| `_dead.py` / `_deadcheck.py` | **死方法判定**：选择器不在 `__objc_selrefs`、字符串只出现一次、无分支指向入口 —— 见主 README 5.9 |
| `_readsave.py <save...>` | 读 `saveGame.bin2` 的任务段（大端），打印每个任务的进度 |
| `_vec.py` | 从二进制里取真实指令字节，作为编码器自检向量 |
| `_v17_cf.py <ipa> <子串...>` | **谁引用了这些 CFString**：枚举全部 CFString，再逐方法走查指令，报告 materialise 站点 + 紧随的 `objc_msgSend` |
| `_v17_pc.py` | **证明 Thumb `add rd, pc` 的 PC 基址是 `addr+4`（不对齐）** |
| `_v17_floats.py <sub> <f1> <f2>...` | **按浮点常量找站点**（字号都是 `movt rX,#0x41xx` / `mov rX,#0xNN00000`+`orr`），带方法归属 —— 查字号问题就用它 |
| `_v17_moji.py` | 全库乱码普查：两个 slice 的每个 CFString 与每个 `__cstring`/`__const` 串 |
| `_t6_ann.py` | **可复用的 Thumb 注解器**：解析 SEL / CFString / cstring / 浮点（`movt`、`vldr` 池、`vmov`）/ `str rX,[sp,#n]` 栈参数，含 `dump_method` / `scan_class` / `ordered_methods` |
| `_t6_range.py <out> <lo> <hi> ...` | 把任意地址区间的注解反汇编写进文件（避免控制台渲染超大输出） |
| `_t7_sweep.py [out]` | **全类 CFString 引用普查**：哪些方法用到 `STATS/ABILITY/POWER/LIFE/SPEED/Mausoleum` 等串 |
| `_t2_cmp.py <ipa> CLASS SEL ...` | **跨版本对比某个方法的 label 工厂**（判断字号是原始值还是被改过） |
| `_t2_users.py SEL ...` | 全库找某个选择器的所有发送点 |
| `_v21_refs.py <lo> <hi>` | 某地址区间**有没有被任何分支/字面量引用** —— 选 code cave 前必跑 |
| `_v21_reach.py [min]` | 从全部方法 IMP 做可达性分析，列出没走到的区间（候选 cave，**需再用 `_v21_refs.py` 复核**） |
| `_v23_recon.py` | 逐指令跟踪 `ZFAlertWindow -alertWindowSlideInInformative:` 里 r5/fp 的去向 |
| `_v24_recon.py` | 谁引用了 `title1`、sub9 两个字体名 CFString 的地址、陵墓 label 的 fontName 装载指令 |
| `_v24_vmov3.py` | **VFP 立即数定值**：逐位翻转 `vmov.f32`，找出立即数域再暴力搜索目标值 |
| `_v24_sub6.py` | sub6 的 `add rX, pc, rX` PIC 惯用法解析 |

### 验证器（每个都**不 import** 对应 patcher，从出货文件独立复算）

| 脚本 | 对应版本 |
|---|---|
| `_verify_v10fix.py` … `_verify_v29fix.py` | v10–v29（v12 任务进度持久化、v13 技能名本地化、v14 CJK 字体分支、v20 工具条位移、v21 字号、v22 setColor: stub、v23 dimensions 高度、v24 标题位置、v25–v27 微调、v28 `stopListening` 注销循环、v29 `.strings` 改 OpenStep 文本） |
| `_verify_v28_verifiers.py` | v28 验证器自身的**变异测试**（12 种故意改坏，要求全部被抓到） |
| `_verify_readme_claims.py` | 把主 README 5.11/6.3–6.5 的**事实性声明**逐条对真实二进制复核 |
| `_verify_layout.ps1` | **目录布局**：每个模拟器资源都能通过 `$hleRoot` 解析到，且根目录无残留 |
| `_verify_layout_match.ps1` | **与 `Release\` 同构**：两边都把模拟器放在 `touchHLE\`，且交付包里没有混进源码树/工具链 |
| `_v29_loader_probe.ps1` | 用**游戏同一个** `plist` crate 版本解析出货成员字节（真加载器探针） |

一次性全部跑：

```powershell
Get-ChildItem _analysis\_verify_*.py | ForEach-Object { "{0,-34} {1}" -f $_.Name, (python $_.FullName 2>&1 | Select-Object -Last 1) }
```

预期全部 PASS / ALL CHECKS PASSED。

### 管理器 / 模拟器 / 交付（改动这几处时用）

| 脚本 | 作用 |
|---|---|
| `_build_fork.ps1` | 全量构建 fork（校验 vendor 依赖存在） |
| `_build_fork_now.ps1` | **增量构建**（约 1m20s），产物是 `touchHLE\touchHLE_fork.exe`，**必须再复制成 `touchHLE.exe` 与 `Release\touchHLE\touchHLE.exe`** |
| `_build_release.ps1` | 生成整个 `Release\` 交付包（含 `使用说明.html` 的内嵌模板，改说明书内容改这里） |
| `_verify_release.ps1` | 启动交付包副本，验证能独立运行 |
| `_release_e2e.ps1` | 交付包的端到端测试 |
| `_device_size_e2e.ps1` | **八档窗口客户区 Win32 实测**（DPI 感知），必须与 `GameManager.ps1` 的 `Get-WindowSizeForScale` 一致 |
| `_device_size_roundtrip.ps1` | 设置的读写往返 + 无遮蔽 + 窗口尺寸算术 + 预置是否放得进屏幕 |
| `_device_size_argtest.ps1` | `--device-size` 参数校验 |
| `_gui_controls_test.ps1` | **驱动真实 GUI 控件**（发 `WM_COMMAND`），验证设置真的落盘 |
| `_res_order_check.ps1` | 直接读运行中 GUI 的下拉框内容，验证顺序 |
| `_gui_tip_test.ps1` | 验证界面上**没有** `?` 按钮，且 `使用说明.html` 确实写到了这些设置 |
| `_gui_shot.ps1` | GUI 截图（`PrintWindow`）。**截图前确认没有遗留的同名窗口**，否则会抓到旧进程 |
| `_gui_bulk_delete_test.ps1` | 批量删除存档的破坏性端到端测试（用安全副本） |
| `_zoomfix_check.ps1` | 逐档截图验证布局 + 滚轮缩放（会打印 `ZombieFarm zoom:` 日志） |
| `_gl_trace_probe.ps1` | `TOUCHHLE_ZF_GL_TRACE=1` 的 GL 调用追踪（framebuffer 感知 scale-hack 的取证工具） |
| `_ensure_bom.ps1` | **改完含中文的 `.ps1` 必须跑**：`edit` 工具会剥掉 BOM，不修就一堆语法错误 |
| `_html_preview.ps1` | 无头 Edge 渲染 `使用说明.html` 供核对 |
| `_restore_vendor.ps1` | 重新抓取 fork 的构建依赖（曾经是 junction，见 process.md #26） |

### 专项诊断（保留下来是因为结论写在主 README 里，随时可能复查）

| 脚本 | 查了什么 |
|---|---|
| `_season*.py` | 季节性任务与 `Enemies.plist` 的名称对不上（主 README 7.2） |
| `_abil*.py`、`_abilitytable.py` | `getRandomAbilityToUnlock` 的 23 个技能名 CFString 与 tag→名字跳转表 |
| `_branch.py` | 弹窗两条字体分支（TTF vs 位图）的完整注解 |
| `_lang.py` | `getCurrentLanguage` 的实现与全部 90 个调用点（主 README 7.5） |
| `_flags*.py`、`_unlock.py` | `GameData.abilityFlags`（`ZFBitBank`）的读写路径、技能发放链路（主 README 7.4） |
| `_tier*.py` | `+[ZFActorAbility abilitiesToUnlockForTier:]` 的两段筛选 |
| `_cjk.py` | 二进制里有没有中文、`Localizable.strings` 里技能名翻译齐不齐 |
| `_enemies.py` | `Enemies.plist` 的 name 与 `Quests.plist` 的 `notificationObject` 比对 |
| `_zfz_*.py`、`_zfe_*.py` | 施肥机制取证（主 README 与 `reports/ZFR_施肥*` 引用的就是这些） |
| `_zoom_*.py` | 滚轮缩放：`setZoomOutAmount:` 的钳制分支、`winSize` 判据 |
| `_sprite_shift.py` / `_mag_check.py` / `_emitter_*.py` | 放大后光源错位的像素级取证 |
| `_viewport_const_scan.py` / `_gl_symcheck.py` | GL viewport 常量与符号引用扫描 |

### 维护脚本（一次性，已跑过；留着是为了知道当时怎么做的）

| 脚本 | 作用 |
|---|---|
| `relocate_paths.py` | 把脚本改成用 `__file__` 定位项目根目录 |
| `_reorg_touchhle.py` | **目录重构**：把模拟器相关的 19 项移进 `<root>\touchHLE\`（幂等） |
| `_reorg_fix_paths.py` | 批量把脚本里的模拟器路径改写成 `$hleRoot` / `_HLE`（幂等） |
| `_reorg_fix_jobs.py` | 修上面那个脚本的一个插入点 bug |
| `tidy_finish.py` | 早期的归档整理（**它的文件清单已过时**，仅作历史参考） |

---

## archive / dumps / reports

- `archive/` —— 之前几轮的探针脚本，名字都很短（`_q7.py`、`_d10.py`、`_iv3.py` …），
  **别删**：主 README 里若干结论的推导过程只在这些脚本里。真要用时先看它们
  是否依赖已经不存在的中转文件。
- `archive/tools/` —— `tools/` 里被淘汰的那批（`adv_*`、`refute*`、`q_d19_*` …）。
  `tools/` 现在只保留还在用的 46 个模块。
- `dumps/` —— **2026-09-23 清理后只剩被点名的取证产物**：`_zfz_*`（施肥机制）、
  `_abil2.out.txt`（13 MB，技能表）、`_flags.out.txt`（10 MB，标志位）、
  `_reorg_moves.json`（重构移动日志）。其余历史中间产物已删 ——
  需要时用 `_analysis/` 里对应的脚本重新生成即可。
- `reports/` —— 技术报告，**当前状态的事实来源**（11 份）：
  `ZFR_v4_v5_报告.md`、`ZFR_v6_与三个新问题.md`、`ZFR_图3_任务计数_深挖报告.md`、
  `ZFR_任务闪退_通知观察者.md`、`ZFR_v28fix_任务闪退根因修复.md`、
  `ZFR_v29fix_施肥飘字还原.md`、`ZFR_施肥飘字_长度限制复查.md`、
  `ZFR_施肥飘字_表来源订正.md`、`ZFR_施肥僵尸_机制取证.md`、
  `ZFR_施肥僵尸_收益效果.md`、`fps60-report.md`。
  旧会话的对话记录提取（`_claude_*.txt`、`history_*.txt`）已删，结论都在上面这些报告里。
- `perf/` —— **空目录**，只作为测试脚本的输出位置。历代截图与日志已在 2026-09-23
  清理（能由脚本重新跑出来）。

## 注意

**`tools/` 是活代码**（patcher + 基础设施），这里的脚本大多 `import` 它。
移动 `tools/` 里的任何文件之前先看主 README 6.1 / 6.2 的表。
