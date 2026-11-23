# v3 字号调查

这里保留早期 `ZFAlertWindow` 字号调查的脚本。共享加载器 `zt.py` 和选择器解析器 `zsel.py` 从本机旧归档补齐，脚本从仓库的 `tools/` 加载通用解析器。

- `c13_final.py` 枚举早期在 `ZFAlertWindow` 调用点发现的字号。`ann.py` 和 `zscan.py` 提供反汇编注解和参数追踪。
- `c14_v3diff.py` 对照原始 `*.fixed.ipa` 和 `*.fixed-fonts-v3.ipa` 的 13 个补丁站点。

需要 Python、Capstone 和 `zombie_farm_ipa/` 下相应的旧版 IPA。当前工具入口见[工具索引](../../../tools/README.md)。
