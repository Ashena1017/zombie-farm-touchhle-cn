# 游戏 IPA 与补丁记录

Windows 和 Android 当前共用以下 IPA，作为 `v29fix-help-profile` 的游戏内容。

| 项目 | 值 |
| --- | --- |
| 文件名 | `Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa` |
| 大小 | 59,570,028 字节 |
| SHA-256 | `7BB214498B149E11DECA49C19E5A21B9AA7F763646537206B85CBBAB86582FFC` |

可以从本项目 GitHub 发行页下载 Windows ZIP，从解压后的 `zombie_farm_ipa/` 取出同名文件。新工作区可用 Windows 运行初始化脚本导入。游戏本体的版权归原权利人所有。IPA 文件由 Git 忽略，补丁报告随源码保存。[游戏发行页](https://github.com/Ashena1017/zombie-farm-touchhle-cn/releases/latest) · [初始化步骤](../HANDOVER.md#源码入口)

- 本机 Windows 模拟器通过 `run/windows/zombie_farm_ipa/` 的 NTFS 目录联接访问这批文件。Windows 便携 ZIP 内含当前发行的 IPA，Android 构建以 `assets/Zombie_Farm_v29fix.ipa` 为包内文件名。
- 旧版 IPA 是本机回归材料。文件名对应的 `*.report.json` 记录可用的输入、输出校验值和补丁细节。当前水印补丁以 v29fix 为输入，替换标题背景图片。保留旧版文件名和目录可供补丁链及历史验证脚本引用。[水印补丁报告](Zombie%20Farm%20ZFR%201.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.report.json) · [游戏 IPA 补丁谱系](../README.md#游戏-ipa-补丁谱系)
