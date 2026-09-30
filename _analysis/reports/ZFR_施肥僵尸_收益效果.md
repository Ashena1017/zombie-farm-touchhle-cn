# 「种在地里的僵尸」被施肥有什么效果？

日期：2026-09-20
二进制：`zombie_farm/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa`
（sha256 `E5951F94…9DED`），代码阅读用 **sub9（Thumb）**。
**纯静态分析，未运行游戏、未修改任何文件。**

承接 `ZFR_施肥僵尸_机制取证.md`（那里查清了"谁施肥、按什么概率"）
与 `ZFR_施肥飘字_表来源订正.md`（订正了表来源）。
**本文专门回答：被施肥的僵尸地块，实际收益是什么。**

---

## 1. 结论

**和作物完全一样 —— 收获时多拿一份市场价（等于双倍金币），外加粒子特效。没有僵尸专属效果。**

三条逐字节验证的依据：

1. **奖励代码块唯一的开关是 `[tile fertilized]`，没有任何 plant/zombie 判别。**
   收获分支（`command == 2`，`0x27e92` 起）里**扫遍所有选择器装填**，
   **找不到一个**名字含 `zombie` / `plant` 的选择器（`_zfe_shared.py` 输出
   `NONE -- the harvest path does not test plant-vs-zombie at all`）。
2. **奖励金额取自市场条目名**：`[market costFromName:name]` →
   `[gameData addResource:0 amount:cost]`，即**再发一份该条目的 `cost`**。
   这就是主人观察到的"双倍金币"。
3. **僵尸在地块上就是 `category='crop'` 的条目**，和植物共用
   `cost` / `growTime` / `SaveTile.fertilized` 一整套字段
   （`Market.plist` 里 83 个 crop 条目，其中 37 个 `subCategory='zombie'`）。

**所以：给僵尸地块施肥 = 收获这只僵尸时多拿一份它的市场价。**
园丁系僵尸 `cost=150` → 施肥后收获共得约 **300**；普通僵尸 `cost=35` → 约 **70**。

---

## 2. 证据链

### 2.1 奖励块（`0x28a9c`）的唯一守卫

```
0x00028a84  movw  r1, #0xb9a0
0x00028a88  movt  r1, #0x36
0x00028a8c  add   r1, pc        ; slot -> SEL 'fertilized'
0x00028a8e  ldr   r1, [r1]
0x00028a90  blx   objc_msgSend  ; r0 = [tile fertilized]
0x00028a94  tst.w r0, #0xff
0x00028a98  beq.w #0x28c34      ; ★ 没施肥 -> 整块跳过（唯一的分支）
0x00028aa4  ldr   r1, [sp, #0x7c]
0x00028aa8  ldr   r0, [r0]      ; cstr '...png'（特效资源）
0x00028aaa  blx   objc_msgSend
0x00028ab8  add   r1, pc        ; slot -> SEL 'costFromName:'
0x00028abc  blx   objc_msgSend  ; r0 = cost
0x00028ac0  mov   r4, r0
0x00028ace  add   r0, pc        ; slot -> SEL 'addResource:amount:'
0x00028ad0  movs  r2, #0        ; 资源类型 0 = 金币
0x00028ad2  mov   r3, r4        ; ★ amount = cost
0x00028ada  blx   objc_msgSend  ; [zfGameData addResource:0 amount:cost]
```

**全方法内跳进这一块的边只有 `0x28a68 b #0x28a72`**（顺序流入），
跳出的只有 `0x28a98 beq.w #0x28c34`（`fertilized == 0`）。
**逐字节验证。** → 开关只有 `fertilized`。

### 2.2 收获路径里没有 plant/zombie 判别

`_zfe_shared.py` 把 `0x27e92..0x28a9c` 区间内**每一个** `movw/movt + add reg,pc`
装填出来的 SEL 槽都解出来，得到 40 余个选择器（`fertilized`、`costFromName:`、
`addResource:amount:`、`replaceTile:withGIDkey:considerNeighbouringTiles:`、
`tSpriteFromTile:`、`headID`、`flyingCrops`、`setCarrotsHarvested:` …）。

**其中名字含 `zombie` 或 `plant` 的：0 个。**
CFStrings 里也没有任何提到 zombie/plant/fertil/crop/harvest 的。

**逐字节验证。** → 收获结算**不区分**种的是植物还是僵尸。

> 注意 `setCarrotsHarvested:`（成就计数）是**胡萝卜专用**的统计，
> 但它是无条件调用的，不是分支条件 —— 不影响收益。

### 2.3 数据侧：僵尸就是 crop，且 `cost` 就是收获价值

`Market.plist`（507 条目）里 `category == 'crop'` 的 83 条，其中 37 条
`subCategory == 'zombie'`：

| 僵尸 | unitKey | cost | growTime | info |
|---|---|---|---|---|
| Garden Zombie（园丁） | `ZombieActorGardenTier1` | **150** | 86400 | `Fertilizes` |
| ZomBotanist（生态） | `ZombieActorGardenTier2` | **150** | 86400 | `Fertilizes+` |
| Flower Zombie（花花） | `ZombieActorGardenTier3` | **150** | 86400 | `Fertilizes++` |
| ZomBumpkin（大型） | `ZombieActorLargeTier1` | 80 | 21600 | `Strong fighter` |
| Mini Zombie（小型） | `ZombieActorSmallTier1` | 55 | 600 | `Fast Crop` |
| Girl Zombie | `ZombieActorGirlTier1` | 45 | 14400 | `Nimble fighter` |
| Headless Zombie | `ZombieActorHeadlessTier1` | 40 | 14400 | `Tough fighter` |
| Zombie（普通） | `ZombieActorRegularTier1` | 35 | 14400 | `Balanced fighter` |

注意 `Mini Zombie` 的 `info` 直接写着 **`Fast Crop`** —— 官方数据自己就把僵尸叫"作物"。
**逐字节验证。**

### 2.4 与植物的一致性

`SaveTile` 的 ivar 布局里 `fertilized` / `isZombie` / `isPlant` 是**并列的三个布尔**
（`+0x01c` / `+0x01d` / `+0x01e`），`TileProperties.plist` 里僵尸走
`soil_seeded_garden_zombie → soil_germinating_… → soil_harvestable_garden_zombie`
同一套阶段链。**逐字节验证**（见前一份报告 §3.1）。

→ 所以"僵尸地块被施肥"在数据模型上是**完全正常的**，收益自然也和植物同源。

---

## 3. 顺带纠正一个误读

前一份报告的 §2.1 提到 `0x28030` 有 `movs r1,#3` / `tst r5,#0xff` / `movne r1,#6`，
看起来像"施肥让某个数值 3→6"。**那个不是金钱倍率。**

它后面接的是 `marketItemFromTilePropertiesKey:`、`CFSTR 'isRemoteItem'`、
`theRemoteMarket`、`CFSTR 'spriteSheet'`、`path`、`stringByAppendingPathComponent:` ——
是**远端资源/精灵表的路径选择**（3 与 6 被当字符串拼进路径），
和金币结算无关。真正的金钱奖励在 `0x28a9c`（本文 §2.1）。

**逐字节验证。**（`_zfe_strings.py` 解出该窗口全部 SEL 与 CFString。）

---

## 4. 未能查清 / 需实测的部分

1. **金币奖励的精确公式。** 已确认是"再发一份 `costFromName:` 的结果"，
   但 `costFromName:` 的返回值是否**恒等于** `Market.plist` 的 `cost` 字段
   （还是含等级/市场波动），静态没定死。前一份报告提到的
   `headID == 14 / 12` 时 `amount += amount * 0.1` 的加成也在同一段附近，
   未逐条追完。
2. **僵尸收获是否也走 `command == 2`。** 本文证明的是"这条路径不区分
   plant/zombie"；**僵尸收获确实由它处理**这一点，最强证据是
   §2.3 的数据结构（僵尸是 crop、有 growTime、走 harvestable 阶段链）
   与 §2.2 的无判别扫描，属于**强推断**而非直接观测。
   → **建议主人实测**：给一只僵尸地块施肥，收获时看是否飘出
   `+N金币(化肥奖励)`，且 N 约等于该僵尸的市场价。
3. `fertilized` 在**非园丁**僵尸地块上能否出现（按 §2 的机制，只能由
   园丁系僵尸的 `fertilizeChance` 掷骰产生，与地块上种的是什么无关）。

---

## 5. 一句话回答主人

> **被施肥的"地里僵尸"和作物一样，收获时多拿一份它的市场价（约等于双倍金币）。**
> 没有僵尸专属效果 —— 因为在这个游戏的数据模型里，
> **种在地里的僵尸本来就是一个 `category='crop'` 的作物**，
> 收益结算那段代码根本不区分两者。

---

## 附：本次新写的脚本（都在 `_analysis/`，未改动任何既有文件）

| 脚本 | 作用 |
|---|---|
| `_zfe_harvest.py` | 收获分支结构 + command 分派 |
| `_zfe_multiplier.py` | 定位 3-vs-6 并列出分支内所有 msgSend |
| `_zfe_strings.py` | 解析窗口内全部 SEL / CFString（**订正 3-vs-6 的误读**） |
| `_zfe_bonus.py` | 奖励块 `0x28a9c` 的完整注解 |
| `_zfe_guard2.py` | 奖励块的进入/跳出的边（证明唯一守卫是 `fertilized`） |
| `_zfe_shared.py` | **扫遍收获路径的选择器，证明无 plant/zombie 判别** |
| `_zfe_zombie_guard.py` | 选择器追踪的中间尝试（保留备查） |
| `_zfe_value.py` | `Market.plist` / `UnitStats.plist` 的僵尸条目与 cost |
