# v28fix：把「任务闪退」的根因从游戏里拿掉

产物：`zombie_farm/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa`
sha256 `7B37DC7CF874D478BA25D458871B2D19F1B58532E83223C52A5C9519B5BDA7F8`，59,564,493 字节
patcher `tools/patch_zfr_questfix_v28.py`（含汇编 + 结构自检）
verifier `_analysis/_verify_v28fix.py`（全量，不 import patcher）
变异测试 `_analysis/_verify_v28_verifiers.py`
输入：v27fix（sha256 `3D4CA38B…C131`）

---

## 0. 一句话

v11 为了修「任务计数归零」把 `-[ZFQuestNotification stopListening]` **整个函数体**覆盖成了
`removeObserver:self`，顺手删掉了原来那句「逐个注销 requirements」的循环。
v28fix 把那一半**加回来**，同时保留 v11 的那一半。

```objc
- (void)stopListening {
    NSNotificationCenter *center = [NSNotificationCenter defaultCenter];
    [center removeObserver:self];                  // v11 的修法，原样保留
    for (ZFQuestRequirement *req in self.requirements)
        [center removeObserver:req];               // 原始二进制里本来就有，v28 恢复
}
```

为什么这条循环是关键：`NSNotificationCenter` 存的是**裸指针、不持有** observer。
`-startListening` 把每个 `ZFQuestRequirement` 注册成 `incrementCount:` 的观察者；
不注销 → requirement 被释放后留下悬空记录 → 下次派发时 `incrementCount:` 发到
被复用成 `NSString` 的地址上 → 崩溃（退出码 -1073741819）。

---

## 1. 为什么这次不用开 code cave

上一轮报告里我估计要开 cave（「原体 0xc0 字节，新体略长」）。**实测不需要**：

* v11 把 `stopListening` 的 0x10a1dc..0x10a29c（**0xc0 字节**）整段填成了 NOP
  （sub9 `0xbf00`，sub6 `mov r0,r0`），后面的 `requirementUpdated:` 从 0x10a29c 才开始；
* 新体用 `count` + `objectAtIndex:` 写循环，Thumb 汇编出来 **0x8a 字节**，
  ARM 出来 **0x88 字节**，都塞得进原槽位。

为什么不用原来的快速枚举：`countByEnumeratingWithState:objects:count:` 光准备
`NSFastEnumerationState` 就要 ~0x40 字节，原体（0xbe）＋ 新增的
`removeObserver:self`（~0x0e）会到 ~0xcc > 0xc0。`count`/`objectAtIndex:` 在这里
**语义等价**（循环期间数组不会被改），而且这两个 selector 在本二进制里本来就在用。

---

## 2. 关键安全论证：恢复循环**不会**把「计数归零」改回来

这是动手前必须先证明的一件事，否则就是在拿主人已经玩通的那个修复冒险。

`removeObserver:` 是**按指针**匹配的，而两个对象集合不相交：

* `-initWithID:loadSprite:` 自己读 `Quests.plist`，`alloc/init` 出**全新的**
  `NSMutableArray`（sub9 `0x109a1e`..`0x109a48`）和**全新的**
  `ZFQuestRequirement` 对象（`0x109b2a` 处 `classref -> ZFQuestRequirement`），
  存进自己的 ivar `+0x128`；
* 所以 GameData 造的那个 throwaway 通知，**拥有的是另一组 requirement 对象**，
  它的循环只能注销自己的那组。

也就是说 v28 恢复的正是**未打补丁的原版游戏行为**；v11 才是那个例外。

---

## 3. 站点（两个 slice 都打）

| slice | 地址 | 长度 | 内容 |
|---|---|---|---|
| sub9 | `0x10a1dc..0x10a29c` | 192 B | `stopListening` 函数体（Thumb，138 B 代码 + NOP 补齐） |
| sub6 | `0x16a5f8..0x16a700` | 264 B | `stopListening` 函数体（ARM，136 B 代码 + `mov r0,r0` 补齐） |
| sub6 | `0x16a700..0x16a718` | 24 B | 该方法**自己的**字面量池，6 个槽位地址 |

sub6 的池子原来就是这 6 个字的槽位（v11 曾把它改成 3 个字），v28 按 6 个 load 重写。

---

## 4. 验证

### 4.1 结构验证（汇编级）

两个 slice 都逐条反汇编核对，不是「哈希对得上就算过」：

* 6 次调用**全部**指向 `objc_msgSend`（sub9 必须是 `blx`）；
* 每次调用前 `r1` 载入的**必须**是对应槽位 —— 逐寄存器跟踪 `movw/movt`，
  且任何对 `r1` 的其它写会作废跟踪值（早期版本只看「最后两条字面量」，
  会因 `r0` 的类引用而侥幸通过，已修）；
* 调用顺序 = `defaultCenter, removeObserver, requirements, count, objectAtIndex, removeObserver`；
* 循环回边唯一，且落回「重读 count」；`bhs`/`bcs` 唯一，且跳到收尾；
* 收尾与 prologue 配对，**除 prologue/epilogue 外没有任何指令碰 SP**；
* sub6 的 7 个池 load **全部**落在池子范围内，且读出的字**逐一等于**期望槽位。

### 4.2 独立 verifier（不 import patcher）

`_analysis/_verify_v28fix.py`：重算 FAT/ZIP 表、**逐字节 diff 限定在 3 个区域**、
上述结构复验、以及**把 v2..v27 的全部旧站点逐条重查**（字体/颜色/金币经验格式串/
v23 尺寸 stub/v17 voucher/v22 setColor/v24 非粗体/v27 标题常量/10 个旧禁区逐字节未变）。
结果：**ALL CHECKS PASSED**。

### 4.3 变异测试（证明验证器不是空转）

`_analysis/_verify_v28_verifiers.py` 故意把产物改坏 12 种方式，要求验证器**全部报错**：
选错槽位、删掉循环里的 `removeObserver`、掐断回边、栈不平衡、调用目标写错、
sub6 池字写错、池 load 越界、sub6 体碰 SP、体超长、输入哈希不符、禁区重叠。

这一步**真的抓到了我自己的 bug**：`verify_stack_balance()` 原来在内部**重新汇编**
而不是检查传进去的字节，于是「栈不平衡」和「sub6 碰 SP」两个变异都被放过了。
已改为接受字节参数；现在 12 个变异全部被捕获。

### 4.4 启动器与 Release

| 项目 | 结果 |
|---|---|
| `GameManager.ps1 -SelfTest` | PASS |
| `_no_console_test.ps1` | PASS |
| `_ipa_picker_test.ps1` | PASS |
| `_gui_tip_test.ps1` | PASS |
| `_verify_release.ps1` | PASS（Release 里就是 v28fix，独立跑得起来） |
| `_release_e2e.ps1` | PASS（从 Release GUI 点「启动游戏」能进游戏） |
| `_analysis/_ensure_bom.ps1` | 全部脚本 parse 通过 |

### 4.5 游戏内验证：**主人已实测通过** ✅

自动化**没有**验到这一层，如实说明：`_analysis/_v28_ab.ps1` 我写了一个
「关掉模拟器兜底清理、只靠 IPA 修复」的 A/B，但两次跑都**卡在开始界面**
（模拟点击坐标落在 y=511，而「开始游戏」按钮实际在 y≈690），
日志里 `0 stale / 0 observers`、debug hook 一次都没触发 —— 属于**无效实验**，不作为依据。
按主人的要求，游戏内验证由主人执行。

**主人的结果（2026-09-20 03:16 那次启动，`zfr_last_launch.txt` 记录的正是 v28fix）：**

* 升级 + 完成任务：**不再闪退**；
* 附带发现：**弹出式提示框里的图片显示也正常了**（见第 7 节的机制分析）。

自动化侧对该次运行的日志复核（`zfr_last_run.log` 是**累积**文件，
最后一次启动是文件末尾那段，行 4734 起）：

| 关键词 | 该段命中数 | 含义 |
|---|---|---|
| `does not respond to selector` | 0 | 没有崩溃 |
| `panicked at` | 0 | 没有 panic |
| `Skipping stale …` | 0 | **模拟器兜底一次都没出手** |
| `incrementCount` | 0 | 该通知名全程没被投递到错误对象 |

最后一行是关键：上一轮（仅模拟器兜底）时这里会出现
`Skipping stale NSNotificationCenter observer for "incrementCount:"`，
说明兜底在**替我们擦屁股**；v28 之后它不再出现，
正是「悬空记录已在源头消失」的预期特征。

---

## 5. 怎么自己复核

1. 看 `zfr_last_launch.txt`：`ipa =` 那行应是 `…fixed-fonts-v28fix.ipa`，
   `sha256 = 7B37DC7C…A7F8`。
2. 看 `zfr_last_run.log` 的**最后一段**（从最后一个 `CPU emulation begins now.` 往后）：
   不该出现 `Skipping stale NSNotificationCenter observer for "incrementCount:"`，
   也不该出现 `does not respond to selector`。
   *注意这个文件是累积的，前面的段属于更早的启动，别被旧记录误导。*

---

## 6. 回滚

v28fix 是**新增文件**，不覆盖 v27fix。管理器里选回
`…fixed-fonts-v27fix.ipa` 即可退回；模拟器侧的兜底清理一直有效，
所以就算选回 v27fix 也不会闪退。

---

## 7. 附带修好的「弹出式提示框里的图片」

主人实测反馈：v28 之后任务弹窗里的**图片显示也正常了**。代码链已定位到同一个根因。

### 7.1 弹窗每行画的是 requirement 自己的图片

`ZFAlertWindowQuest -initWithQuest:`（sub9 `0x10cf1c..0x10d76c`）遍历
`self.requirements`，为**每一条** requirement 画一行。每行取图的确切指令序列：

```
0x10d3d0  mov r0, r8            ; r8 = 该行对应的 requirement 对象
0x10d3d2  blx objc_msgSend      ; sel = "spriteFilename"
0x10d3d6  ldr r1, [sp,#0x88]    ; sel = "spriteWithFile:"
0x10d3da  mov r0, r4            ; r4 = CCSprite
0x10d3dc  blx objc_msgSend      ; CCSprite spriteWithFile:<该 requirement 的图>
```

即**每行的图来自 `req.spriteFilename`** —— 一个存在 requirement 对象上的字段。

> 订正：报告初稿曾把 `bigCheck.png` / `bigX.png`（`0x10d648` / `0x10d582`）当成
> 「每行的勾/叉」。核对后确认那两个是 **CCMenuItemImage 按钮**
> （target 分别是 `dismissAlertPositive:` / `dismissAlertNegative:`，
> 即弹窗的「确定/取消」），不是逐行勾叉。此处已改正。

### 7.2 每行还读 `countCurrent` / `countTotal`

```
0x10d2a8  selref-> "countTotal"      ┐ 取 selector
0x10d2b0  selref-> "countCurrent"    ┘
0x10d494  ldr r1, [sp,#0x90]         ; countCurrent
0x10d4a0  blx objc_msgSend           ; req.countCurrent -> r5
0x10d4a4  ldr r1, [sp,#0x94]         ; countTotal
0x10d4ae  blx objc_msgSend           ; req.countTotal   -> [sp]
0x10d4c8  CFSTR "%i/%i"              ; 文本 "当前/总数"
0x10d54a  cmp  r5, r0                ; 行循环边界
0x10d54c  blo.w 0x10d314             ; 还有行 -> 回到循环头
```

而 `-[ZFQuestRequirement incrementCount:]` 改的正是 `countCurrent`
（ivar `+0x10`；sub9 `0x1092fa`：`ldr r1,[r1]`=`0x10` → `ldr r2,[r4,r1]`
→ `add r0,r2` → `str r0,[r4,r1]`）。

### 7.3 与模拟器兜底清理的关系（为什么上一轮没修好它）

上一轮的模拟器兜底只能拦住**会崩的那种**悬空：地址被复用成**别的类**
（`NSString`）→ `observer_is_stale` 判为 stale → 跳过。

但**同类复用**判不出来：如果 `ZFQuestRequirement` 的地址被复用成
**另一个 `ZFQuestRequirement`**，isa 相同 → 那条记录被当作正常观察者
**照常派发** → 多投递一次 `incrementCount:` → 该 requirement 的
`countCurrent` 多加 1 → 弹窗按错位的计数画那一行。

这正是交付 v28 前提到的残留风险（「同类复用拦不住，会多记一次」）。
**IPA 侧注销掉，才把这条路径真正切断。**

### 7.4 诚实标注：哪些是实测、哪些是推断

* **实测（主人）**：v28 之后弹窗图片显示正常了。
* **静态确证**：弹窗每行确实取 `req.spriteFilename` 并读
  `countCurrent`/`countTotal`（上面的指令地址可复核）；
  `incrementCount:` 确实写 `countCurrent`。
* **推断（未做对照实验）**：把「同类复用 → 多投递一次 → 计数错位 → 图片显示不对」
  这一条链归因给主人看到的图片问题。**没有**做「v27 图错 / v28 图对」的
  对照截图，也没有抓到一次实际的 `Skipping stale` 同类复用日志。
  主人反馈的是「图片显示」，而上面证到的是「计数与行图都读同一批 requirement 数据」，
  两者同源但**不是逐像素对得上的证明**。
  若要坐实，可做一次对照：v27 与 v28 各截一张同一任务的弹窗图对比。

---

## 8. 遗留

* 模拟器侧的悬空观察者清理**保留**，作为通用兜底（任何别的悬空注册都能兜住）。
  它现在应该几乎不再触发 —— 触发即说明还有别的地方在漏注销。
* 模拟器兜底的**已知盲区**：地址被复用成**同类**对象时判不出悬空（见 7.4）。
  若日后还想加固，可给 guest 对象加分配序号（登记时记下，派发时比对），
  这样同类复用也能识别；本次**没做**，因为 IPA 侧已经把根因去掉了。
* 「任务计数归零」的修复（v10 工厂补丁 + v11 的 `removeObserver:self`）**未回退**，
  本次 verifier 专门逐条复查了这 6 个站点。
