# ZFR「施肥僵尸」机制取证 —— 往地块上放僵尸为什么也飘「 %@施肥啦！」

日期：2026-09-20
被分析的二进制：`zombie_farm/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa`
大小 **59,564,493 字节**，sha256 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`
代码阅读用 **sub9（Thumb）**，下文所有地址除非注明都是 **sub9**。

**本次为纯静态分析，没有运行游戏，没有修改任何文件。**

> **⚠️ 本报告 §2.1 有一处已被订正的错误推断**（"飘字读的是 `Localizable.strings`"）。
> 真实情况是读 `Arial-BoldMT.strings`，**v29fix 改对了文件**。
> 订正见 `_analysis/reports/ZFR_施肥飘字_表来源订正.md`。
> **§2.1 之后的结论不受影响。**

---

## 1. 结论

**既不是「被施肥的僵尸有特殊属性」，也不是「误把僵尸当成庄稼」的显示 bug。**
真相是第三条：
> **` %@施肥啦！` 是「园丁类僵尸**自动施肥**」事件的通知文本，它的触发点是「往地块上放东西」这条代码路径（种庄稼和放僵尸共用），
> 而 `%@` 是**施肥的那只僵尸的名字**，不是被施肥的对象。**

所以：

1. **飘字出现在放僵尸时，是设计行为，不是 bug。** 代码路径 `ZFToolManager -popGameActionAndExecute:deltaTime:` 的 `command == 3` 分支（「在地块上放置单位」）**同时**处理种植物和放僵尸 —— 这是**逐字节验证**的（见 §2.1、§2.2）。
2. **但施肥本身不是无条件的**：它是一次**按概率的掷骰**，概率来自**刚放下的那只园丁僵尸**在 `UnitStats.plist` 里的 `fertilizeChance`（4% ~ 12%）。**逐字节验证**（见 §2.4）。
3. **被施肥的僵尸/地块确实有实际效果**，但**不是生长加速**：
   - 地块获得 `SaveTile.fertilized = 1`（存档持久化）；
   - 地块上出现 `CCParticleFlower` 绿色粒子；
   - **收获时结算额外的「化肥奖励」金币**并飘 `+%i金币(化肥作用)` / `+%i金币(化肥奖励)`。
   见 §3。

**置信度：高（机制链条）。** 代码路径、条件、概率来源、`%@` 的取值来源全部逐字节对上；
唯一**没有**做到的是「在游戏里真的看到这条飘字」（那要由主人实测），以及收获奖励在**僵尸**地块上的最终数值（见 §5）。

---

## 2. 证据链

### 2.1 这条飘字全库只有**一个**生产点

`Fertilized by %@!` 这个 CFString 在 sub9 是 `@0x3a4d40`（字符串数据 `@0x2faac4`，`size=17`）。
用 `_analysis/_v17_cf.py` 做全 `__text` 的寄存器值追踪，**sub9 只有一处**把它装进寄存器：

```
0x0002a0ba  movw  r1, #0x997a ; movt r1, #0x36 ; add r1, pc
0x0002a0d6  ldr   r1, [r1]   → SEL localizedStringForKey:value:table:
0x0002a0c2  movw  r2, #0xac6c ; movt r2, #0x37 ; add r2, pc
0x0002a0d0  add   r2, pc     → CFSTR @0x3a4d40 'Fertilized by %@!'
0x0002a0d2  movt  r3, #0x37 ; 0x0002a0d8 add r3, pc
             → CFSTR @0x3a3310 = ''   ← ★ 空串，即**默认表 Localizable.strings**
0x0002a0dc  blx   #0x2d014c   → objc_msgSend
0x0002a0e0  ldr   r1, [sp, #0x68]  ; = SEL stringWithFormat:（0x29600 写入）
0x0002a0e2  mov   r2, r0            ; 模板
0x0002a0e4  mov   r0, r5            ; theMarket
0x0002a0e6  mov   r3, r4            ; ★ 名字
0x0002a0e8  blx   #0x2d014c   → objc_msgSend  [theMarket stringWithFormat:模板, 名字]
```

> **⚠️ 订正（2026-09-20，见 `ZFR_施肥飘字_表来源订正.md`）：下面这段"表名是空串 →
> 读默认表 `Localizable.strings` → v29fix 改错了文件"的推断是【错误】的，已作废。**
>
> **真实情况：这条飘字读的就是 `Arial-BoldMT.strings`，v29fix 改对了文件。**
>
> 出错原因是本报告的一个**工具级 bug**：本 slice 的**虚拟地址与文件偏移差 0x1000**
> （`addr_to_file(0x3a4d40) == 0x3a3d40`），而这里直接用 `data[va:va+n]` 读，
> 于是整体偏到隔壁数据，把一个真实字符串看成了空串。
> 另外 ABI 也记错了：`localizedStringForKey:value:table:` 是
> **`r0=self r1=_cmd r2=key r3=value [sp]=table`**，这里把 `r3`（value）当成了 table。
>
> 三条独立证据（历史/段扫描/反汇编相位）都指向 `Arial-BoldMT.strings`，
> 详见订正报告。**本报告 §2.1 之后的全部结论不受影响**（施肥触发路径、概率来源、
> `%@` 是施肥者名字、`fertilized` 的效果等，用的都是正确的地址解析）。
>
> 以下是原文，保留以便对照：

> **重要修正（对 v29fix 的影响）**：`table:` 参数解析出来是 CFString `@0x3a3310`，其内容为**空串 `""`**（`flags=0x7c8, data=0x334ef8, len=0`）。
> 空 table 名 = **默认表**，即 `zh-Hans.lproj/Localizable.strings`，
> **不是** `Arial-BoldMT.strings`。
> 也就是说这条飘字实际读的是 `Localizable.strings` 里的 `Fertilized by %@!` = ` %@施肥了`；
> v29fix 改的那两个 `Arial-BoldMT.strings` 成员**不是**这条飘字的来源（它们是给 `labelWithString:fontName:fontSize:` 用的字体名映射表）。
> **逐字节验证**（`_analysis/_zfz_table_arg.py` 的 table 参数普查 + 直接解 CFString）。
> 这一点与 `TECHNICAL.md` 5.12 / `ZFR_v29fix_施肥飘字还原.md` 的表述**不一致**，见 §5.6。

（sub6 对应站点在 `0x37fec`，同一方法。）
两处都归属 `ZFToolManager -popGameActionAndExecute:deltaTime:`，`imp=0x27939`，方法体 **`0x27938..0x2a64c`（4015 条指令）**。

紧接着飘出去：

```
0x0002a104..0x0002a12c   [gui displayMessage:onTile:withColor:withDelay:]
                         color = *(0x342be0) = 0x3accff，delay = 0x19 (25)
0x0002a144/0x0002a146    [tile setFertilized:1]      ← 落旗
0x0002a17c               [tileManager fertilizeTile: action.tile]  ← 生成粒子
```

**逐字节验证。**

### 2.2 它是从「放置单位」这条命令路径进来的（**放僵尸和种庄稼共用**）

方法开头是标准的游戏动作出队：

```
0x00027a88  ldr  r4, [sp, #0x84]        ; r4 = action (ZFGameAction)
0x00027a8c  ldr  r1, [r0]   SEL command
0x00027a90  blx  objc_msgSend           ; r0 = [action command]
0x00027a94  cmp  r0, #3
0x00027a96  beq.w  #0x29498             ; ★ command 3 → 本问的「放置」分支
0x00027a9a  cmp  r0, #2
0x00027a9c  beq.w  #0x27e92             ; command 2 → 收获/结算分支
0x00027aa0  cmp  r0, #1
0x00027aa2  bne.w  #0x2a5ac             ; 其它 → handleFailureInMethod:…'popGameAction:unknown command'
```

谁 push 这三个 command（`ZFToolManager -onTileClickUp:forTool:` 里的三处 `pushGameAction:onTile:withRect:withItem:`，全库仅此三处）：

| 站点 | command | 上下文（**逐字节验证**） |
|---|---|---|
| `0x22a08` | **2** | 前置 `0x22964 [self isTileHarvestable:]`、`0x22926 CFSTR 'alternateTile'` → **收获** |
| `0x23fca` | **1** | 前置 `0x27bba CFSTR 'soil_plowed'`、`0x27bf4 [tile label]` → **耕地** |
| `0x26932` | **3** | 前置 `0x2687a [self isTilePlantable:]`、`0x268da [self selectorRectFromTile:]` → **放置** |

`command == 3` 分支（`0x29498`）读的是 **`action.item` 这个市场条目的字典**：

```
0x000294a2  ldr  r5, [r0]   SEL item
0x000294a8  blx  objc_msgSend            ; [action item]
0x000294be  add  r2, pc     CFSTR 'name'          → sp+0x7c
0x000294dc  add  r2, pc     CFSTR 'subCategory'
0x000294f4  add  r2, pc     CFSTR 'zombie'
0x000294fc  blx  objc_msgSend            ; [subCategory isEqualToString:@"zombie"]
0x00029506  bne  #0x29538                ; ★ 僵尸走这条
0x00029520  add  r2, pc     CFSTR 'special'       ; 非僵尸再查 'special'
```

**这就是关键：`command 3` 里明确存在 `subCategory == "zombie"` 的判断**，也就是说这条路径**本来就要处理僵尸**。

### 2.3 两条路径在 `0x29538` 汇合，一起走到飘字

`0x29538` 起是**种/放通用**的落地流程（**逐字节验证**）：

```
0x000295c8..0x000295e4  stringByReplacingOccurrencesOfString:@" "→@"_"
                        + lowercaseString                 ; "Garden Zombie" → "garden_zombie"
0x0002960c  CFSTR 'soil_seeded_%@'   + stringWithFormat:  ; → "soil_seeded_garden_zombie"
0x00029664  [tileManager replaceTile:withGIDkey:considerNeighbouringTiles:]
0x000296a6  [TSprite findByCoordinates:]
0x00029706/0x00029732  setDate: / setPlantDate:
0x0002974c  [tileManager tilePropertiesDictionary]
0x0002976c/0x0002976e  CFSTR 'transformsTo' / CFSTR 'movable'   ; 沿变换链走
0x00029804  [actorManager …]  0x00029814 [actorManager actorList]
0x00029830  countByEnumeratingWithState:objects:count:          ; ★ 遍历 actorList
```

遍历体（**逐字节验证**）：

```
0x0002988e  ldr.w  r6, [r0, r5, lsl #2]        ; r6 = actor
0x0002989c  ldr    r0, [r0]  → 0x399fac        ; classref = ZombieActorGarden
0x000298a0  blx    objc_msgSend                 ; [ZombieActorGarden class]
0x000298aa  blx    objc_msgSend                 ; [actor isKindOfClass:…]
0x000298b2  beq    #0x29908                    ; 不是园丁类 → 下一个 actor
0x000298b8  blx    objc_msgSend                 ; [actor unitDictionary]
0x000298c6  add    r2, pc   CFSTR 'fertilizeChance'
0x000298c8  blx    objc_msgSend                 ; [unitDict objectForKey:@"fertilizeChance"]
0x000298ce  blx    objc_msgSend                 ; [… floatValue]  → fp
0x000298d4  blx    #0x2cf9e4                    ; ★ _arc4random
0x000298d8..0x000298e8  umull/lsr/mls          ; r0 = arc4random() % 100
0x000298f4  vdiv.f32 s0, s0, s20               ; s20 = 100.0（字面量池 0x29be8 = 0000c842）
0x000298fc  vcmpe.f32 s0, s1                   ; s1 = fertilizeChance
0x00029904  bls.w  #0x29b2e                    ; ★ 掷中 → 施肥块
```

`0x2cf9e4` 的桩已解析为 `__la_symbol_ptr[128] = '_arc4random'`（`_analysis/_zfz_stub2.py`）。**逐字节验证。**

### 2.4 概率数值来自 `UnitStats.plist`（数据侧佐证）

`Payload/ZFR.app/UnitStats.plist` 里**只有园丁系僵尸**带 `fertilizeChance`：

| unitKey | fertilizeChance | tier |
|---|---|---|
| `ZombieActorGardenTier1`（Garden Zombie / 园丁僵尸） | **0.04** | 1 |
| `ZombieActorGardenTier2`（ZomBotanist / 生态僵尸） | **0.06** | 2 |
| `ZombieActorGardenTier3` / `Tier3GreenFlower`（Flower Zombie / 花花僵尸） | **0.08** | 3 |
| `ZombieActorGardenTier4`（Zombee / 蜜蜂僵尸） | **0.08** | 4 |
| `ZombieActorGardenTier5`（Zombutterfly / 蝴蝶僵尸） | **0.08** | 5 |
| `ZombieActorGardenCupid` / `CupidPink`（Cupid Zombie / 丘比特僵尸） | **0.12** | 0 |

全表 70 个条目里**没有第二个键名**包含 `fertilizeChance`。
`Market.plist` 里这些条目的 `info` 就是 `Fertilizes` / `Fertilizes+` / `Fertilizes++`，
本地化（`zh-Hans/Localizable.strings`）为 `施肥` / `施肥+` / `施肥++`。**逐字节验证。**

### 2.5 `%@` 到底是什么 —— **施肥那只僵尸的名字**

```
0x0002a070  ldr  r1, [sp, #0xa0]
0x0002a072  mov  r0, sl
0x0002a074  blx  objc_msgSend            ; [action item]
0x0002a078  blx  #0x2cf9e4               ; ★ _NSStringFromClass
0x0002a07c  mov  r2, r0
0x0002a088  ldr  r1, [r0]  SEL nameFromUnitKey:
0x0002a08a  ldr  r0, [sp, #0x6c]         ; = theMarket（ZFMarketMenu）
0x0002a08c  blx  objc_msgSend            ; [theMarket nameFromUnitKey:…]
0x0002a094  mov  r4, r0                  ; ★ r4 = 本地化名字
…
0x0002a0e6  mov  r3, r4                  ; ★ %@ 参数 = r4
0x0002a0e8  blx  objc_msgSend            ; [NSString stringWithFormat:…]
```

`ZFMarketMenu -nameFromUnitKey:`（`imp=0x5335d`）实现是
`[[self marketItemFromUnitKey:key] objectForKey:@"name"]`（`0x5336a`/`0x5338a`），
而 `name` 正是市场条目名 —— `"Garden Zombie"` → zh-Hans `园丁僵尸`。

**所以这句飘字的字面意思是「园丁僵尸施肥啦！」，`%@` 是施肥者，不是被施肥者。**
中文读起来像「僵尸被施肥了」，是**文案主语歧义**，不是逻辑错误。**逐字节验证。**

### 2.6 触发条件（完整）

`0x29b2e` 起的施肥块：

```
0x00029b38  ldr  r1, [r0]  SEL brainState
0x00029b3c  blx  objc_msgSend            ; [actor brainState]   (r6 = 该 actor)
0x00029b44  cmp  r0, #2
0x00029b4c  bne  #0x29bd6                ; 不在僵尸地里 → 跳过驱逐
```

`brainState == 2` 由 `ZFZombiePatch -addInhabitant:` 设置（`0x5b8ac MSG setBrainState:(0x2,…)`）。
**即：那只园丁僵尸必须正待在僵尸地里**（刚放下的那只正好满足）。

**逐字节验证。**

### 2.7 真·施肥动作与视觉

```
0x0003cf88  [SaveTile setFertilized:1]                ; ZFTileManager -fertilizeTile: (imp 0x3cf49)
0x0003cff2..0x3d224  CCParticleFlower（classref 0x399fec），
                     setPosition: 精灵位置 + (20, 50)，
                     addChild:z: 到精灵的 parent、zOrder+1，
                     [tSprite setEmmiter:…]
0x0003d26e  [SaveTile setFertilized:0]                ; ZFTileManager -unFertilizeTile: (imp 0x3d235)
```

**逐字节验证。**

---

## 3. 被施肥的地块/僵尸到底有什么特性

### 3.1 数据模型：`fertilized` 是 `SaveTile` 的字段，**植物和僵尸共用同一个模型**

`SaveTile`（sub9 `cls=0x39b228`，`instance_size=60`）的 ivar 布局（**逐字节验证**）：

```
+0x010 key           NSString
+0x014 endCropTile   NSString
+0x01c fertilized    c   ← 施肥旗标
+0x01d isZombie      c
+0x01e isPlant       c
+0x01f isHarvestable c
+0x024 growTime      d
```

**关键发现：`fertilized` / `isZombie` / `isPlant` 是同一层级的三个并列布尔。**
也就是说**僵尸在地块上就是一个「作物对象」**，`isZombie=1`、`isPlant=0`，
它和植物**共享** `key` / `endCropTile` / `growTime` / `fertilized` 这一整套字段。

数据侧完全吻合：`Market.plist` 里园丁僵尸的 `category` 就是 **`'crop'`**，`subCategory` 是 `'zombie'`，
`growTime` 86400 —— 和胡萝卜之类的植物同一套结构，只是 `subCategory` 不同。
`TileProperties.plist` 里僵尸也走同一条链：

```
soil_seeded_garden_zombie → soil_germinating_garden_zombie
  → soil_seedling_garden_zombie → soil_harvestable_garden_zombie → soil_withered_zombie
```

（植物是 `soil_seeded_carrots → soil_seedling_carrots → soil_harvestable_carrots → soil_withered_plant`。）
**逐字节验证。**

→ **所以「僵尸能被施肥」在数据模型上根本不是异常：僵尸就是种在地里的作物。**

### 3.2 持久化

`SaveTile -encodeWithCoder:`（`imp=0x5a3dd`）：

```
0x0005a530  ldrsb  r2, [r5, r0]   ; r0 = ivar 偏移 0x1c = fertilized
0x0005a53c  blx  objc_msgSend     ; [coder encodeBool:r2 forKey:@"fertilized"]
```

回读在 `GameData +readFarmData:intoGameData:withVersion:`（`0x121bac`）。
**逐字节验证。** → 施肥状态**存档持久**，不是临时特效。

### 3.3 效果一：收获时的「化肥」金币奖励

收获分支（`command == 2`，`0x27e92` 起）里有**两处**读 `[tile fertilized]`：

```
0x00027ff4  [tile fertilized]          ; r5 = 结果
0x00028464  tst.w  r0, #0xff
0x00028468  beq    #0x2853a            ; 没施肥 → 跳过
0x000284aa  add    r2, pc  CFSTR '+%ig (Fertilizer)'
0x000284b6  [localizedStringForKey:value:table:]
0x00028574  [NSString stringWithFormat:]        ; → "+200金币(化肥作用)"
```

```
0x00028a90  [tile fertilized]
0x00028a98  beq.w  #0x28c34            ; 没施肥 → 跳过
0x00028ab8  [theMarket costFromName:…]
0x00028ad6  [zfGameData addResource:… amount:cost]
0x00028b1c  add    r2, pc  CFSTR '+%ig (Fertilizer Bonus)'
0x00028b80  [gui displayMessage:onTile:withColor:withDelay:]   ; → "+200金币(化肥奖励)"
```

这两条 key 在 zh-Hans 里就是 `'+%i金币(化肥作用)'` / `'+%i金币(化肥奖励)'`
（`process.md` 记录的 v15fix 修的正是它们）。**逐字节验证。**

### 3.4 效果二：**不影响生长速度**

`fertilized` 在全 sub9 的**读取点只有 6 处**（`_analysis/_zfz_sel_sites.py` 全 `__text` 扫描）：

```
0x00027ff4  ZFToolManager -popGameActionAndExecute:deltaTime:   ← 收获 UI
0x00028a90  同上                                                ← 收获金币奖励
0x000291da  同上                                                ← 收获金币奖励（另一条）
0x0003c8aa  ZFTileManager -graduateSoilTileWithTSprite:         ← 阶段推进时继承/清除
0x0005a92c/0x0005a940  SaveTile -copyWithZone:                  ← 拷贝
0x00121bac  GameData +readFarmData:…                            ← 读档
```

**没有任何一处进入生长时间/`growTime` 计算。**
`graduateSoilTileWithTSprite:`（`imp=0x3c529`）里算阶段时长用的是
`d8 = isPlant ? 2.0 : (isZombie ? 3.0 : 1.0)`（字面量池 `0x3ca08` = f64 3.0、`0x3ca10` = f64 1.0）
再除以 `zfGameData.growSpeed` —— **输入里没有 `fertilized`**。

阶段推进时的旗标继承逻辑（`0x3c9a2..0x3c9c6`）：

```
fp = [旧tile fertilized] && ![旧tileProperties canHarvest]
if (fp)  [self fertilizeTile:新坐标]     ; 0x3c9b0 → selref 0x394594 = 'fertilizeTile:'
else     [self unFertilizeTile:新坐标]   ; 0x3c9bc → selref 0x39467c = 'unFertilizeTile:'
```

即：**施肥状态随生长阶段一路继承，直到地块进入可收获阶段之后（旧阶段 `canHarvest=1`）才清除。**
（`TileProperties.plist` 里 `soil_seeded_*` / `soil_germinating_*` / `soil_seedling_*` **都没有** `canHarvest` 键，
只有 `soil_harvestable_*` 有且为 `True` —— 65 条。）**逐字节验证。**

→ **结论：施肥给的是「收获时多给钱 + 粒子特效」，不是「长得快」。**
这纠正了 §1 里我列的候选假设之一。

---

## 4. 那这算 bug 吗？

**分三层看（这部分含推断）：**

1. **「放僵尸也会飘施肥字」—— 不是 bug，是设计。** 【推断，但依据充分】
   路径共用（§2.2）、僵尸明确被判定（§2.2 的 `'zombie'` 检查）、
   概率表里**只有园丁系僵尸**有 `fertilizeChance`（§2.4）、
   飘字内容取自**施肥者**的名字（§2.5）—— 这四点合起来只能解释成
   「你放下的园丁僵尸按概率给这块地施了肥」。

2. **文案有主语歧义 —— 这是真正值得改的地方。** 【推断】
   中文 ` %@施肥啦！` 里的 `%@` 是**施动者**（园丁僵尸），但中文语序读起来像**受动者**（僵尸被施肥了）。
   英文原键 `Fertilized by %@!` 没有这个歧义（`by` 明确标出施动者），
   日文 `%@が施肥済みです！` 也没有。
   如果主人想消除歧义，**只改 `Arial-BoldMT.strings` 的值**即可（纯数据改动，不碰可执行文件），
   例如 `%@施肥啦！` → `%@给这块地施肥啦！`。
   **注意槽位限制**：这两个成员现在是 189 字节 DEFLATE 槽位、当前值占 186 字节（余 3），
   见 `TECHNICAL.md` 5.12 / `_analysis/reports/ZFR_v29fix_施肥飘字还原.md`。
   要加字必须先按该文档的办法重算压缩后大小，装不下就得回到「换序列化格式」或
   「接受缩短」的二选一。**本次未做任何改动，也不建议在没重算槽位前动它。**

3. **代码层面唯一可议之处**：施肥掷骰的循环遍历的是**整个 `actorManager.actorList`**，
   对**每一只**满足条件的园丁僵尸都掷一次骰，**掷中即 `break`（跳出循环）**。
   也就是说：**如果你养了多只园丁僵尸，每次种植/放置的施肥概率是叠加的**
   （第一只不中就试第二只……）。
   这在「一次种植」的语义下是合理的（"你的园丁们谁来帮忙"），
   但和 UI 上「某一只僵尸施肥了」的呈现方式配合起来，会让人以为是那只僵尸的固有属性。
   **这属于设计取舍，不是缺陷。** 【推断；`0x29838 beq` 跳出 / `0x2990e` 外层迭代已逐字节验证】

---

## 5. 遗留问题 / 没能查清的部分

1. **未做游戏内实测。** 上面全部是静态分析 + 数据文件比对。
   「放僵尸时真的会飘出 ` %@施肥啦！`」这一步**由主人验证**。
   建议实测口径：放一只**园丁僵尸**（Garden Zombie，`fertilizeChance=0.04`）到**已耕好的空地**，
   重复多次（4% 概率，约 25 次一遇；丘比特僵尸 12% 更快）。
   若放**非园丁**僵尸（如普通 Regular 僵尸）也稳定飘字，那才说明我的路径判定有误，请回报。

2. ~~**收获奖励的具体数值没算出来。**~~ **已由后续一轮查清，见
   `_analysis/reports/ZFR_施肥僵尸_收益效果.md`。** 摘要：奖励块 `0x28a9c`
   的唯一守卫是 `[tile fertilized]`，金额是**再发一份** `[theMarket costFromName:]`
   的结果（即"双倍金币"），而且**收获路径里没有任何 plant/zombie 判别** ——
   所以**被施肥的僵尸地块和作物拿到一模一样的奖励**。
   原本的线索保留如下：
   - 走的是 `[theMarket costFromName:…]` + `[zfGameData addResource:… amount:…]`；
   - 还有一条 `headID == 0xe (14)` 或 `headID == 0xc (12)` 时 `amount += amount * 0.1` 的加成（`0x28426`/`0x28438`，字面量池 `0x285d4` = f32 0.1）；
   - **`costFromName:` 的返回值是否恒等于 `Market.plist` 的 `cost` 字段，仍未定死**（`0x291da` 那条分支的系数依赖运行时状态）。这需要动态或实测。

3. **`sp+0x60` 那个标志没查清。** `0x29500`/`0x29536` 把
   `(subCategory=="zombie") || (subCategory=="special")` 存进 `sp+0x60`，
   后续用途未追到底。它**不影响**施肥飘字的结论（飘字块在 `0x2a0dc`，不读该槽位 —— 已用
   `_analysis/_zfz_slot2.py` 验证：从 `0x29538` 可达的写只有 `0x29540`，读只有 `0x29a22`）。

4. **`sp+0x6c`（theMarket）在 `command 3` 路径上没有写点 —— 这是个反直觉的发现，但已验证。**
   `_analysis/_zfz_slot2.py` 报告：从 `0x29498` 可达的 `sp+0x6c` 写点为 **0 个**，
   而 `0x2a08a` 读它当 `nameFromUnitKey:` 的接收者。
   静态上这意味着它沿用 `0x279dc`（方法入口）写的 `theMarket` 单例。
   由于 `theMarket` 是单例（`+[ZFMarketMenu theMarket]`），**推断**这里语义正确，
   但「没有写点」本身值得记录 —— 若将来做动态验证，这是第一个该看的槽位。

5. **`+%ig` 的 `%i` 在 v19 之后是否仍是 `%i`。** 本次只确认代码里引用的是 `'+%ig (Fertilizer)'`
   与 `'+%ig (Fertilizer Bonus)'`（CFString `@0x3a4b00` / `@0x3a4be0`），
   表里的值是 v15fix 修过的 `'+%i金币(化肥作用)'` / `'+%i金币(化肥奖励)'`，未复核压缩槽位。

---

## 附：本次新写的分析脚本（都在 `_analysis/`，未改动任何既有文件）

| 脚本 | 作用 |
|---|---|
| `_zfz_strings.py` | 导出 `.strings` 表 + 可执行文件里与 fertiliz/施肥/化肥 相关的 CFString |
| `_zfz_fertile_site.py` | 定位 `Fertilized by %@!` 站点 + 施肥系选择器全库调用点 |
| `_zfz_fertile_cfg.py` | 该站点的方法窗口 + 跳入该窗口的分支 |
| `_zfz_cfg.py` | 任意方法的**基本块 CFG + 反向切片** |
| `_zfz_reach.py` | 方法内**可达性**判定（`--from A --to B`） |
| `_zfz_path.py` | 方法内最短指令路径（把「怎么走到的」打出来） |
| `_zfz_slot.py` / `_zfz_slot2.py` | 栈槽读写点（后者只列**从某入口可达**的那些） |
| `_zfz_into.py` / `_zfz_escapes.py` | 进入某区间的边 / 离开某区间的边 |
| `_zfz_preds.py` | 谁跳到了某个地址 |
| `_zfz_sel_sites.py` | 全 `__text` 扫某个选择器的所有发送点（带方法归属） |
| `_zfz_who_impl.py` | 哪些类实现了某个选择器 |
| `_zfz_class.py` | `__objc_classrefs` 槽位 → 类名 |
| `_zfz_stub2.py` | Thumb `__symbol_stub4` → 导入符号名（如 `_arc4random`） |
| `_zfz_mem.py` / `_zfz_range.py` / `_zfz_mat.py` / `_zfz_regpath.py` | 内存字面量 / 区间反汇编 / 常量解析 / 寄存器路径追踪 |
| `_zfz_plists.py` / `_zfz_market.py` / `_zfz_tileprops.py` / `_zfz_canharvest.py` | 数据 plist 普查 |

中间产物在 `_analysis/dumps/_zfz_*.txt`。
