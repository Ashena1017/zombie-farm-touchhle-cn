# 历史维护资料

这些脚本和记录对应早期迁移、打包和反汇编取证。当前构建和校验入口在 [scripts/](../../scripts/README.md)。

| 目录 | 内容 |
|---|---|
| [maintenance/](maintenance) | 早期的目录迁移、批量改路径、全量构建和旧交付包测试，以文本形式保留原件。旧脚本假定当时的目录结构，部分会移动文件或停止模拟器进程。 |
| [fork-windows/](fork-windows) | 早期 fork 自带的 Windows 启动与打包入口。 |
| [zt/](zt) | v3 字号补丁取证、原来的反汇编脚本和配套模块。 |

本机曾用于旧版本的上传、Release 正文修改和附件清理脚本归档到 `_analysis/archive/release-scripts/`。正式发布流程见[维护交接](../../HANDOVER.md#准备发行)。
