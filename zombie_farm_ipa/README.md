# 游戏 IPA 与补丁记录

本工作区的 Windows 和 Android 构建共用 v30fix-notice，保留标题水印，裁小三张位图字体，并修复出售详情弹窗重复绘制正文的问题。

| 项目 | 值 |
| --- | --- |
| 文件名 | `Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v30fix-notice.ipa` |
| 大小 | 59,560,883 字节 |
| SHA-256 | `9C7A4CBAFE0B7636B541F9D8F7D40BC7F0DCDD33C3440BEBA3FC3C731B718339` |

## 从最初的 IPA 重建

把 `ZFR 1.0.zh-CN-unsigned.ipa` 放在本目录。在仓库根目录用 Python 3.14 或更新版运行以下命令，即可得到上述 v30 文件。

```powershell
python tools/cumulative_ipa.py apply
```

| 输入 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `ZFR 1.0.zh-CN-unsigned.ipa` | 58,788,319 | `E7CE2D18BC77E513B4B4B382E4A9AF9BB8A7133E5513B5A73955D3F3EE9A8F60` |
| [unsigned-to-v30fix-notice.zst](unsigned-to-v30fix-notice.zst) | 1,865,118 | `C613511980328504ECF48256F785136BB04DDF09999B44F8C8A5AAF3E5C47BE5` |

可以用 `--base` 指定原始 IPA 所在位置，用 `--output` 指定输出文件。工具核对原包、还原的文件集合及最终 IPA 的 SHA-256，全部通过后写入目标。目录中已有内容不同的同名文件时会报错。生成差分的命令见 [IPA 工具](../tools/README.md)。

整包指纹包括 ZIP 压缩后的字节。若工具仅在最后的 `reconstructed IPA` 校验提示指纹不同，可用已实测的 conda-forge 环境重建：`conda create -n zfr-ipa -c conda-forge python=3.14.6 libzlib=1.3.2`，然后执行 `conda run -n zfr-ipa python tools/cumulative_ipa.py apply`。

## 本机与发行包

GitHub 发行版所用的完整 IPA 随对应的 Windows ZIP 放在 `zombie_farm_ipa/` 中。新工作区可用 Windows 运行初始化脚本导入与该发行对应的文件。游戏本体的版权归原权利人所有。Git 忽略完整 IPA，保存补丁、工具和报告。[游戏发行页](https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/latest) · [初始化步骤](../HANDOVER.md#源码入口)

- 本机 Windows 模拟器通过 `run/windows/zombie_farm_ipa/` 的 NTFS 目录联接访问这批文件。Windows 便携 ZIP 内含当前发行的 IPA，Android 构建以 `assets/Zombie_Farm_v29fix.ipa` 为包内文件名。
- 旧版 IPA 是本机回归材料。文件名对应的 `*.report.json` 记录可用的输入、输出校验值和补丁细节。v29fix-notice 在 v29fix 的标题背景加入水印，v30fix-notice 在此基础上优化字体和弹窗。[水印补丁报告](Zombie%20Farm%20ZFR%201.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.report.json) · [v30 补丁报告](Zombie%20Farm%20ZFR%201.0.zh-CN-complete-final.fixed-fonts-v30fix-notice.report.json) · [游戏 IPA 补丁谱系](../README.md#游戏-ipa-补丁谱系)
