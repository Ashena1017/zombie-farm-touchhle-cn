# 图3 深挖报告：入侵成功任务计数不累计 / 重启回退 0/3

分析对象：`zombie_farm/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v6.ipa`
（sub6 = ARM，sub9 = Thumb，两 slice 代码一致）

---

## 0. 先给结论

**结论 A（已验证，字节级）**
v3～v6 的所有改动**没有一处碰到任务逻辑**。把 v6 与 `complete-final` 逐字节对比，全二进制共 50 个差异字节、30 个区间，全部落在字体立即数上（`mov/movt/movw` 的 float 常量），无一处修改任务相关指令。**图3 不是我的补丁造成的。**

**结论 B（已验证，字节级）**
存档 `saveGame.bin2` 里任务进度字段**全为 0**。按格式解析出 10 条任务记录，`progress` 数组无一例外是 0：

```
0x0144: ID=51 reqs=1 progress=[0]
0x0150: ID=53 reqs=3 progress=[0,0,0]
0x0164: ID=13 reqs=1 progress=[0]      <- Old McDonnell's Farm 3x（用户看到 1/3 的那个）
0x0170: ID=17 reqs=1 progress=[0]
0x017c: ID=23 reqs=1 progress=[0]
0x0188: ID=28 reqs=3 progress=[0,0,0]
0x019c: ID=45 reqs=1 progress=[0]
0x01a8: ID=46 reqs=3 progress=[0,0,0]
0x01bc: ID=47 reqs=1 progress=[0]
0x01c8: ID=33 reqs=2 progress=[0,0]
```

存档 mtime `19:47:31` 与最后一次会话（log `11:45:31 +0000` = 本地 19:45）对应，即"入侵后退出"的那次写盘。**进度没有写进去。**

**结论 C（读档侧已排除，2026-09-16 探针实验证实）**
手工构造探针存档（只改 3 个 u32，不动 IPA、不动代码）：

```
quest 51  progress = [1]      → 游戏内显示 1/1
quest 13  progress = [2]      → 游戏内显示 2/3
quest 14  progress = [3]      → 游戏内显示 3/3
```

**写什么就读出什么，读档链路 100% 正常。**
故 `restoreQuestsFromSave` / `readUserData:` / `setCountCurrent:` 全部无罪。
断点**唯一**落在写入侧——即"游戏内计数 → 字典 `progress` → 落盘"中的某一环。

**结论 D（关键，写侧唯一的疑点）**
`addUserData:` 落盘时读的就是字典的 `progress`（2.7 节已逐条闭合），
故"磁盘 progress=0" ⇔ "保存那一刻字典里的 `progress` 就是 `@[@0…]`"。

而 `requirementUpdated:` 是**唯一**把 `countCurrent` 写进字典的代码（2.6 节）。
因此只剩两种可能，且二者都预测 0：

| | 成因 |
|---|---|
| **甲** | `requirementUpdated:` 从未被投递/执行（观察者链断） |
| **乙** | 执行了，但写入被丢弃（字典不可变 / 对象被后续拷贝替换） |

**下一个实验直接区分甲/乙**：探针存档仍保留 `[2]/[3]/[1]`，
让游戏**正常退出**（触发它自己的保存）后读盘——
若变回 0 → 乙（写侧覆盖）；若仍为 2 → 甲（根本没写）。

**结论 F（决定性，探针实验；字节级）**
probe4 探针（8 条非零，值都远小于 countTotal）→ 用户**只读档、不做任何操作**、正常退出 →
把 `_probe4.py` 的写入在 `pre4` 备份上重放，得到"游戏运行前"的确切字节，
与"游戏退出后"的存档逐字节对比：

```
探针写出 vs 游戏回写：共 70 段差异、143 字节，全部落在 0x006d..0x090d（actorList 等）
任务段 0x010c..0x022c   —— 零字节差异 ——
```

**8 条非零值原样保留。落盘路径 100% 无罪。**
对照 probe2/3（读档 → 锄地 ×2 + 入侵 ×1 → 退出）：**20 条全部归零**。
⇒ 清零由**游戏内动作**触发，且是**全局性**的（连没碰过的 quest 53 也从 `[1,1,0]` 变 `[0,0,0]`）。

**结论 G（精确完整 xref，字段级解码，不依赖会丢站点的寄存器跟踪）**
`tools/annot_disasm.py` 的插桩式跟踪只能解析出 144 个站点，严重漏项
（真实二进制应有数万）。改用**字段级 ARM 解码**（literal 池里存的是 delta，不是绝对地址）
后得到完整调用点：

| 选择子 | 调用点 |
|---|---|
| `clearQuests` | **仅** `ZFFarmGameScene -switchMaps:`（`0x004534`）——入侵 / 换地图 / 回家 |
| `setCurrentQuests:` | **仅** `GameData -copyWithZone:`（`0x184478`）——即保存时的 `Setting a new GameData` |
| `stopListening` | **仅** `ZFQuestMan -cleanupQuest:`（`0x16bad8`） |
| `startListening` | `addQuestWithID:`（`0x16c750`）、`restoreQuestsFromSave`（`0x16dcec`）、`ZFGuiLayer -showPromotion:`（`0x25a668`） |
| `restoreQuestsFromSave` | **仅** `ZFGuiLayer -gamestart:`（`0x023088`） |
| `addQuestWithID:` | `ZFToolManager -popGameActionAndExecute:deltaTime:`（`0x0384c8`）、`ZFToolManager -harvestZombieWithUnitKey:onTile:`（`0x03ad80`）、`questTriggerCheckLevelUp`（`0x16d0f4`）、`questTriggerQuestCompleted:`（`0x16d2e8`）、`addSeasonalQuests`（`0x16d4a4`） |
| `currentQuests` | `requirementUpdated:`、`completeQuest:`×2、`addQuestWithID:`、`removeSeasonalQuests`、`restoreQuestsFromSave`×3、`readUserData:` |

关键结构：`clearQuests`（`0x16d9fc`）对 `questQueue`（ivar `+0xcc`）**取副本后逐条 `removeObject:` 并 `cleanupQuest:`**，
而 `cleanupQuest:`（`0x16bac4`）第一步就是 **`[quest stopListening]`** —— 注销该任务的全部通知观察者。
`clearQuests` **不触碰** `gameData.currentQuests`（存档源），但把 `questQueue` 清空。

`reorderQuests`（`0x16c9a0`）只做 UI 布局（`setPosition:` / `CCMoveTo` / `CCSequence`），
**不碰 currentQuests**，已排除。

**结论 H（全二进制中唯一三条能制造 `@[@0,@0,@0]` 的路径）**

| | 位置 | 触发条件 | ARM 站点 | Thumb 站点 |
|---|---|---|---|---|
| **A** | `ZFQuestMan -addQuestWithID:` | 新建任务字典时**硬编码** | `0x16c5b4/0x16c5d0/0x16c5e4` | `0x10b9c6/0x10b9de/0x10b9ec` |
| **B** | `ZFQuestNotification -requirementUpdated:` 零覆盖分支 | 匹配字典的 `progress` 为 nil 或空 | `0x16a8c8/0x16a8e4/0x16a8f8` | `0x10a3fe/0x10a410/0x10a41c` |
| **C** | `ZFQuestMan -restoreQuestsFromSave` 零覆盖分支 | 同上，对 `currentQuests` 每字典各一次 | `0x16e1a4/0x16e1c4/0x16e1d8` | `0x10cd18/0x10cd3e/0x10cd4a` |

**结论 I（判定实验已构建，等待一次游戏运行）**
`tools/patch_zfr_questdiag_v7.py` 生成 `...fixed-fonts-v7diag.ipa`：
把 A/B/C 的 `mov r2,#0` 分别改成 **7 / 8 / 9**（宽度不变、两 slice 同步、共 18 处）。
三条路径互斥可辨：

| 存档里的值 | 判定 |
|---|---|
| 7 | `addQuestWithID:` 重建了任务字典（A） |
| 8 | `requirementUpdated:` 走了零覆盖分支（B） |
| 9 | `restoreQuestsFromSave` 走了零覆盖分支（C） |
| 0（且条数/顺序不变） | A/B/C 都不是，字典在别处被清空 |
| 1..3 | 该条未被触碰 |

配套探针 `_probe7diag.py` 给每条 requirement 写入**严格小于 countTotal 的安全值**
（countTotal==1→0，==2→1，==3→2，≥4→3），既不会完成也不会被钳位，且与 7/8/9 不可能混淆。
读盘脚本 `_read7diag.py` 直接输出判定。

**结论 J（v7diag 判定实验：A/B/C 全部排除，出现反转）**
v7diag 运行结果（探针 17 条非零，值 1..3；用户锄地 4 片 + 入侵大树世界 1 次，正常退出）：

```
ID   countTotal   progress
1    [10,10]      [0,0]      ZEROED
6    [15]         [0]        ZEROED
...（共 17 条全部 0）
sentinelA(7)=0  sentinelB(8)=0  sentinelC(9)=0
```

**A、B、C 三条"构造 `@[@0,@0,@0]`"的路径一个都没触发，17 条值却全部归零。**

同时用 `_progress_writers.py`（权威反汇编器 `annotate()` 全量扫描两个 slice）
确认 CFSTR `"progress"`（`0x471af0`）在整个二进制中**只被 5 个函数引用**：

```
0x16a7fc/0x16a808/0x16a828/0x16a988/0x16ab80   ZFQuestNotification -requirementUpdated:
0x16c59c/0x16c618                              ZFQuestMan -addQuestWithID:
0x16ddfc/0x16de08/0x16de20/0x16de28            ZFQuestMan -restoreQuestsFromSave
0x186ca8/0x186cb0                              GameData -addUserData:          （读）
0x187c90/0x187c9c                              GameData +readUserData:...      （写）
```

⇒ 剩下两个**写普通 0、且不构造数组**的路径（因此 v7diag 抓不到）：

| | 位置 | 条件 | ARM | Thumb |
|---|---|---|---|---|
| **D** | `GameData -addUserData:` 越界/NSNull 兜底 | 字典 `progress` 数组比"重建 notification 的需求数"短 | `0x186ecc` | `0x11f53c` |
| **E** | `GameData +readUserData:...:` progress 补零 | 载荷里每条任务的需求数 < plist 需求数 | `0x187e34` | `0x120074` |

**E 尤其可疑**：`0x187d70` 是 `cmp r0,#1 / blt 0x187db0` ——
**若载荷读到的需求数为 0，整段逐值读取被跳过，数组完全靠 `numberWithInt:0` 补满**，
于是 `progress` 变成"长度正确但全 0"，`addUserData:` 再原样写盘 → 与观测完全一致。

`tools/patch_zfr_questdiag_v8.py` 生成 `...fixed-fonts-v8diag.ipa`：
A/B/C/D/E 分别打哨兵 **7/8/9/5/4**（22 处，宽度不变，两 slice 同步）。
读盘脚本 `_read8diag.py`。启动器已加**构建指纹** `zfr_last_launch.txt`
（记录实跑 IPA 名 + SHA256 + 时间），用于排除"跑错构建"。

**结论 K（已排除，本轮补齐）**
- `GameData -copyWithZone:`（`0x184410..0x18447c`）是**逐属性浅拷贝**：
  `setCurrentQuests:`（`0x184478`）直接传入源数组，无重建、无丢字段 —— **无罪**
- `ZFFarmGameScene -switchMaps:` → `clearQuests`（`0x004534`）只清 `questQueue`
  并 `cleanupQuest:`（`stopListening`），**不触碰 `currentQuests`** —— 无罪
- `removeSeasonalQuests` 仅 `cleanupQuest:` + `removeObject:`，不写零 —— 无罪
- `reorderQuests` 纯 UI 布局 —— 无罪

**结论 E（已排除）**
- 落盘路径确实被走到：`GameData -saveGameDataToBinaryFile:asFriend:`（`0x18dbe4`）
  在 `0x18ddf8` 发送 `addUserData:`，与日志 14 次 `******* SAVING *******` 吻合
- `GameData -currentQuests`（`0x18ef2c`）是**纯 getter**，直读 ivar `0x47fb60`(=+0x1c)，
  无拷贝；`GameState -zfGameData`（`0x2a7a0`）直读 ivar `0x47ec44`(=+0x04)。
  **HUD 与存档写的是同一个 `GameData` 实例，不存在对象分裂**
- 探针会话（log line 1103 起）**没有产生任何 SAVING 行** →
  用户上一次是强杀退出，游戏**根本没保存**，存档仍是探针写入的值

---

## 1. 存档格式（已解码并验证）

`saveGame.bin2` 为**大端**自定义二进制。任务段语法：

```
uint32  questCount
repeat questCount:
    uint32  ID
    uint32  requirementCount
    repeat requirementCount:
        uint32  progress      # 对应 ZFQuestRequirement.countCurrent
```

解析结果与 `Quests.plist` 的每条任务 requirement 数量完全吻合（51→1、53→3、13→1、28→3、46→3、33→2 …），格式确认无误。

---

## 2. 完整链路解码（ARM，sub6）

### 2.1 关键 ivar（从 `__objc_ivar` 列表读出，权威）

`ZFQuestNotification`（instance size 0x13f）：

| ivar | 偏移 |
|---|---|
| ID | **0x120** |
| requirements (`NSMutableArray`) | **0x128** |
| title | 0x124 |
| seasonal | 0x13c |

`ZFQuestRequirement`（instance size 0x20）：

| ivar | 偏移 | 类型 |
|---|---|---|
| type | 0x04 | i |
| notificationID | 0x08 | @"NSString" |
| notificationObject | 0x0c | @ |
| **countCurrent** | **0x10** | i |
| **countTotal** | **0x14** | i |
| text | 0x18 | @"NSString" |
| spriteFilename | 0x1c | @"NSString" |

### 2.2 建立任务：`ZFQuestMan -addQuestWithID:`（0x16c328）

```
0x16c394  [[ZFQuestNotification alloc] initWithID:questID loadSprite:YES]   → 通知对象
0x16c3b8  [GameState gameState].zfGameData
0x16c3d0  hasQuestBeenCompleted: / 0x16c3e8 removeQuest / 0x16c40c level / 0x16c420 levelRequired
0x16c44c  hasQuestBeenCompleted:(prerequisiteQuest)
0x16c4a8  遍历 questArray 查重（同 ID 则 0x16c77c 返回）
0x16c54c  [NSMutableDictionary alloc] init]
0x16c584  numberWithInt: questID
0x16c5a8  setObject:questID forKey:@"ID"
0x16c5c0  numberWithInt: 0            ┐
0x16c5d4  numberWithInt: 0            ├── 硬编码三个 0
0x16c5e8  numberWithInt: 0            ┘
0x16c608  [NSArray arrayWithObjects: 0,0,0, nil]      <- 不可变数组
0x16c624  setObject:<该数组> forKey:@"progress"
0x16c650  [gameData.currentQuests addObject:<该字典>]
0x16c6d8  [questArray insertObject:notification atIndex:0]   （seasonal）
0x16c6ec  [questArray addObject:notification]                （普通）
0x16c758  [notification startListening]
```

**`progress` 初始恒为 `@[@0,@0,@0]`（三个常量 0），与 requirement 对象无关。**

### 2.3 注册观察者：`ZFQuestNotification -initWithID:loadSprite:`（0x169664）

- 0x1696f8–0x169720：`[NSArray arrayWithContentsOfFile:<bundle>/Quests.plist]`
- 0x169758：`objectAtIndex:questID` → 任务字典
- 0x169770：`self.ID = questID`（写入 ivar 0x120）✔
- 0x1699c0：`[questDict objectForKey:@"requirements"]`
- 0x169b6c–0x169bxx：逐条 `[[ZFQuestRequirement alloc] init]`，从 plist 填
  `setType:` / `setNotificationID:` / `setNotificationObject:` / `setCountTotal:` / `setText:` / `setSpriteFilename:`，
  然后 `addObject:` 进 `self.requirements`（ivar 0x128）
  ⚠️ **plist 无 `countCurrent` 键，故 countCurrent 恒从 0 起**
- 0x169d8c：`addObserver:self selector:@selector(requirementComplete) name:@"kRequirementComplete" object:nil`
- 0x169db8：`addObserver:self selector:@selector(requirementUpdated) name:@"kRequirementUpdated" object:nil`
  （`strd sl, fp, [sp]`，`fp=0` → object 参数确为 nil）

### 2.4 增量：`ZFQuestRequirement -incrementCount:`（0x169018）

按 `type`（ivar 0x04）分派：

- **type == 2**（入侵类任务走这条）：0x1691b0 `[userInfo isEqualToString:notificationObject]`
  → 成功则 0x16927c 取 countCurrent 偏移，0x169284 `add r1,r1,#1`，0x169288 `str r1,[r4,r1]` **写回 countCurrent**
- type == 0 / 1：按 `userInfo` 的 isKindOfClass: + intValue 累加

收尾：
```
0x16929c  countTotal (0x14)
0x1692a4  cmp countCurrent, countTotal
0x1692a8  strge countTotal -> countCurrent        # 封顶
0x1692d0  [defaultCenter postNotificationName:@"kRequirementUpdated" object:<requirement 自身>]
0x169320  countCurrent == countTotal 时再 post @"kRequirementComplete"
```

### 2.5 观察者派发：`ZFQuestNotification -startListening`（0x16a47c）

```
0x16a4c0  self.requirements (ivar 0x128)
0x16a4dc  countByEnumeratingWithState 遍历 requirements
0x16a568  r0 = requirement
0x16a56c  [requirement notificationID]
0x16a580  r0 = defaultCenter
0x16a584  r2 = requirement              # observer = requirement 自身
0x16a588  addObserver:<requirement> selector:@selector(incrementCount:) name:<notificationID> object:nil
```

即：遍历**需求对象**，各自监听自己 `notificationID` 的通知，收到就调 `incrementCount:`。

### 2.6 回写（唯一写进度的代码）：`ZFQuestNotification -requirementUpdated:`（0x16a718）

```
0x16a740  [GameState gameState]
0x16a770  zfGameData
0x16a778  currentQuests (ivar 0x1c)
0x16a79c  countByEnumeratingWithState         # 外层：遍历 currentQuests
   0x16a860  dict = currentQuests[i]
   0x16a874  [dict objectForKey:@"ID"]
   0x16a87c  intValue
   0x16a888  self.ID (ivar 0x120)
   0x16a88c  cmp / bne 0x16a930              # ID 不等 → 下一个
   0x16a8a4  [dict objectForKey:@"progress"]
   0x16a8b4  [progress count]
   0x16a8bc  !=0 → 0x16a974                  # 非空 → 走真正回写
   0x16a974  [dict objectForKey:@"progress"]
   0x16a9a4  [NSMutableArray arrayWithArray:progress]
   0x16a9ac  sp+0x3c = 该可变数组
   0x16a9b4  [array count] → fp
   0x16a9e8  countByEnumeratingWithState     # 内层：遍历 self.requirements
      0x16aab4  [self.requirements indexOfObject:req] → idx
      0x16aabc  cmp idx, fp
      0x16aad4  [req countCurrent]
      0x16aaf8  [array replaceObjectAtIndex:idx withObject:@(countCurrent)]   # idx <  count
      0x16ab38  [array addObject:@(countCurrent)]                             # idx == count
   0x16ab8c  [dict setObject:<array> forKey:@"progress"]     # ← 唯一的进度持久化点
   0x16ab90  b 0x16a968 → 返回
```

`[sp,#0x3c]` 初值为 `objectForKey:` 选择子（0x16a7e4），在 0x16a9ac 被可变数组覆盖；
因命中后 0x16ab90 立即返回，不会二次进入外层循环，**此覆盖无害**。

### 2.7 存档写入：`GameData -addUserData:`

**本方法已逐条闭合，结论：它读的就是字典的 `progress` 数组。**（上一版曾标为"存疑"，本轮已定论）

```
0x186ba8  清零枚举状态
0x186bd4  遍历 gameData.currentQuests            # 外层
0x186d00  [questDict objectForKey:@"ID"]
0x186d08  ... unsignedIntValue                   → questID
0x186d30  [ZFQuestNotification alloc]
0x186d3c  [notification initWithID:questID]      # 重建，仅用于取 requirements 的下标
0x186d44  [notification autorelease]
0x186d64  [questDict objectForKey:@"progress"]   ← 键来自 CFSTR 0x471af0
0x186d74  [NSMutableArray arrayWithArray:progress]   → sl = 进度数组
0x186d90  [[notification requirements] count]
0x186da0  [archiver addUnsignedInt:reqCount]      # 写"需求条数"
0x186df0  遍历 [notification requirements]        # 内层
0x186e3c  [[notification requirements] ...]
0x186e48  indexOfObject:req                       → idx
0x186e58  [sl count]                              # 越界检查
0x186e60  idx >= count → 0x186ec4                 # 写 0
0x186e70  [sl objectAtIndex:idx]
0x186e9c  isKindOfClass:（NSNull 判定）
0x186ea4  是 NSNull → 0x186ec4                    # 写 0
0x186eb0  unsignedIntValue
0x186ed0  [archiver addUnsignedInt:value]         ← 落盘的真实取值
0x186ec4  （兜底分支）r2 = 0 → 0x186ed0
```

即在 `sl`（字典 `progress` 的可变副本）上按下标取值写盘。
**故"磁盘上 progress = 0" ⇔ "保存那一刻字典里的 `progress` 就是 `@[@0]`"。**

同时确认：`CFSTR "progress"`（0x471af0）在 `addUserData:` 内只被引用一次（0x186cb0），
另一处 0x187c9c 属 `readUserData:`（方法边界 0x18655c..0x1872b4 / 0x1872b4..0x188158）。

### 2.8 存档读取：`ZFQuestMan -restoreQuestsFromSave`（0x16db7c）

```
0x16dbc4  [GameState gameState].zfGameData.currentQuests
0x16dc5c  countByEnumeratingWithState
0x16dc7c  setCountCurrent:            # 选择子
0x16dcac  requirements                # 选择子
0x16dcf4  countCurrent                # 选择子
0x16dcd4  countTotal                  # 选择子
0x16ddfc  CFSTR "ID"
0x16de08  CFSTR "progress"   ×3 处
0x16ddc0  [[ZFQuestNotification alloc] initWithID:loadSprite:]
0x16e084  [req countTotal]
0x16e098  越界则钳到 countTotal
```

读取侧键名 `ID` / `progress` 与写入侧、2.6 节回写侧**完全一致**。

---

## 3. 断点定位

链路上唯一"设计上应该发生、实际没发生"的一步是 **2.6 的 `requirementUpdated:` 回写**。
其前置条件（2.5 注册、2.4 投递）逐条指令核对均正确：

| 环节 | 状态 |
|---|---|
| `incrementCount:` 写 countCurrent (0x10) | ✔ 指令正确 |
| `incrementCount:` 投递 `kRequirementUpdated`，object = requirement | ✔ 0x1692d0 |
| `initWithID:loadSprite:` 注册 `kRequirementUpdated`，object = nil | ✔ 0x169db8，同一 CFSTR 0x4719d0 |
| `requirementUpdated:` ID 比对（dict"ID" vs ivar 0x120） | ✔ 0x16a88c |
| `requirementUpdated:` 回写 dict"progress" | ✔ 0x16ab8c |
| `addUserData:` 落盘 | 存疑（见 2.7 注） |
| `restoreQuestsFromSave` 读回 | ✔ 键名一致 |

即：**静态代码看不出缺陷，但实测进度恒为 0。**
因此图3 的成因只可能是下列二者之一：

- **(甲)** 运行时 `requirementUpdated:` 从未被投递/执行（观察者未生效或通知中心未派发）；
- **(乙)** `addUserData:` 落盘时并未采用字典 `progress`，而是采用了按 ID 重建的通知对象里恒为 0 的 `countCurrent`。

区分甲/乙只需一次实验（见第 4 节）。

---

## 4. 判定实验（一次游戏运行即可定论）

在 `ZFQuestMan -addQuestWithID:` 把 2.2 的三个 `numberWithInt:0` 改成非零哨兵（宽度不变）：

- ARM `0x16c5c0` / `0x16c5d4` / `0x16c5e8`：`mov r2, #0` (`0020a0e3`) → `mov r2, #5` (`0520a0e3`)
- Thumb 对应三处同样改

然后进游戏（**不要做入侵**）后退出，再解析 `saveGame.bin2`：

| 存档里 quest 13 的 progress | 判定 | 修法 |
|---|---|---|
| `5` | 落盘读字典 `progress`（乙排除）→ **甲成立**，问题在观察者派发 | 放弃该回写路径，改为在别处同步 |
| `0` | 落盘用的是重建对象的 countCurrent → **乙成立** | 让 `addUserData:` 取字典 `progress` |
| `1`（做过一次入侵后） | 链路其实是通的，问题只在别处 | 重新评估 |

该哨兵补丁**宽度不变、可逆**，不影响其它任何逻辑。

---

## 5. 附：与图2 的关系

图2（入侵成功弹窗技能名仍英文，如 `ZomBumpkin`）与本问题**同源不同点**：
`ZFFightMan -getRandomAbilityToUnlock`（ARM 0xb70f8，站点 0xb73a8）直接返回内部
actor 子类型名 `__cstring` 字面量，调用方（0xb7530）用
`localizedStringForKey:@"Unlocked a new %@ ability!"` + `stringWithFormat:` 拼装，
**该内部名从未过本地化**。`zh-Hans Localizable.strings` 里其实已有
`'ZomBumpkin' = '南瓜头僵尸'`，只是代码不查它。
需注入中文串到 `__text` 空洞（`__cstring` 前面 0 gap），与图3 互不影响。

---

## 6. 本次分析用到的工具与产物

- 方法归属：`tools/inspect_v3_facts.py` 的 `classes_by_name()` + `all_methods()`
  （**注意：`sl.methods` 不完整，会把站点归属错方法**，本次已因此踩坑一次：
  `0x16e8ac` 曾被误归到 `ZFQuestMan -setQuestArray:`，实为
  `ZFAlertWindowQuest -initWithQuest:`）
- 反汇编：`tools/annot_disasm.py meth <Class> <sel> --sub 6|9` / `at <addr> <len>`
- ivar：`tools/dump_ivars.py` + `class_info()` + `dump_ivars()`
- 存档：按第 1 节语法手工解析
