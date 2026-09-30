# 施肥飘字「 %@施肥了」为什么被折中成「%@施肥」

日期：2026-09-20
结论：**当时那个「装不下」的判断不成立** —— 不是槽位太小，是**只试了一种序列化格式**。
换格式后忠实文本能装进同一个 189 字节槽位，且**游戏确实读得懂**。

---

## 1. 问题本体

`Payload/ZFR.app/Arial-BoldMT.strings`（以及 `zh-Hans.lproj/` 下同名成员）里的键
`Fertilized by %@!`：

| | 值 | 码元数 |
|---|---|---|
| 正确（`zh-Hans/Localizable.strings` 里本来就有） | ` %@施肥了` | 6 |
| 实际出货（v19 起） | `%@施肥` | 4 |

差的正是**一个前导空格**和**语气词「了」**。

这两个成员**在原始基线里不存在** —— 是 codex 补丁新建的，8 条值全是乱码
（` %@ČđĂ` 等），v19 修好了乱码，但顺手把这条缩短了。

---

## 2. 当时的理由，与它错在哪

v19 的记录（`process.md`、`tools/patch_zfr_b2_v19.py` 注释）说：

> 这个成员被 codex 塞进一个 **189 字节**的 DEFLATE 槽位（按它自己那套极好压缩的乱码算的）。
> 忠实还原需要 193 字节。试遍了 level 1..9 × 5 种 strategy × memLevel 8/9 × wbits ±15、
> 5 种 key 排序、手写去重 bplist —— 全是 193。最后只能缩短 2 个码元。

**这些数字全部复现无误**（见 §4）。问题在于：**试的全是二进制 plist（bplist）**。
`.strings` 成员不是只能存 bplist。

---

## 3. 关键发现：换格式就装得下

同一份内容（含忠实的 ` %@施肥了`）用三种序列化分别压：

| 格式 | 原始大小 | 最小 DEFLATE | 对 189 槽位 |
|---|---|---|---|
| bplist（当时用的） | 257 | **193** | 超 4 |
| XML plist | 646 | 328 | 超 139 |
| **OpenStep 文本 + `\U` 转义** | 390 | **182** | **装得下，余 7 字节** |

OpenStep 是 `.strings` 的**经典格式**（`{ "key" = "value"; }`），
非 ASCII 用 `\Uxxxx` 转义写。它的原始体积大，但**压缩率好得多**，
所以压缩后反而更小。

---

## 4. 证据链：游戏真的读得懂 OpenStep 吗

这是决定性的问题，逐层查了源码，并**编译探针实测**。

### 4.1 加载路径

```
-[NSBundle localizedStringForKey:value:table:]
    -> [NSDictionary dictionaryWithContentsOfURL:]
       touchHLE-fork/src/frameworks/foundation/ns_bundle.rs:254
    -> -[NSDictionary initWithContentsOfURL:]
       ns_dictionary.rs:559-562
    -> deserialize_plist_from_file()
       ns_property_list_serialization.rs:133
    -> plist::Value::from_reader(...)          // plist crate 1.8.0
```

### 4.2 `plist` crate 的格式自动识别

`plist-1.8.0/src/stream/mod.rs` 的 `Reader::init`：

```
binary magic ("bplist") -> BinaryReader
否则                    -> 先试 XmlReader
XmlReader 失败          -> 回退 AsciiReader（即 OpenStep）
```

`Value::from_reader` 的文档原文就是 *"a plist of **any encoding**"*。

### 4.3 实测（不是只读代码）

用**同一个 crate 版本**（registry 里 vendored 的 plist-1.8.0）编了一个 5 行探针：

| 输入 | 结果 |
|---|---|
| 裸 `"k" = "v";` 列表（无大括号） | `PARSE FAILED: ExpectedEndOfEventStream` |
| **大括号 `{ "k" = "v"; }`** | **`PARSED OK`** |
| 大括号 + `\Uxxxx` 转义 | **`PARSED OK`，中文正确**（`蜜蜂僵尸`、`花花僵尸`、`生态僵尸`…） |
| 对照：现有 bplist | `PARSED OK`，8 条值 |

注意两个坑：
1. **必须有大括号**，裸列表不认；
2. **不能直接写 UTF-8 字节** —— ASCII reader 按 1:1 映射，中文会变 Latin-1 乱码
   （` %@æ\u{96}½...`）。必须用 `\Uxxxx` 转义。

---

## 5. 修法（若要做 v29fix）

把这两个成员从 bplist 换成 OpenStep 文本 + `\U` 转义，值用忠实的 ` %@施肥了`：

* 压缩后 **182 ≤ 189**，**槽位大小不变** → 归档里没有任何偏移移动 →
  IPA 仍是 59,564,493 字节；
* 只需改这两个成员的 CRC、`usize` 与数据；
* 用现成的 `compress_to_fixed_slot()` 就能定长填充（已实测：`padded to exactly the slot = True`）。

已写好候选构造与校验脚本：`_analysis/_fertilize_v29_candidate.py`
（对两个成员都验证了「能解回目标字典」「能填满槽位」）。

---

## 6. 遗留 / 风险

* **未做**：没有真的生成 v29fix.ipa，也没在游戏里跑过。上面的结论是
  「静态 + 探针实测」，**不是**「游戏里看到 ` %@施肥了` 了」。
* **风险点**：真实 iOS 与 touchHLE 都接受 OpenStep `.strings`（这是该格式的经典用法），
  但本项目的 IPA 只在这台机器的 touchHLE 上验证过；若要做，建议做成 v29 单独一版、
  保留 v28 可回退。
* **本次未改动任何 IPA**，`zombie_farm/` 与 `Release/` 仍是 v28fix
  （sha256 `7B37DC7C…A7F8`）。
