# 任务完成瞬间闪退：NSNotificationCenter 悬空观察者

分析对象：`zombie_farm/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa`
＋ `touchHLE.exe`（fork fa3d095 + 本次修复）
日期：2026-09-20

---

## 0. 结论先说

**闪退的直接原因**：`NSNotificationCenter` 里残留了一条**指向已释放对象**的观察者记录，
派发时把 `incrementCount:` 发给了那个地址上**后来被复用成别的对象**（原报错里是 `NSString`）。

**为什么会有悬空记录**：**是我们自己造成的**。v10/v11 的 IPA 补丁为了修「任务计数归零」，
把 `-[ZFQuestNotification stopListening]` 的整个函数体改写成只剩
`[[NSNotificationCenter defaultCenter] removeObserver:self]` ——
**原来那句「逐个注销 requirements 观察者」的循环被覆盖掉了**。
v11 的注释当时判断这是「无害的小泄漏」，实际上它是崩溃的根因：

```objc
// 原始函数体（base IPA 0x10a1dc，sub9）
- (void)stopListening {
    for (ZFQuestRequirement *req in self.requirements) {   // ivar +0x128
        [[NSNotificationCenter defaultCenter] removeObserver:req];
    }
}

// v11 之后（v27fix 里实测就是这个）
- (void)stopListening {
    [[NSNotificationCenter defaultCenter] removeObserver:self];
}
```

**修法**：在模拟器里补上 iOS 9+ 的语义 —— 「观察者被释放而没注销时，系统在下次派发前清理它」。
`NSNotificationCenter` 本来就不持有 observer，v27 的 `stopListening` 又不再注销它们，
于是每个被释放的 `ZFQuestRequirement` 都留下一条悬空记录。现在这些记录会在派发时被识别并丢弃。

---

## 1. 证据链

### 1.1 静态：`incrementCount:` 只可能由通知中心发出

`tools/scan_selector_refs.py "incrementCount:"`（全 `__text` 扫描 + PIC `movw/movt` 解析）：

```
sub9  0x10a15e/0x10a16a   ZFQuestNotification -startListening +0x72/+0x7e
      -> selref "incrementCount:"
sub9  0x109304 / 0x1093b4  ZFQuestRequirement -incrementCount: 自身的内部分支
```

即整个二进制里，这个 selector 只在
`-startListening` 里被用作 `addObserver:selector:name:object:` 的 selector。
**没有任何一处直接 `[obj incrementCount:]`。**
所以那条报错信息里的接收者，必然是**通知中心登记过的 observer**。

### 1.2 静态：v11 之后 requirements 不再注销

`tools/annot_disasm.py at 0x10a1dc 0x90`：

* base IPA：完整的多重枚举循环（`countByEnumeratingWithState:` → `[center removeObserver:req]`）
* v27fix：`push {r4,lr}; …defaultCenter…; removeObserver:self; pop`，后面全是 `nop`

而 observer 列表在模拟器里存的是**裸指针**（不 retain，与 iOS 9 之前一致）。

### 1.3 这些 requirement 确实会被释放

`ZFQuestMan -completeQuest:`（sub9 0x10b108 起）末尾：

```
[questQueue removeObject:<quest>]
[quest setUserData:...]
[self cleanupQuest:<quest>]        -> [quest stopListening]
                                      [quest removeAllChildrenWithCleanup:YES]
                                      [[quest parent] removeChild:quest cleanup:YES]
```

任务从队列和场景里摘掉后，`ZFQuestNotification` 的引用计数归零，
它的 `requirements` 数组随之释放 —— 而观察者记录还留在通知中心里。

### 1.4 运行时：A/B 对照（决定性）

模拟器里加了一个一次性自检（`TOUCHHLE_NSNOTIFICATIONCENTER_STALE_SELFTEST=1`）：
在 guest 注册第一个观察者时，自己造一个「注册后释放、地址被别的东西复用」的观察者，然后派发。
脚本：`_analysis/_observer_selftest.ps1`。

| 运行 | 结果 |
|---|---|
| 关闭清理 `TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE=1` | **复现原崩溃**：`Object 0x3c8220 (class "NSNotification") does not respond to selector "incrementCount:"`，进程退出码 **-1073741819**（与主人截图里的 0xC0000005 完全一致） |
| 打开清理 | `Skipping stale NSNotificationCenter observer for "incrementCount:": 0x3c8220 (registered as NSObject, now a live NSNotification)`，随后继续运行，不崩 |

自检里的对象与被复用的类型和真实场景不同（那里是 `_touchHLE_NSString`），
但机制、报错格式、退出码完全一致 —— 这也是为什么主人看到的是 NSString。

---

## 2. 改动

`touchHLE-fork/src/frameworks/foundation/ns_notification_center.rs`

1. `Observer` 多记两个字段：注册时的 `registered_class`（isa）和
   `was_host_managed`（当时是否由模拟器托管）。
2. 新增 `observer_is_stale()`：
   * 注册时就不是托管对象的 → **永不判为悬空**（无法判断，保守处理）；
   * 现在查不到 host object → 已释放，悬空；
   * 还在，但 isa 和注册时不同 → 地址被复用成别的对象，悬空。
3. `postNotification:` 派发前逐个校验；悬空的跳过并记一条日志，
   派发结束后把这些记录从表里删掉，并补上注册时对 filter 对象的 retain/release 配平。
   删除时按 **整条记录**（地址＋类＋托管标志）匹配，避免误删派发期间 guest 重新注册的同名对象。

这就是 iOS 9+ 文档里写的「系统会在下次派发时清理忘了注销的观察者」，
游戏显然依赖这个行为：`startListening` 注册的 requirement 在原始二进制里由
`stopListening` 注销，而 v11 把那条路砍了以后就只剩系统兜底。

### 附带的诊断开关（默认全关，不设环境变量完全不生效）

| 环境变量 | 作用 |
|---|---|
| `TOUCHHLE_NSNOTIFICATIONCENTER_STALE_AUDIT=<秒>` | 每隔 N 秒在有通知派发时审计一次观察者表，打印总数与悬空数 |
| `TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE=1` | 关掉清理（A/B 复现用） |
| `TOUCHHLE_NSNOTIFICATIONCENTER_STALE_SELFTEST=1` | 启动后跑一次上面 1.4 的自检 |
| `TOUCHHLE_ZFR_DEBUG_COMPLETE_QUESTS_AFTER=<秒>` | N 秒后（且任务系统已就绪）执行一次「完成全部任务」 |
| `TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION=<名字>[,<名字>…]` | 在上一步之后 N 秒，手动派发这些通知 |

---

## 3. 验证

| 项目 | 结果 |
|---|---|
| `_analysis/_observer_selftest.ps1 -NoPrune` | PASS —— 复现原崩溃（退出码 -1073741819） |
| `_analysis/_observer_selftest.ps1` | PASS —— 悬空观察者被清理，进程存活 |
| `GameManager.ps1 -SelfTest` | PASS |
| `_no_console_test.ps1` | PASS |
| `_ipa_picker_test.ps1` | PASS |
| `_gui_tip_test.ps1` | PASS |
| `_verify_release.ps1` | PASS |
| `_release_e2e.ps1` | PASS |
| `_no_dependency_test.ps1` | PASS |

真实存档里的复现（种胡萝卜 → 完成「农场准备」）留给主人实操验证：
`_analysis/_quest_observer_test.ps1` 已经能自动走到农场并在指定时刻完成全部任务＋派发任务通知，
只是它需要模拟点击「开始游戏」，坐标和窗口焦点不稳定，所以不作为结论依据。

---

## 4. 遗留

* ~~**IPA 侧还可以做一次根因修复**~~ —— **已于 v28fix 完成**，见
  `_analysis/reports/ZFR_v28fix_任务闪退根因修复.md`。
  当时估计「需要开 code cave」是**错的**：v11 把整个函数体填成了 NOP，
  0xc0 字节的槽位是空的，新体（改用 `count`/`objectAtIndex:` 写循环）只有 0x8a 字节，
  **原地就塞得下**。
  模拟器侧的清理**保留**作为通用兜底：任何别的悬空注册也能兜住。
* 「任务计数归零」（v10/v11 要修的那个问题）v28fix **没有回退**，
  verifier 逐条复查了那 6 个工厂站点。
