# 帧率修复报告：Zombie Farm 30fps → 60fps（游戏速度不变）

**日期**：2026-09-19
**结论**：已定位并修复 30fps 上限的根因，实测 **30.20 → 60.00 fps**，且**游戏内时间流逝完全不变**。

---

## 一、根因

不是性能不足，也不是游戏自己锁 30fps，而是 **touchHLE 把"零超时的 run loop 调用"实现成了阻塞调用**。

### 1.1 游戏侧：每帧调两次 run loop

游戏用的是 cocos2d 的 **`CCFastDirector`**（不是 `CCDisplayLinkDirector`）。
`-preMainLoop`（sub9 `0x213a30`，sub9 = armv7 = touchHLE 实际加载的 slice）：

```
0x213abc  blx  _CFRunLoopRunInMode(mode, 0.0, true)   ; 排空事件
0x213ac0  cmp  r0, #4 / beq 回 0x213ab0               ; 4 = HandledSource，继续排
0x213ada  blx  objc_msgSend  sel='drawScene'          ; 画一帧
0x213ae6  blx  _CFRunLoopRunInMode(mode, 0.0, true)   ; 再排空一次
0x213aea  cmp  r0, #4 / beq 回 0x213ade
```

timeout 由 `0x213a58` 的 `vldr d8, [pc, #0xb4]` 载入，该处 literal = **`0.0`**。

### 1.2 模拟器侧：零超时也睡 16ms

`src/frameworks/core_foundation/cf_run_loop.rs`：

```rust
if seconds == 0.0 {
    run_run_loop_single_iteration(env, current_run_loop);   // 却是"跑一整圈"
}
```

而每圈末尾 `src/frameworks/foundation/ns_run_loop.rs:480`：

```rust
let limit = Duration::from_millis(1000 / 60);   // 整数除法 = 16 ms
env.sleep(sleep_until.map_or(limit, |i| i.duration_since(Instant::now()).min(limit)));
```

真实 iPhone OS 上 `CFRunLoopRunInMode(mode, 0.0, true)` 是**非阻塞排空**，立刻返回。
于是游戏每帧付出 **2 × 16 ms = 32 ms** → **约 30 fps**。

### 1.3 profiler 佐证

`--zfr-profile` 累计计数（一次完整运行）：

| 计数 | 值 |
|---|---|
| `run_loop` | 5502 |
| `eagl_present_renderbuffer` | 2750 |
| **比值** | **2.0007** |

run loop 被进入的次数正好是呈现次数的两倍 —— 与"每帧两次轮询"完全吻合。

---

## 二、为什么提帧不会加速游戏

`CCDirector -calculateDeltaTime`（sub9 `0x211a90`）在 `0x211a9e` 调用的 stub：

```
target 0x2d0410 -> literal 0x2d0418 -> slot 0x343a00 -> _gettimeofday
```

**`dt` 来自 `gettimeofday()` 的真实挂钟时间**，不是帧间隔。

> 本报告纠正了本次调查早期的一个错误结论。最初基于 sub6（armv6）分析得出结论，
> 但 touchHLE 日志明确写 `Loading armv7 slice`，实际执行的是 **sub9**。
> 两条 slice 的 `CCFastDirector -preMainLoop` 结构一致，结论不变。

fork 的 `gettimeofday` 实现（`src/libc/time.rs`）返回 `emulated_system_time()`
= 宿主 `SystemTime::now()` + 固定偏移，即**真实流逝时间**。

因此画得勤一倍，只会让每帧 `dt` 减半，游戏时钟仍按真实时间前进。

---

## 三、修复

新增**可选**（默认关闭）选项，不改动上游默认行为：

```
--non-blocking-zero-timeout-run-loop
```

零超时调用改为"让出线程但不等待"（`Duration::ZERO`），
仍会 `yield_thread`，因此**不会饿死其他 guest 线程**。

改动文件（`touchHLE-fork/`）：
- `src/frameworks/foundation/ns_run_loop.rs` — 新增 `run_run_loop_single_iteration_non_blocking()`，`run_run_loop()` 增加 `non_blocking` 参数
- `src/frameworks/core_foundation/cf_run_loop.rs` — 零超时分支按选项选择
- `src/options.rs` — 新选项
- `OPTIONS_HELP.txt` — 帮助文本

---

## 四、实测结果

同机、同存档、同 GPU（NVIDIA RTX 4080 Laptop），每次先 `RestoreTestSave.ps1 -Force`：

| 配置 | 平均 FPS | 最低 | 最高 | 标准差 |
|---|---|---|---|---|
| A. 原 `touchHLE.exe` | 30.19 | 29.96 | 30.53 | 0.244 |
| B. 重编译版，选项**关** | 30.22 | 29.93 | 30.58 | 0.247 |
| C. 重编译版，选项**开** | **60.00** | 59.89 | 60.13 | **0.050** |
| D. 同上，90 秒长跑 | **60.00** | 59.64 | 60.40 | **0.094** |
| E. 选项开 + `--fps-limit=120` | **119.94** | 119.41 | 120.76 | — |
| F. 选项开 + `--fps-limit=off` | **1926.10** | 1784.95 | 1983.73 | — |
| G. 选项开，默认 60 限帧 | **59.99** | 59.92 | 60.04 | — |

**A vs B 几乎逐位相同** → 重编译本身零行为改变。

**F 是决定性证据**：解除限帧后可跑 1926 fps，说明睡眠瓶颈确实被移除，
帧率现在由限帧器（而非人为等待）决定。修复前 `--fps-limit=120` 完全无效（仍卡 30）。

### 4.1 帧率更稳了

标准差 **0.244 → 0.050**（C 组）。因为不再需要每帧等两次 16 ms 的整拍，
帧时间抖动反而下降。

### 4.2 开销

| | 30fps | 60fps |
|---|---|---|
| CPU（单逻辑核=100%） | 1.87 % | 2.25 % |
| GPU 全引擎 | 32.0 % | 37.0 % |
| 工作集 | 262 MB | 259 MB |

60fps 只多花 **0.38 % 单核**（32 核中的 0.012 %）。余量极大。

### 4.3 功能等价性

对比 A/B/C 三种配置的应用 stdout 与模拟器警告（地址/数字归一化后）：

- A vs B（重编译影响）：**逐条相同**
- B vs C（开 60fps 影响）：**逐条相同**
- 三者 panic 数均为 **0**

即：中文本地化补丁路径、游戏代码路径完全未受影响。

### 4.4 run loop 服务速率

| | `run_loop`/s | `present`/s | 比值 |
|---|---|---|---|
| 选项关 | 50.97 | 25.46 | 2.0022 |
| 选项开 | 104.79 | 52.39 | 2.0000 |

游戏每帧仍固定轮询两次，所以 run loop 服务频率随帧率一起翻倍（≈60 → ≈120/s）。
**这是无害的**：`NSTimer` 按到期时间触发而非轮询次数，计时器节拍不变；
触摸输入只是延迟更低。

---

## 五、编译环境（从零重建）

原始 fork 的 `touchHLE.exe` 报告 `touchHLE fa3d095`。经查
**`fa3d095` 是上游仓库真实存在的 commit**：

```
fa3d09511d471f505e41abed7c535e4dfbd7c59c
2026-08-19  "Fix Zombie Farm action manager corruption"
```

但它**不在 trunk 线上**（两者分叉 66 个 commit）。所以：

- `touchHLE-trunk/`（主人下载的）**不含 ZFR 适配**，编译出来跑 ZFR 直接 panic：
  `ns_dictionary.rs: assertion failed: this == ... "NSMutableDictionary"`
- `touchHLE-fork/`（已取回 fa3d095）**含全部适配**：185 处引用、
  21 个专属文件（`src/objc/messages/zombie_farm.rs` 等）

已备好的自包含工具链（均在 `_build_tools/`，不碰系统 rustup）：
- rustc / cargo 1.98.1
- cmake 4.4.3（pip 装）
- MSVC 2022 Community + Windows SDK 10.0.22621
- vendor：boost 1.81 / SDL (07d0f51) / dynarmic (a41c380) / openal-soft (23c8a35) / stb (9f1776a)

编译坑（已解决）：
1. CMake 4 移除了 `< 3.5` 兼容 → `CMAKE_POLICY_VERSION_MINIMUM=3.5`
2. trunk 需要 `libxml2.2.dylib` + `libsqlite3.dylib`，本项目 `touchHLE_dylibs/` 原本没有
   → 已从 touchHLE 官方发布补上（**fork 不需要这两个**）
3. `git checkout` 会把 submodule 目录建成空目录，需按内容而非存在性判断

---

## 六、安装与回滚

已安装：
- `touchHLE.exe` ← `touchHLE_fork.exe`（26,275,328 B，sha256 `D17BE6F3…`）
- 旧版备份：`touchHLE.exe.backup-fps60-20260919-204040`（22,077,952 B）
- 启动器 `StartZombieFarmNextHour.ps1` 第 103 行追加选项：
  ```powershell
  & $touchHLE $game '--device-family=ipad' '--landscape-right' '--non-blocking-zero-timeout-run-loop'
  ```

**回滚**：
```powershell
.\_analysis\_install_fps60.ps1 -Revert
```

**端到端验证**（走真实启动器路径）：**60.00 fps**，无 panic。

---

## 七、复现脚本

| 脚本 | 用途 |
|---|---|
| `_analysis\_setup_rust.ps1` | 装自包含 rust 工具链 |
| `_analysis\_fetch_vendor.ps1` | 拉 vendor 依赖 |
| `_analysis\_pin_vendor.ps1` | 按上游 SHA 钉住 vendor |
| `_analysis\_fetch_fork_src.ps1` | 取回 fa3d095 源码 |
| `_analysis\_build_fork.ps1` | 编译 fork |
| `_analysis\_smoke.ps1` | 单次冒烟测试 |
| `_analysis\_final_ab.ps1` | A/B/C/D 对比 |
| `_analysis\_equiv.ps1` | 功能等价性检查 |
| `_analysis\_cpu_cost.ps1` | CPU 开销 |
| `_analysis\_runloop_rate.ps1` | run loop 服务速率 |
| `_analysis\_fr_dt_stub.py` | 证明 dt 来自 gettimeofday |
| `_analysis\_install_fps60.ps1` | 安装 / 回滚 |

---

## 八、注意事项

1. **不要用 `--fps-limit=off`**：会跑到约 1900 fps，白白发热耗电。默认 60 即可。
2. 本修复是 **opt-in**。同一份 `touchHLE.exe` 若用于其他 app，建议去掉该选项
   （或写入 `touchHLE_options.txt` 仅对 ZFR 生效）：
   ```
   com.playforge.ZombieFarm.ZFR: --non-blocking-zero-timeout-run-loop
   ```
3. `touchHLE.exe.backup-20260827-222546`（18.6 MB）是更早的官方版，与本次无关。
