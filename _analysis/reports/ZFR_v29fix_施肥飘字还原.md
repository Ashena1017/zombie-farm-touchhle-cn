# v29fix：把施肥飘字丢掉的「空格 + 语气词」还原回来

日期：2026-09-20
产物：`zombie_farm/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa`
大小 **59,564,493 字节**，sha256 `E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED`
patcher `tools/patch_zfr_b2_v29.py`，verifier `_analysis/_verify_v29fix.py`（**ALL CHECKS PASSED**）

主人指令（本轮输入）：

> 所以你能把没显示的字弄回来？能不能把那个「了」改成「啦」？
> → 可以可以，那感叹号也补上吧

最终值：`Fertilized by %@!` → **` %@施肥啦！`**（前导空格 + 啦 + 全角感叹号）

---

## 1. 一句话结论

**「189 字节装不下」这个判断是错的 —— 那是「二进制 plist 装不下」，不是「槽位装不下」。**
同一份内容换成 OpenStep 文本格式压缩后只要 182 字节，**槽位大小不变**，
所以 IPA 尺寸、归档偏移、可执行文件全部一动不动。

上一轮的复查报告（`ZFR_施肥飘字_长度限制复查.md`）已经查清了机制，
本轮把它**落地成产品**，并把值从 ` %@施肥了` 改成主人要的 ` %@施肥啦！`。

---

## 2. 为什么是「全角！」而不是 ASCII `!`

主人的原话是「感叹号也补上吧」，没指定半角/全角。选**全角 `！`**（U+FF01）的理由是
游戏自己的本地化习惯：

| 证据 | 数值 |
|---|---|
| `zh-Hans/Localizable.strings` 的**中文值**里全角 `！` | **500** 处 |
| 同一批中文值里 ASCII `!` | 67 处 |
| 游戏里是否已有「啦！」这个组合 | **有** —— `ZOMBIE FARM GOES SOCIAL!` → `僵尸农场更新到社交版啦！` |

也就是说 `啦！` 是这份本地化里**已经存在的写法**，不是我拼出来的。
而且键名本身就以 `!` 结尾（`Fertilized by %@!`），语义上确实该带感叹号。

> 若主人更想要半角 `!`，改 `tools/patch_zfr_b2_v29.py` 里的 `FERT_VALUE` 即可 ——
> 半角版本只要 184 字节，槽位更宽裕。这属于**改一个字符串常量**级别的小改。

---

## 3. 槽位余量的实测账

两个成员各自被 codex 补丁塞进 **189 字节**的 DEFLATE 槽位（它是按自己那套
极好压缩的乱码算出来的）。各候选值的实测压缩后大小：

| 候选值 | 压缩后 | 对 189 槽位 |
|---|---|---|
| ` %@施肥了`（bplist，v19 当年试的） | **193** | 超 4 ← 当年就卡在这 |
| `%@施肥`（v19 实际出货） | 188 | 余 1 |
| ` %@施肥啦` | 182 | 余 7 |
| ` %@施肥啦!`（半角） | 184 | 余 5 |
| **` %@施肥啦！`（全角，本次采用）** | **186** | **余 3** |

注意第一行和第二行是**同一种序列化格式（bplist）**下的对比 ——
这正是当年「只能缩短」的由来。换格式后，**更长的忠实文本反而更小**。

---

## 4. 改了什么（逐字节范围）

| 成员 | 改动 |
|---|---|
| `Payload/ZFR.app/Arial-BoldMT.strings` | 由 binary plist 重序列化为 OpenStep 文本，值换新 |
| `Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings` | 同上 |

每个成员：`usize` 253 → **396**，`csize` **189 → 189（不变）**，CRC 更新，
压缩后 186 字节 + 3 字节填充。

**可执行文件一个字节都没动**（输入/输出 `executable_sha256` 均为
`45D647787CC6256DBE83B041808E5845739A7B331B72DC030C7FD6E9CC04B05B`）。
`csize` 不变 ⇒ 归档里**没有任何偏移移动** ⇒ IPA 仍是 59,564,493 字节。

其余 7 条值**逐字节未变**（verifier 断言）：`丘比特僵尸`、`花花僵尸`、`园丁僵尸`、
`花花僵尸`、`生态僵尸`、`蜜蜂僵尸`、`蝴蝶僵尸`。

---

## 5. 验证（三层，全部独立于 patcher）

### 5.1 结构 + 归档一致性 —— `_analysis/_verify_v29fix.py`

**ALL CHECKS PASSED**。覆盖：归档身份、恰好 2 个成员变化、
OpenStep 结构 + 解码后的值、另外 7 条值未变、`csize` 保持 189、
存储流能解压且 CRC 相符、**声明范围之外没有任何字节变化**。

### 5.2 游戏真正的加载器能读懂吗 —— `_analysis/_v29_loader_probe.ps1`

这是**决定性**的一层。加载路径（读源码得到）：

```
-[NSBundle localizedStringForKey:value:table:]
  -> [NSDictionary dictionaryWithContentsOfURL:]      ns_dictionary.rs:559
  -> deserialize_plist_from_file()                    ns_property_list_serialization.rs:133
  -> plist::Value::from_reader(...)                   plist crate 1.8.0
```

`plist-1.8.0` 的 `Reader::init` 自动识别编码：binary magic → 二进制；否则先试 XML；
XML 失败 → 回退 **OpenStep/ASCII reader**。`Value::from_reader` 的文档原文就是
*"a plist of **any encoding**"*。

探针**取出货文件里真实的成员字节**，喂给**同一个 crate 版本**（registry 里 vendored 的
plist-1.8.0）编译出的 Rust 程序，按**码点**比对（不靠中文字面量，避免编码陷阱）：

**RESULT: PASS** —— 两个成员都解出 `vec![0x20, 0x25, 0x40, 0x65BD, 0x80A5, 0x5566, 0xFF01]`
= ` %@施肥啦！`。

### 5.3 启动冒烟 —— `_analysis/_v28_boot.ps1 -Ipa …v29fix.ipa -Tag v29`

`emulation began: True; panic: False; still alive at the end: True` → **RESULT: PASS**。
（读档路径本身就会走到这些 `.strings` 表，所以这一步同时排除了「表格式不对导致读档即崩」。）

### 5.4 游戏内实测

**已通过 —— 主人实测确认**（2026-09-20）：

> 我试过了，你的修改相当成功！字符已经正确显示了！

因此 v29fix 已**晋升为默认版本**：`GameManager.ps1` 的 fallback、
`launcher_selected_ipa.txt`、`_analysis\_build_release.ps1` 的 `$ipaName` 三处均已改为
v29fix，`Release\` 也已重建并内含 v29fix（`_verify_release.ps1` 与 `_release_e2e.ps1` 均 PASS）。

---

## 6. 探针踩到的两个格式坑（写进 README 5.12）

1. **大括号是必需的**。裸列表 `"k" = "v";` 会被拒：
   `PARSE FAILED: ExpectedEndOfEventStream { found: String }`。必须是 `{ "k" = "v"; }`。
2. **不能直接写 UTF-8 字节**。ASCII reader 按 1:1 映射字节 → 中文变 Latin-1 乱码
   （实测得到 ` %@æ\u{96}½...`）。**非 ASCII 必须写 `\Uxxxx` 转义**。

另外：验证「值对不对」时**不要用中文字面量做期望值**。
`_v29_loader_probe.ps1` 第一版就因为 PowerShell 把 UTF-8 写成了无 BOM，
Rust 源码里的中文被错误解码，对一个**字节完全相同**的字符串报了 WRONG。
改成**逐码点比对**后立刻通过。

---

## 7. 遗留 / 风险

* **游戏内实测已通过**（主人确认，见 5.4），v29fix 已是默认版本。
* **风险点**：真实 iOS 与 touchHLE 都接受 OpenStep `.strings`（这本就是该格式的经典用法），
  但本项目的 IPA 只在这台机器的 touchHLE 上验证过。
* **回滚**：v29 是**新增文件**，没有覆盖任何东西。
  要回滚就在管理器里选回 `v28fix`（模拟器侧的兜底清理一直有效，选回去也不会闪退）。
* **已晋升**：`Release/`、`GameManager.ps1` 的 fallback、`launcher_selected_ipa.txt`
  均已指向 v29fix。

## 8. 附带发现：僵尸被施肥也会显示这句飘字

主人实测后反馈：**不只是种植物，把僵尸放到土地上时也会出现「XX僵尸施肥」**，
问这是 bug 还是被施肥的僵尸有特殊效果。

取证见 `_analysis/reports/ZFR_施肥僵尸_机制取证.md`（独立一轮调查）。
