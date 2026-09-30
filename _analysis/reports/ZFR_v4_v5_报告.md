# ZFR 字号统一 v4 / v5 与「入侵成功数」调查

生成时间：2026-09-15
基线：`zombie_farm/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v3.ipa`
（用户已实测确认 v3 可正常使用）

---

## 一、产物

| 产物 | 大小 | 说明 |
|---|---|---|
| `...fixed-fonts-v4.ipa` | 59,564,493 | helper 修复 + delta 归零（20 处等宽改写） |
| `...fixed-fonts-v5.ipa` | 59,564,493 | 14 个专用 AlertWindow 子类纳入 24/18（19 处等宽改写） |
| `StartZombieFarmNextHour.ps1` | — | 第 12 行 `$game` 已指向 **v5** |

v5 SHA256 = `622A2F88EB6D93C6810E1D8649929C3F23A08817E3332E2A75C7AB841275CE86`
（与 report.json 记录一致；v4 与 v5 均与基线**完全同尺寸**，1086 个成员，`testzip()` 通过）

三个 IPA 的层叠关系：

```
.fixed.ipa ──(v3: 基类 13 站点)──> .fixed-fonts-v3.ipa
                                        │
                                        ├─(v4: helper 修复 20 站点)─> .fixed-fonts-v4.ipa
                                        │                                │
                                        └────────────────────────────────┴─(v5: 子类 19 站点)─> .fixed-fonts-v5.ipa
```

---

## 二、v4：helper 修复 + 字号 delta 归零

### 背景（承接 Claude 中断处）

codex 把「中文名重建 + 字号加成」的 helper 塞进了两个已废弃方法的方法体：

| 方法 | ARM 入口 / 函数体 | Thumb 入口 / 函数体 | delta |
|---|---|---|---|
| `ZFGuiLayer showRateIt` | `0x1b464` / `0x1b46c` | `0x14f6c` / `0x14f70` | +4.0 |
| `ZFGuiLayer showTreeWorldPopUp` | `0x1b688` / `0x1b690` | `0x15110` / `0x15114` | +3.0 |

8/28 的崩溃修复把两个**入口**改成无条件 `bx lr`，于是所有 wrapper 的 `bl 入口` 全部空转——
**中文名重建和字号加成一起失效**。这正是「玩了几天发现新问题」的来源。

### v4 的两半改动

**① retarget（恢复中文名重建）**：cave 内 16 条 `bl 入口` → `bl 入口+8`（ARM +8、Thumb +4）。
入口保持 `bx lr`，所以 ObjC 派发 `showRateIt` / `showTreeWorldPopUp` 依然安全。

**② delta 归零（防止与 v3 的 24/18 叠加）**：
把 4 条 `vadd.f32 s0, s0, s2` 换成冗余的 `vldr s0, [r4, #0x190]`——
重新读回同一个值，紧随其后的 `vstr s0, [r4, #0x190]` 变成空操作。

选择这个写法而非 `vmov.f32 s2, #0.0` 的原因：
- 同样 4 字节，等宽
- **替换编码原样存在于同一个 helper 内部**（ARM `0x1b478`/`0x1b69c` 就是同一条 `vldr`），
  是编码正确性最强的证据
- 顺带把中间寄存器 s2 也一并绕过，不依赖任何浮点运算语义

### 站点清单（20 处：sub6 10 + sub9 10）

| subtype | 地址 | 旧 → 新 | 说明 |
|---|---|---|---|
| 6 | `0x1b480` | `010a30ee` → `640a94ed` | showRateIt helper: +4.0 delta 归零 |
| 6 | `0x1b6a4` | `010a30ee` → `640a94ed` | showTreeWorldPopUp helper: +3.0 delta 归零 |
| 6 | `0x1b4dc` | `690000eb` → `6b0000eb` | `bl 0x1b688` → `0x1b690` |
| 6 | `0x1b4f4` | `630000eb` → `650000eb` | 同上 |
| 6 | `0x1b500` | `600000eb` → `620000eb` | 同上 |
| 6 | `0x1b50c` | `d4ffffeb` → `d6ffffeb` | `bl 0x1b464` → `0x1b46c` |
| 6 | `0x1b5cc` | `2d0000eb` → `2f0000eb` | `bl 0x1b688` → `0x1b690` |
| 6 | `0x1b5dc` | `290000eb` → `2b0000eb` | 同上 |
| 6 | `0x1b758` | `caffffeb` → `ccffffeb` | 同上 |
| 6 | `0x1b768` | `c6ffffeb` → `c8ffffeb` | 同上 |
| 9 | `0x14f7e` | `30ee010a` → `94ed640a` | showRateIt helper: +4.0 delta 归零 |
| 9 | `0x15122` | `30ee010a` → `94ed640a` | showTreeWorldPopUp helper: +3.0 delta 归零 |
| 9 | `0x14fc6` `0x14fda` `0x14fe4` | `…f8` → `…f8`（+2） | `bl 0x15110` → `0x15114` |
| 9 | `0x14fee` | `fff7bdff` → `fff7bfff` | `bl 0x14f6c` → `0x14f70` |
| 9 | `0x15094` `0x150a0` `0x151a0` `0x151ac` | `…` → `…`（+2） | `bl 0x15110` → `0x15114` |

### 独立核验（`tools/v4_verify.py`，全部 PASS）

- 全部 28 个变更字节**都落在两个 cave 区间内**，无一处越界
- 4 个入口字仍然是 `bx lr`（sub6 `1eff2fe1`、sub9 `7047`）
- 4 个 helper 的函数体已无任何 `vadd`/`vsub`，反汇编确认为
  `vldr → (vmov) → vldr → vstr`，即「读出来又写回去」
- 两个 slice 各 33 条 cave 内分支，**0 条**仍指向死入口
- 两个 slice 编辑对称

---

## 三、v5：14 个专用 AlertWindow 子类纳入 24/18

v3 只覆盖了 `ZFAlertWindow` **基类**的 13 个站点。子类自建 label、自带字号常量，
完全不经过基类路径。v5 补齐 19 处（sub6 10 + sub9 9）：

| 类 / 方法 | 改动 | 影响 |
|---|---|---|
| `ZFAlertWindowQuestComplete -initWithQuest:` | 标题 20→24 | 任务完成框 |
| `ZFAlertWindowQuest -initWithQuest:` | 标题 20→24 | 任务框 |
| `ZFAlertWindowFlurryOffer -initWithWindow:` | 标题 20→24 | Flurry 广告框（**它 override 了基类初始化器**，基类站点对它无效） |
| `ZFAlertWindowBrainSpinner -displayResult` | 标题 20→24 | 脑力转盘结果 |
| `ZFAlertWindowFriendsList -init`（两个 label） | 标题 20→24 | 好友列表 |
| `ZFAlertWindowGiftReceive -initWithGifts:` | 标题 20→24 | 收礼物框 |
| `ZFAlertWindowGiftSelection -initWithLevel:` | 标题 20→24 | 选礼物框 |
| `ZFAlertWindowPromo -initWithWindow:withDictionary:` | 正文 15→18 | 推广框 |
| `ZFAlertWindowPromo -display` | 正文 15→18 | 推广框 |

### 为什么改到这两个立即数就够

ARMv6 把浮点常量拆成 `mov rX,#0x1a00000` + 后续 `orr rX,rX,#0x40000000` 组装；
Thumb 用 `movw`（低半）+ `movt rX,#0x41a0`（高半）。

- ARM：`mov` 的立即数携带浮点的**低 25 位**（bit24 是指数最高位，`0x41a00000 & 0x1ffffff = 0x1a00000`），
  改它即可，`orr` 不动。
- Thumb：改 `movt` 的 16 位立即数即可，`movw` 不动。

**每一处替换都做了 decode-back**：按 ARM 的 rotate+imm8 规则重新解码，
再用 `struct.unpack('<f')` 还原成浮点，确认等于 24.0 / 18.0。
（ARM 立即数是「8 位循环右移」编码，rotate 写错会静默得到另一个数值——这是本任务最容易埋雷的地方。）

### 刻意**没有**改的

- `FlurryOffer` 第二个 label、`BrainSpinner -init`、`DailyBonus -init`、`GoldenDice -init` —— 本来就是 24.0
- slide-in 家族与 `ZFAlertWindowStorageItem` —— 正文本来就是 18.0；标题是 19.0，属于另一档设计，改了会破坏视觉层次
- `ZFGuiLayer displayToolTip:` 的 26.0 —— 全游戏 tooltip 共用

### 独立核验（`tools/v5_verify.py`，全部 PASS）

- v4→v5 全容器 diff：**恰好 19 处**，每处 1 字节
- 逐条从**出货字节**（不是站点表）解码，全部还原为 24 或 18
- v4 修复的 helper 区间逐字节未变
- v3 的 13 个基类站点逐字节仍在
- 与 v3 站点无任何地址重叠

---

## 四、「任务统计入侵成功数失败」调查结论

### 机制（已逐字节确认）

1. 任务数据在 `Payload/ZFR.app/Quests.plist`，54 个任务、86 条 requirement，全部由数据驱动。
2. 入侵类任务共 16 条，全部使用
   `notificationID = kInvasionSuccessfulNotification` 或 `kInvasionPerfectGameNotification`。
3. `ZFQuestNotification -startListening`（ARM `0x16a47c` / Thumb `0x10a0ed`）对每个
   requirement 注册观察者：
   ```
   [NSNotificationCenter defaultCenter]
       addObserver:<notification>
        selector:@selector(incrementCount:)
            name:<requirement.notificationID>
          object:nil]                      ← object 传的是 nil
   ```
   **object = nil 意味着不过滤发送方**，匹配完全依赖通知名 + 处理器内部的比较。
4. 发送方只有一处：
   - `ZFGuiLayer -showFightResult`（ARM `0x1c00c`）在胜利分支发
     `postNotificationName:kInvasionSuccessfulNotification`
     `object:nil`
     `userInfo:@{@"name": <enemyDictionary[@"name"] 的副本>}`
     （ARM `0x1c2ec`–`0x1c2f8`）
   - `ZFFightMan -showFightSummaryIn:`（ARM `0x8af0` 附近）发 `kInvasionPerfectGameNotification`
5. `ZFQuestRequirement -incrementCount:`（ARM `0x169018`）按 `type` 分派：
   - **type 0**：要求 userInfo 是 `NSDictionary`，取 `intValue` 累加
   - **type 2**（**所有入侵任务都是这一类**）：自建一个 `NSMutableString`，
     把 `userInfo` 追加进去，然后与自身的 `notificationObject` 做 `isEqualToString:`，
     相等才 `countCurrent += 1`（ARM `0x16924c`–`0x169288`）

### 最可能的根因

**任务数据与游戏运行时发出的 `userInfo` 之间，名称对不上。**

把 `Quests.plist` 的 `notificationObject` 与 `Enemies.plist` 的 `name` 逐一比对：

| 任务 | notificationObject | Enemies.plist 里有吗 |
|---|---|---|
| Overrun the Farm | `''`（空串） | 空串匹配任意内容 → **恒成立** |
| Farming the farmer | `Old McDonnell's Farm` | ✅ |
| Laying Down The Law | `Zombies vs Lawyers` | ✅ |
| Plundering the Pirates | `Zombies vs Pirates` | ✅ |
| Looting the Ninjas | `Zombies vs Ninjas` | ✅ |
| Raiding the Robots | `Zombies vs Robots` | ✅ |
| Ambushing the Aliens | `Zombies vs Aliens` | ✅ |
| Big Top Bash | `Zombies vs Circus` | ✅ |
| Breaking the Spell / Poppy Power | `Tree World` | ✅ |
| **Badger Badger Badger**（复活节） | `Seasonal: Easter` | ❌ **不存在** |
| **Lactose Intolerance**（脑冻结） | `Seasonal : Brain Freeze` | ❌ **不存在** |
| **Down for the Count**（万圣节） | `Seasonal : Halloween` | ❌ **不存在** |
| Survivin' the Blizzard | `Seasonal : Brain Freeze` | ❌ **不存在** |
| Uber Loser | `Seasonal : Halloween` | ❌ **不存在** |

`Enemies.plist` 只有 8 个条目，`name` 分别是：
`Old McDonnell's Farm` / `Zombies vs Lawyers` / `Zombies vs Pirates` / `Zombies vs Ninjas` /
`Zombies vs Robots` / `Zombies vs Aliens` / `Tree World` / `Zombies vs Circus`。
三个 seasonal 名字**在全部 130 个 plist 里只出现在 `Quests.plist` 自己身上**，
游戏其它任何地方都不产生这三个字符串。

推论：**复活节 / 脑冻结 / 万圣节这 5 个入侵任务在原版游戏里就永远无法完成**，
因为游戏从未发出过与 `notificationObject` 相等的名称。这是原版数据缺陷，不是补丁造成的。

### 其余两个可疑点（已排除或降级）

1. **`kInvasionFailedNotification` 根本不存在**——不是笔误，全binary 无此字符串。
   失败路径走的是 `logEvent:` 而非通知。这条**无影响**。
2. **`type: 0` 的 requirement 依赖 `userInfo` 带 `intValue`**——但 86 条 requirement 里
   `type` 只有 1 和 2 两种取值，**没有 type 0**。这条也**无影响**。

### 已确认为「非原因」的项

- **任务代码未被本项目的任何补丁改动。** 逐字节比对 `ZFQuestMan` / `ZFQuestRequirement` /
  `ZFQuestNotification` / `ZFQuestMenu` / `ZFQuestCell` 的全部 144 个方法（两个 slice），
  与 pristine 基线相比**仅 2 处 sub6 / 3 处 sub9** 不同，且全部是：
  - `0x1c` / `0x41c0` 立即数（v3/v5 的标题字号 24.0）
  - sub6 `0x1d1750`、sub9 `0x1553e2` 等（既有的 codex 字号改动）
  → **没有任何一处触及计数、通知或比较逻辑。**
- `Quests.plist` 在 pristine → complete-final → fixed → v5 **四代里 SHA256 完全一致**，
  从未被修改。
- 所有 quest 相关 selector（`incrementCount:` / `completeQuest:` /
  `questTriggerQuestCompleted:` / `startInvasion:` 等）在两个 slice 里都**恰好 1 个 selref**，
  可达性无异常。
- `Enemies.plist` 的 8 个 `name` 与对应任务的 `notificationObject` **完全吻合**，
  非 seasonal 路线是通的。

### 需要你实测确认的一点

上面第 5 步的 type 2 比较逻辑我是**静态读出来的**，无法在模拟器里跑一遍验证。
请你在游戏里试一次**非 seasonal 的入侵**（比如打 Old McDonnell），然后看
「Farming the farmer」这个任务的计数有没有动：

- **计数有动** → 说明机制本身正常，问题就是上面那条 seasonal 名称不匹配，
  那 5 个任务属于原版数据缺陷，改 `Quests.plist` 可以修（但那要改数据文件，不在字号补丁范围内）。
- **计数完全不动** → 说明还有别的环节，我需要再做一轮动态取证
  （重点查 `enemyDictionary` 在 `showFightResult` 时到底有没有 `name` 键，
  以及 `localizedStringForKey:` 是否把通知名换成了中文导致 `addObserver` 的名字对不上）。

---

## 五、本轮新增的工具

| 工具 | 用途 |
|---|---|
| `tools/v4_cave_map.py` | cave 全量带注解反汇编 + 入向分支归属（承接 Claude 中断的 Thumb 侧） |
| `tools/v4_sites.py` | v4 站点编译 + 分支回读 + cave 保护校验 |
| `tools/patch_zfr_helper_v4.py` | v4 patcher（含入口保护、cave 内约束、分支 decode 校验） |
| `tools/v4_verify.py` | v4 独立核验 |
| `tools/v5_sites.py` | 子类站点编译（含 ARM 立即数编码器 + decode-back） |
| `tools/v5_validate.py` | v5 站点验证（decode-back、污染传播到字号槽、寄存器存活期） |
| `tools/patch_zfr_fonts_v5.py` | v5 patcher |
| `tools/v5_verify.py` | v5 独立核验 |
| `tools/value_xref.py` | **准确的**寄存器值追踪交叉引用 |
| `tools/dump_window.py` | 带 selector / CFString / 类引用解析的反汇编窗口 |

### 两个值得一提的技术坑

1. **朴素 xref 在这个 binary 上完全失效。** 这些 slice 用
   `ldr rS, [pc, #imm]` 取一个**增量**，再在另一条 `add rD, pc, rS` 上物化地址——
   基址是 `add` 的 PC，不是 `ld` 的 PC。把两者混为一谈会产出大量**看似合理的假引用**
   （我第一版就因此误判 `kInvasionSuccessfulNotification`「零引用」）。
   `value_xref.py` 正确地建模了这个惯用法。

2. **ARM 立即数是 rotate+imm8。** capstone 把补过的值显示成 `mov r3, #28, #12`（三操作数）。
   必须折叠 rotate 才能读回真实浮点，否则会误读成 2.0。
   同理，Thumb 的 `movt` 掩码是 `0xFBF0`（不是 `0xFBFF`），否则解码全失败。
