# 订正：施肥飘字读的是哪张 `.strings` 表

日期：2026-09-20
背景：`_analysis/reports/ZFR_施肥僵尸_机制取证.md` §2.1 断言这条飘字读的是
`Localizable.strings`（默认表），并据此说 v29fix 改错了文件。**这个断言是错的。**
本文给出订正与根因。

---

## 1. 结论

**这条飘字读的就是 `Arial-BoldMT.strings`，v29fix 改对了文件。**

`ZFR_施肥僵尸_机制取证.md` 的 §2.1 有一处**工具级错误**（把虚拟地址当文件偏移用），
导致它读到了相邻数据、把一个真实字符串看成了空串，进而推出"表名是空 =
默认表 = Localizable.strings"。

**该报告 §2 之后的全部结论不受影响** —— 施肥的触发路径、概率来源、
`%@` 是施肥者名字、`SaveTile.fertilized` 的效果等等，用的都是正确的地址解析。
**只有 §2.1 里"哪张表"这一句需要作废。**

---

## 2. 三条独立证据

### 2.1 历史证据（最强，不依赖任何反汇编）

| 版本 | `Arial-BoldMT.strings` | `Localizable.strings` | 主人当时看到 |
|---|---|---|---|
| v18fix（v19 之前） | ` %@ČđĂ` ← **乱码** | ` %@施肥了` ← **正确** | **乱码**（图1 红框） |
| v19fix（只改了前者） | `%@施肥` | ` %@施肥了` | 正常 |
| v29fix（只改了前者） | ` %@施肥啦！` | ` %@施肥了` | **`啦！`** |

**一张一直是正确的表，不可能显示出乱码。** v19 只碰了 `Arial-BoldMT.strings`，
乱码就消失了；v29 又只碰了它，主人就看到了新措辞。三次观测指向同一张表。

复现脚本：`_analysis/_resolve_table_history.py`。

### 2.2 段扫描（不依赖反汇编）

`__cfstring` 段里 `data` 真正指向 `Fertilized by %@!` 的对象只有一个：

```
object @ 0x003a4d40  data=0x2faac4  len=17  'Fertilized by %@!'
```

而 `_dis.py` 从方法入口解码出的 `r2` 正好是 **`0x003a4d40`** —— 完全吻合。

复现脚本：`_analysis/_resolve_alignment.py`。

### 2.3 反汇编相位（说明谁对谁错）

从**方法入口**（`0x27938`，ObjC 元数据里的真实边界）线性解码：

```
0x0002a0c2  movw  r2, #0xac6c
0x0002a0c8  movt  r2, #0x37
0x0002a0d0  add   r2, pc        -> 0x003a4d40  'Fertilized by %@!'
0x0002a0dc  blx   objc_msgSend  (SEL = localizedStringForKey:value:table:)
```

同一个方法里**找不到任何构造 `0x003a4d40` 的 `movw`/`movt` 对**如果按裸扫描的相位解码
—— 说明**漂移的是裸扫描**，`_dis.py` 的相位才是对的。

---

## 3. 根因：VA ≠ 文件偏移（**全 slice 差 0x1000**）

这是本次真正值得记进 README 的发现：

```
section                 VA          file off    delta
__text               0x00003c68    0x00002c68  0x1000
__cfstring           0x003a3280    0x003a2280  0x1000
__objc_selrefs       0x00393870    0x00392870  0x1000
...                  （所有已映射段一律 0x1000）
__bss / __common     （无文件内容）
```

**因此 `data[va : va+n]` 是错的**，会整体偏 0x1000 读到隔壁数据。
子代理正是这么读的，于是：

* 它以为 `CFSTR 0x3a3310` 的内容是**空串** `""`；
* 用正确映射读，`0x3a3310` 其实是 `''`（真的空串，但那是 **`value:` 回退参数**，
  不是 `table:`）；
* 它由此推出"表名空 → 默认表 → Localizable.strings"。

顺带纠正：`localizedStringForKey:value:table:` 的 ABI 是
**`r0=self r1=_cmd r2=key r3=value [sp]=table`**。
子代理把 `r3` 当成了 `table`，而 `r3` 是 `value`。

> 还有一个**反证**：若 `table:` 真是空串，touchHLE 会去找 `.strings`（不存在），
> `URLForResource:` 返回 nil，`ns_bundle.rs:255` 的 `assert!(dict != nil)` 会**直接 panic**。
> 游戏不 panic，所以表名不可能是空串。

---

## 4. 影响面：**历代工作都没受影响**

`tools/` 的基础设施**全部走 `addr_to_file()`**（`audit_zfr_ipa.py` 7 处、
`inspect_v3_facts.py` 5 处、`patch_zfr_alert_fonts.py` 9 处……），
`_dis.py` / `_v17_cf.py` / `value_xref.py` 也走它。所以：

* 历代 patch / verifier 的地址**都是对的**（v28 的 `0x10a1dc`、`0x16a5f8` 等照旧）；
* 唯一直接索引 `sl.data[a:b]` 的地方是**新旧文件同偏移比较**（偏移相消，无害）
  和 `addr_to_file()` 之后的结果（正确）。

**所以这个坑此前没有被踩到过 —— 它是本次新写的探针引入的。**

---

## 5. 那 `table:` 到底是什么？

**没有在静态层面定死，而且不影响结论。** 事实是：

* 调用点是**三个寄存器参数**的发送（`[sp]` 在该调用前没有被写），
  所以它不是"显式传表名"的常见形态；
* 方法里 `Arial-BoldMT` 这个 CFString（`0x3a3570`）**确实存在**，
  但附近没有把它装进参数寄存器的 `movw/movt` 对 —— 它可能在别处先存进了 ivar。

**但这一点不需要查清**：§2.1 的历史证据是**行为观测**，
它直接证明了"游戏读到的是哪张表的值"，比静态推断更强。

---

## 6. 对已有文档的影响

| 文档 | 是否需要改 |
|---|---|
| `ZFR_施肥僵尸_机制取证.md` §2.1 | **需要** —— 已加订正标注 |
| `ZFR_v29fix_施肥飘字还原.md` | 不需要（结论正确） |
| `TECHNICAL.md` 5.12 | 不需要（结论正确） |
| `process.md` 的 v29 段 | 不需要 |

---

## 7. 新写的脚本

| 脚本 | 作用 |
|---|---|
| `_resolve_table_history.py` | 跨 4 个版本的"哪张表是什么值"对照（**最强证据**） |
| `_resolve_alignment.py` | 段扫描确认真实 CFString 地址，判定哪个反汇编相位正确 |
| `_resolve_call_site_final.py` | 从方法入口解码调用点，解出 SEL 与三个参数 |
| `_resolve_table_final.py` | 追踪 `[sp]`（table 参数）的写点 |
| `_resolve_font_table.py` | 检验"表名 = 字体名"假说 |
| `_check_skew.py` | **证明全 slice 的 VA 与文件偏移差 0x1000** |

（`_resolve_table_contradiction.py`、`_resolve_table_arg.py`、`_resolve_call_site.py`
是排查过程中的中间脚本，保留备查。）
