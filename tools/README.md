# IPA 工具

| 工作 | 入口 |
|---|---|
| 读取 IPA 的 Mach-O、Objective-C 方法和区段 | [audit_zfr_ipa.py](audit_zfr_ipa.py) |
| 查看带注解的反汇编和跨引用 | [annot_disasm.py](annot_disasm.py)、[value_xref.py](value_xref.py) |
| 回放某一版二进制补丁 | 对应的 `patch_zfr_*.py`。版本与作用见[技术参考](../TECHNICAL.md#62-历代-patcher-与验证器)。 |
| 维护标题页水印 | [_make_notice_texture.py](_make_notice_texture.py)、[_build_notice_ipa.py](_build_notice_ipa.py) |

工具使用 Python 3。反汇编功能使用 Capstone，水印工具使用 Pillow 和 Windows 微软雅黑字体。当前维护环境已验证 Python 3.14 和 Capstone 5.0.9 的读取与反汇编。需要依赖时可在虚拟环境执行 `python -m pip install capstone Pillow`。

从仓库根目录选择一份已有 IPA 进行只读检查。

```powershell
$ipa = (Get-ChildItem -LiteralPath zombie_farm_ipa -Filter '*-v29fix-notice.ipa' -File | Select-Object -First 1).FullName
python tools/audit_zfr_ipa.py $ipa
python tools/annot_disasm.py meth ZFGuiLayer showRateIt --ipa $ipa --sub 9
```

历史补丁的输入 IPA、输出路径和参数以对应脚本为准。v29 的补丁参数可用 `python tools/patch_zfr_b2_v29.py --help` 查看。独立验证需要本机已有对应版本的两个 IPA，脚本入口见[验证工具索引](../_analysis/README.md)。

水印脚本共用 `_analysis/dumps/release-assets/MainMenuBG.notice.png`。第一步从现有 v29fix 读取标题图层并输出水印图，第二步将图层写入 v29fix-notice，并逐成员比对。如果已有同名 v29fix-notice，第二步会替换它。正式 IPA 的来源与核验见[维护交接](../HANDOVER.md)。
