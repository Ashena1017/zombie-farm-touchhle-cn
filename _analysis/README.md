# _analysis

这里存放专项测试、诊断脚本和技术报告。日常构建及发行包校验从 [scripts/](../scripts/README.md) 进入。历史迁移脚本见[归档索引](legacy/README.md)。

```
_analysis/
├── *.py  *.ps1      专项验证和探针，部分脚本依赖历史 IPA
├── android/         MuMu 定向诊断助手
├── legacy/          纳入版本控制的历史脚本
├── reports/         技术报告与旧版发布记录
├── dumps/           本机取证与构建验证输出
├── perf/            本机测试数据
└── archive/         本机旧探针、二进制备份和一次性发布脚本
```

本机 Windows 测试针对 `run/windows/touchHLE/`，管理器在 `windows/`。发行 ZIP 和 APK 从 `dist/` 读取。旧报告中的 `Release/` 等路径对应当时的版本。

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
| `_v29_loader_probe.ps1` | 用**游戏同一个** `plist` crate 版本解析出货成员字节（真加载器探针） |

一次性全部跑：

```powershell
Get-ChildItem _analysis\_verify_*.py | ForEach-Object { "{0,-34} {1}" -f $_.Name, (python $_.FullName 2>&1 | Select-Object -Last 1) }
```

预期全部 PASS / ALL CHECKS PASSED。

### Windows 管理器与运行测试

| 脚本 | 作用 |
|---|---|
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

## 专项报告和本机证据

- [reports/](reports) 存放问题取证和旧版发行说明。
- `dumps/` 和 `perf/` 由脚本写入。历史报告里引用的日志、截图和包仍按原批次保留。
- `archive/` 保留本机早期探针与历史附件辅助脚本。可跟随仓库迁移的旧工具见 [legacy/](legacy/README.md)。
- 此处的反汇编脚本与 [IPA 工具](../tools/README.md) 共享 Python 模块和历史输入，跨目录移动前核对导入与素材路径。
