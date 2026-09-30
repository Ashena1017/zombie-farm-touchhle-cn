# ZFR v6 与三个新问题的诊断

生成时间：2026-09-15
基线：`...fixed-fonts-v5.ipa`（用户实测可用）

---

## 一、产物

| 产物 | 大小 | 说明 |
|---|---|---|
| `...fixed-fonts-v6.ipa` | 59,564,493 | 「提前解锁道具」弹窗文字 14.0 → 18.0（2 处等宽改写） |
| `StartZombieFarmNextHour.ps1` | — | `$game` 已指向 **v6** |

v6 与 v5 逐字节只差 **2 个字节**，`testzip()` 通过；v3 的 13 个站点、v4 的 helper 修复、v5 的 19 个子类站点全部逐字节保留。

层叠关系：

```
v3 基类 13 站点 ──> v4 helper 修复 20 站点 ──> v5 子类 19 站点 ──> v6 解锁弹窗 2 站点
```

---

## 二、图1「提前解锁道具」文字放大 —— 已修复（v6）

### 根因

这个弹窗是 `ZFMarketMenu -unlockItem:` 生成的。它**不用** `initWithWindow:` 建好的 body label，而是**另建一个**再 `setBody1:` 装回去 —— 和 v3 已经处理过的 Simple/SimpleChoice「重建」惯用法完全一样，只是商场这套有自己的副本，所以 v3/v5 都够不着它。

```
ARM   0x6a49c  mov  r2, #0x1600000        ; 14.0
      0x6a4bc  orr  r2, r2, #0x40000000
      0x6a4c0  str  r2, [sp, #0xc]        ; fontSize 槽
      0x6a4a0  labelWithString:...:fontSize:  →  0x6a4dc setBody1:

Thumb 0x4d6ec  movs r3, #0
      0x4d6f4  movt r3, #0x4160           ; 14.0
      0x4d6fc  str  r3, [sp, #0xc]
      0x4d704  blx  objc_msgSend
```

### 修复

| subtype | 地址 | 旧 → 新 | 效果 |
|---|---|---|---|
| 6 | `0x6a49c` | `1626a0e3` → `1926a0e3` | `mov r2,#0x1600000` → `#0x1900000`，14.0 → 18.0 |
| 9 | `0x4d6f4` | `c4f26013` → `c4f29013` | `movt r3,#0x4160` → `#0x4190`，14.0 → 18.0 |

两处都做了 decode-back：按 ARM rotate+imm8 规则重新解码，还原成浮点确认等于 **18.0**。

### 一个技术要点

ARM 的 `mov` 立即数携带浮点的**低 25 位**，不是 24 位 —— `0x41a00000 & 0x1ffffff = 0x1a00000`，bit24 是指数的最高位。我第一版扫描器用 24 位掩码，**恰好把 14.0（`0x1600000`，bit24 置位）整个漏掉**，只好回头修。这个坑和之前「capstone 把补过的值显示成 `mov r3,#28,#12` 三操作数」是同一类问题。

---

## 三、图2 入侵成功后的僵尸技能名仍是英文 —— 根因已定位

### 现象
弹窗显示 `Unlocked a new **ZomBumpkin** ability!`，应为「获得了一项新的**南瓜头僵尸**技能！」

### 根因

`ZomBumpkin` **不是显示名，是内部 actor 子类型标识符**。

证据链：
1. `ZFMarketMenu -unlockItem:` 那一带的 `__cstring` 里，`ZomBumpkin` 和这些字符串**紧挨着排成一串**：
   `Zombie` / `Girl Zombie` / `ZomBumpkin` / `Headless Zombie` / `Zyborg` / `ZomBeauty` / `ZomBruiser` / `Kindlehead` / `ZomBotanist` / `Zombot` / `Amazombie` / `ZomBrute` / `Flamehead` / `Flower Zombie` / `ZomGoblin` / `Robo Zombie` / `Zombielocks` / `Zombarian` / `Party Zombie` / `Zombee`
   —— 这是 **actor 类名表**，不是本地化表。
2. 该 CFString 的唯一引用点是 `ZFFightMan -getRandomAbilityToUnlock`（ARM `0xb70f8`），它把这张表里的名字**直接返回**。
3. 调用方 `0xb7530` 起做：
   ```
   localizedStringForKey:@"Unlocked a new %@ ability!"  →  「获得了一项新的%@技能！」
   stringWithFormat:(该译文, <getRandomAbilityToUnlock 的返回值>)
   ```
   **只本地化了模板，没有本地化 %@**。
4. `zh-Hans.lproj/Localizable.strings` 里 `'ZomBumpkin' = '南瓜头僵尸'` **是存在的** —— 但代码从没查过它，因为返回的是 actor 名而非本地化 key。

**所以这是原版游戏的本地化缺口**，不是补丁造成的。`ZombieNames.plist` 里那 124 个中文僵尸名（codex 加的）只用于**给僵尸起名**，不覆盖技能名。

### 修复可行性（未实施，需你确认）

能做，但要注入中文串。已确认的约束：

- 可执行文件里目前**只有一条 CJK 串**（`__cstring@0x3dabe8` 的「概率获得」），说明表本身支持中文。
- `__cstring` 尾部**没有富余空间**（gap = 0），Mach-O 的 section 在不改动 header 的前提下无法扩容。
- 所以只能：把中文写进 **`__text` 内部的空洞**（v2 当年就是这么放 code cave 的），再把 CFString 的字符指针指过去 —— 每处需要改 CFString 的 `data` 指针 + 写入中文字节。

**代价与风险**：约 16 个名字 × 各 12~18 字节，需要找 200+ 字节的连续空洞，并且要绕过 v4 正在使用的 helper 区域。属于「可以但不算干净」的改动。

**更简单的替代方案**：直接**改 `Localizable.strings`**（zh-Hans）—— 但如上所述代码路径根本不查它，所以无效。

**我的建议**：这一项先不动。它的收益是 16 条技能名，风险是往 `__text` 里塞数据；而前面 v3~v6 一直坚持「只做等宽原地替换、不碰 code cave」这条原则，正是这个原则让 v4 的 helper 修复能干净地落地。如果你很在意，我可以单独做一轮，用和 v2 相同的方式开洞，并配一轮字节级验证。

---

## 四、图3 入侵计数重启后回退 —— 根因已定位

### 现象
当次入侵显示 1/3，关掉游戏重开变回 0/3。

### 已排除的假设

- **不是通知匹配问题。** 图中任务是「挑战地霸」= `Beat Old McDonnell 3x`，其 `notificationObject` 是 `Old McDonnell's Farm`，与 `Enemies.plist` 的 `name` **完全吻合**；`ZFQuestNotification -startListening` 注册观察者时 `object:nil`（不过滤发送方），当次能正确累加 **1/3** 恰恰证明整条通知链是通的。这推翻了我上一轮「seasonal 名称不匹配」是主因的判断 —— 那只是**部分任务**的独立缺陷。
- **不是存档没写。** `saveGame.bin2` 里**确实有任务数据**（见下）。

### 存档实际内容（大端序）

`saveGame.bin2`（1861 字节）里能解析出任务记录，形如「quest id + 计数」：

| 偏移 | 任务 id | 任务 | 随后的计数 |
|---|---|---|---|
| `0x00f4` | 7 | Overrun the Farm | 15 |
| `0x00f8` | 15 | Plundering the Pirates | 1 |
| `0x0144` | 51 | Breaking the Spell | 1 |
| `0x0164` | 13 | **Farming the farmer** | **1** |
| `0x019c` | 45 | Big Top Bash | 1 |
| `0x01bc` | 47 | Ringmastered | 1 |

**注意 `0x0164`：任务 13 就是「挑战地霸」，存档里计数是 1** —— 与你说的「当次 1/3」完全对上。

而 `saveGame.bin2.bak-20260915-133615-222`（870 字节，8/29 之前的旧档）里**一条入侵任务记录都没有**（0 occurrences）。

### 写入/读取两侧的实现（已逐字节确认）

`GameData -addUserData:`（ARM `0x18655c`）写：
```
addUnsignedInt:  <currentQuests.count>
每个 quest:  key "ID" -> addUnsignedInt:<quest index>
             key "progress" -> addUnsignedInt:<每个 requirement 的 countCurrent>
```
`GameData +readUserData:intoGameData:withVersion:`（ARM `0x1872b4`）读回同一形状，用 `initWithID:` + `requirements` + `setCountCurrent:` 重建。

**两侧都在，形状对称，键名都是 `ID` / `progress`。**

### 结论与待确认点

存档**确实保存了** `Farming the farmer = 1`，但重开后显示 0/3。所以问题不在「有没有写」，而在 **load 之后到 UI 显示之间**。最可能的三个环节：

1. **UI 刷新时机**：「任务」面板读的是 `ZFQuestNotification` 内存对象的 `countCurrent`，而恢复流程 `ZFQuestMan -restoreQuestsFromSave`（ARM `0x16db7c`）是**从实时对象重建** quest 数组的；如果面板在重建完成前就取了值，就会显示 0。
2. **恢复时的匹配条件**：`restoreQuestsFromSave` 用 `indexOfObject:` 在新的 quest 列表里找旧 requirement，匹配靠对象的 `isEqual:`/`ID`。若匹配失败，计数会保留默认 0。
3. **存档写入时机**：`addUserData:` 只在 `save` 时跑；若退出前最后一次计数变化没触发存档，磁盘上的值就会滞后。但这里磁盘上是 1，与显示一致，所以这条不是主因。

**需要你配合的一次测试**：再打一次 Old McDonnell，让计数变成 2/3 或 3/3，**先不要退出**，回到农场界面再打开任务面板看数字是否还在。然后正常退出重开，再看：

- 若**重开后回到 0/3**（而不是 1/3）→ 说明 load 路径确实没把 progress 还原，我按第 2 条深挖 `restoreQuestsFromSave` 的匹配逻辑。
- 若**重开后是 1/3**（即停留在上次存档时的值）→ 说明是**存档时机**问题，计数只在特定时刻落盘，我改查 `save` 的触发点。

我暂时无法只靠静态分析区分这两者 —— 因为两条路径的代码都存在且看起来对称，差别在运行时状态。所以这一项我**没有动任何字节**，避免在没有验证手段的情况下改坏存档逻辑。

---

## 五、本轮工具

| 工具 | 用途 |
|---|---|
| `tools/patch_zfr_fonts_v6.py` | v6 patcher（图1 修复） |
| `tools/v6_verify.py` | v6 独立核验 |
| `tools/unlock_font_sites.py` | 扫方法内的 font 调用点 + 浮点立即数构造 |
| `tools/quest_save_trace.py` | 追踪 `currentQuests`/`completedQuests` 的 ivar 在存取两侧的引用 |
| `tools/ivar_xref.py` | 列出一个 `__objc_ivar` 的全部引用点及其归属方法 |
| `tools/save_probe.py` | 结构化解析 `saveGame.bin2`，把 quest id 对照 `Quests.plist` |
| `tools/dump_window.py` | 带 selector / CFString / 类引用解析的反汇编窗口 |
| `tools/value_xref.py` | 寄存器值追踪交叉引用 |

---

## 六、还没解决 / 需要你决定的

1. **图2（技能名英文）**：可修但需往 `__text` 注入中文串。建议先不动，等你确认要不要单独做一轮。
2. **图3（计数回退）**：根因收窄到 load 路径或存档时机，需要你按上面的测试区分。代码一个字节没动。
3. **上一轮报告的 seasonal 任务缺陷仍在**（`Seasonal: Easter` / `Seasonal : Brain Freeze` / `Seasonal : Halloween` 这三个名字游戏里从不产生，导致 5 个季节性入侵任务无法完成）—— 与本轮图3 是**两个独立问题**，图3 是常规任务（Old McDonnell）也受影响，范围更大。
