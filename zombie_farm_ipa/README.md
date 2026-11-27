# 游戏 IPA 与补丁记录

本工作区的 Windows 和 Android 构建共用 v32fix。启动黑屏底部显示「本整合版免费 · 请勿购买」。本次构建沿用 v30 的游戏可执行文件、位图字体与标题水印。

| 项目 | 值 |
| --- | --- |
| 两端内置文件名 | `内置中文版·v32fix·开源免费.ipa` |
| 大小 | 59,565,945 字节 |
| SHA-256 | `FFBD9D7C7E73A0C5AAB0CA3CD252D28E55272AC5F665AB3B4ECB6E2006C3FFEA` |

v32 修正麦老爹与机器人关卡的中文提示、部分物品名、繁中合成提示和两组装饰动画路径。四个资源有改动，其余 1,082 个成员与 v31 逐字节相同。[资源校验报告](内置中文版·v32fix·开源免费.report.json)

## 从最初的 IPA 重建

把 `ZFR 1.0.zh-CN-unsigned.ipa` 放在本目录。在仓库根目录用 Python 3.14 或更新版运行以下命令，即可生成本次构建使用的内置 IPA。

```powershell
python tools/cumulative_ipa.py apply
```

| 输入 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `ZFR 1.0.zh-CN-unsigned.ipa` | 58,788,319 | `E7CE2D18BC77E513B4B4B382E4A9AF9BB8A7133E5513B5A73955D3F3EE9A8F60` |
| [unsigned-to-v32fix.zst](unsigned-to-v32fix.zst) | 1,870,357 | `B4F8E48979A27D50463D738B6AD5BF032A5E80471BE18F0B0A34D5F7B6D11D69` |

可以用 `--base` 指定原始 IPA 所在位置，用 `--output` 指定输出文件。工具核对原包、还原的文件集合及最终 IPA 的 SHA-256，全部通过后写入目标。目录中已有内容不同的同名文件时会报错。生成差分的命令见 [IPA 工具](../tools/README.md)。

整包指纹包括 ZIP 压缩后的字节。若工具仅在最后的 `reconstructed IPA` 校验提示指纹不同，可用已实测的 conda-forge 环境重建：`conda create -n zfr-ipa -c conda-forge python=3.14.6 libzlib=1.3.2`，然后执行 `conda run -n zfr-ipa python tools/cumulative_ipa.py apply`。

## 本机与发行包

GitHub 发行版所用的完整 IPA 随对应的 Windows ZIP 放在 `zombie_farm_ipa/` 中。新工作区可用 Windows 运行初始化脚本导入与该发行对应的文件。游戏本体的版权归原权利人所有。Git 忽略完整 IPA，保存补丁、工具和报告。[游戏发行页](https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/latest) · [初始化步骤](../HANDOVER.md#源码入口)

- 本机 Windows 模拟器通过 `run/windows/zombie_farm_ipa/` 的 NTFS 目录联接访问这批文件。Windows 便携 ZIP 在 `zombie_farm_ipa/` 中放入内置 IPA，Android 构建在 `assets/` 中使用同一文件名。
- 文件名对应的 `*.report.json` 记录输入、输出校验值和补丁细节。v29fix-notice 在标题背景加入水印，v30fix-notice 优化字体和弹窗，v31fix-notice 仅更改启动图 `Payload/ZFR.app/Default.png`。其余 1,085 个成员与 v30 内容一致。[标题水印](Zombie%20Farm%20ZFR%201.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.report.json) · [v31 启动图报告](内置中文版·v31fix·开源免费.report.json) · [v30 补丁报告](Zombie%20Farm%20ZFR%201.0.zh-CN-complete-final.fixed-fonts-v30fix-notice.report.json) · [游戏 IPA 补丁谱系](../README.md#游戏-ipa-补丁谱系)
