**Windows 解压后运行「游戏管理.exe」；Android 可直接覆盖安装旧版。** 两端沿用原有存档格式，更新前可在管理器里备份存档。

## 本次更新

- **两端分辨率倍率上限扩展到 ×6**：继续支持小数和分数。Windows 在「自定义」中填写；Android 新增 ×4、×5、×6 预设。Android 新安装默认仍为 iPhone ×3。
- **九种付费农场主统一 15 脑子购买**：进入左上角「设置 → 农场主」，选择未解锁形象后可确认购买，永久解锁并保存；取消不扣费，已解锁形象可免费切换。
- **修复列表滑动长时间卡顿**：修复「设置 → 变异」列表和 iPhone 模式下入侵僵尸编队列表反复清空、重建内容的问题。Windows / Android 同步生效。

用户已在 Windows / Android 确认三项修改均成功。此次沿用验收通过的程序文件；Android APK 与 v13 测试包逐字节一致，Windows ZIP 仅将顶层文件夹改为正式版本名，45 个包内文件全部保持一致。

Android `versionCode` 为 **13**，签名保持不变，可覆盖安装。此前的模拟时间显示、Android 昼夜光照、商店黑块与云手机启动修复继续保留。

## 验证情况

- 两个平台三项修改均经用户游戏内实测确认。
- 生产库 68 项测试通过；当前 IPA 的只读 guest 列表谓词测试另 1 项通过；购买逻辑 10 项、原二进制产品映射 18 条通过。
- Windows 管理器自检、倍率解析、布局与独立启动通过；发行 ZIP 的 45 个文件、44 项 SHA-256、CRC 与完整内容回读均通过。
- Android 倍率解析、构建、包结构及原签名核验通过。游戏 IPA 与存档格式未改动。

## 文件校验

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `zombie-farm-windows-x64-v29fix-farmers-scroll.zip` | 95,463,321 B | `6EBD790D8446B74F4F994AE001771E857F6CF53B4CE4CD916B70A323C9781F3F` |
| `zombie-farm-android-arm64-v29fix-farmers-scroll.apk` | 97,348,980 B | `B10B909B2EDBC2809447E0DBA92106D539536238AC67D1BB18BF625FA350D780` |
| 包内 `touchHLE\touchHLE.exe` | 28,894,208 B | `120653FAE5B17E5CABAAC55BA754C648E6BB4C7E7E44241DF5033E31BB42AF37` |
| 包内游戏 IPA | 59,570,028 B | `7BB214498B149E11DECA49C19E5A21B9AA7F763646537206B85CBBAB86582FFC` |

Windows 包不含玩家存档或运行日志。可双击 `校验.bat` 或在管理器的「文件校验」页核对文件。

本项目免费、开源，官方地址：<https://github.com/Ashena1017/zombie-farm-touchhle-cn>。交流群 QQ：1185712984。
